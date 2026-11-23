"""Build and run a single elimination bracket from the round robin seeds (section 9)."""

from __future__ import annotations

import datetime
from itertools import groupby

from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone

from core import audit
from events.models import BracketSizing, BracketType, Event, Side
from scheduling.models import Match, Round, Session
from standings import services as standings_services

from .brackets import BracketError, feed_label, single_elimination


# --- Seeding ties ----------------------------------------------------------

@transaction.atomic
def set_tiebreak(event: Event, side_ids: list[int], actor=None) -> None:
    """The admin puts tied teams in order (section 8). First in the list gets the better seed."""
    sides = {s.pk: s for s in event.sides.filter(pk__in=side_ids)}
    if len(sides) != len(side_ids) or len(set(side_ids)) != len(side_ids):
        raise BracketError("Pick each tied team once.")
    for order, side_id in enumerate(side_ids, start=1):
        sides[side_id].tiebreak = order
    Side.objects.bulk_update(sides.values(), ["tiebreak"])
    names = ", ".join(sides[i].name for i in side_ids)
    audit.log(actor, "seeding tie decided", event, new=names, event=event)


# --- Building --------------------------------------------------------------

def build_problem(event: Event, count: int | None, table=None) -> str | None:
    """Why the bracket can't be built yet, or None."""
    if event.is_scramble:
        return "Scramble events don't have a bracket. The top ranked player wins."
    if event.bracket_type == BracketType.DOUBLE:
        return "Double elimination is coming in the next update. For now, switch this event to single elimination in its settings."
    if event.status != Event.Status.ROUND_ROBIN:
        if event.status in (Event.Status.BRACKET, Event.Status.COMPLETE):
            return "This event already has a bracket."
        return "Start play and finish the round robin first."
    table = table or standings_services.table(event)
    if table.remaining:
        return (f"{table.remaining} round robin match{'es are' if table.remaining != 1 else ' is'} "
                "not final yet. Finish or forfeit them first.")
    if count is None:
        return "Enter how many teams advance."
    if count < 2:
        return "At least 2 teams need to advance."
    if count > len(table.rows):
        return f"Only {len(table.rows)} teams played."
    ties = table.seeding().unresolved_within(count)
    if ties:
        return "Some teams are tied on every rule. Put them in order first."
    return None


def _schedule_start(event: Event, date: datetime.date | None, start: datetime.time | None):
    """Which session the bracket goes in, and when it starts."""
    last = event.sessions.order_by("-week").first()
    date = date or last.date
    session = event.sessions.filter(date=date).first()
    if session is None:
        week = (event.sessions.aggregate(m=Max("week"))["m"] or 0) + 1
        session = Session.objects.create(event=event, week=week, date=date)
    last_round = session.rounds.order_by("-number").first()
    if start:
        first = timezone.make_aware(datetime.datetime.combine(date, start))
    elif last_round:
        first = last_round.start_time + datetime.timedelta(minutes=event.minutes_per_match + event.break_minutes)
    else:
        first = timezone.make_aware(datetime.datetime.combine(date, event.start_time))
    next_number = (last_round.number if last_round else 0) + 1
    return session, first, next_number


@transaction.atomic
def build(event: Event, count: int, actor=None, *, date=None, start=None) -> list[Match]:
    """Seed the top `count` teams into a bracket and schedule it after the round robin."""
    event = Event.objects.select_for_update().select_related("division", "level").get(pk=event.pk)
    table = standings_services.table(event)
    problem = build_problem(event, count, table)
    if problem:
        raise BracketError(problem)
    seeds = [row.key for row in table.seeding().order[:count]]
    plan = single_elimination(count, play_in=event.bracket_sizing == BracketSizing.PLAY_IN,
                              third_place=event.third_place_match)

    session, first, number = _schedule_start(event, date, start)
    step = datetime.timedelta(minutes=event.minutes_per_match + event.break_minutes)
    courts = event.court_count
    by_key: dict[int, Match] = {}
    slot_time = first
    groups = groupby(plan.matches, key=lambda m: m.round)
    for _, group in groups:
        group = list(group)
        names = list(dict.fromkeys(m.label for m in group))
        label = names[0] + "".join(f" and {n.lower()}" for n in names[1:])  # "Final and third place"
        for start_index in range(0, len(group), courts):
            chunk = group[start_index:start_index + courts]
            rnd = Round.objects.create(event=event, session=session, number=number, start_time=slot_time, label=label)
            number += 1
            for court, planned in enumerate(chunk, start=1):
                match = Match(
                    event=event, round=rnd, court=court, start_time=slot_time, stage=Match.Stage.BRACKET,
                    bracket_round=planned.round, bracket_slot=planned.position, bracket_side="WINNERS",
                    bracket_label=planned.label, third_place=planned.third_place,
                    feed_a=feed_label(planned.a, plan), feed_b=feed_label(planned.b, plan),
                )
                if planned.a.kind == "seed":
                    match.side_a_id = seeds[planned.a.value - 1]
                if planned.b.kind == "seed":
                    match.side_b_id = seeds[planned.b.value - 1]
                match.save()
                by_key[planned.key] = match
            slot_time += step

    for planned in plan.matches:
        match = by_key[planned.key]
        if planned.winner_to:
            match.winner_to, match.winner_to_side = by_key[planned.winner_to[0]], planned.winner_to[1]
        if planned.loser_to:
            match.loser_to, match.loser_to_side = by_key[planned.loser_to[0]], planned.loser_to[1]
    Match.objects.bulk_update(by_key.values(), ["winner_to", "winner_to_side", "loser_to", "loser_to_side"])

    event.advancing_count = count
    event.status = Event.Status.BRACKET
    event.save(update_fields=["advancing_count", "status", "updated_at"])
    audit.log(actor, "bracket built", event, new=f"{count} teams, {len(by_key)} matches", event=event)
    return list(by_key.values())


@transaction.atomic
def delete(event: Event, actor=None) -> None:
    """Take the bracket down, only while no bracket match has a score."""
    event = Event.objects.select_for_update().get(pk=event.pk)
    matches = event.matches.filter(stage=Match.Stage.BRACKET)
    if not matches.exists():
        raise BracketError("There's no bracket to remove.")
    if matches.exclude(status=Match.Status.SCHEDULED).exists() or matches.filter(submissions__isnull=False).exists():
        raise BracketError("Bracket matches already have scores. Clear those scores first.")
    round_ids = set(matches.values_list("round_id", flat=True))
    matches.update(winner_to=None, loser_to=None)
    matches.delete()
    Round.objects.filter(pk__in=round_ids, matches__isnull=True).delete()
    event.sessions.filter(rounds__isnull=True).delete()
    event.advancing_count = None
    event.status = Event.Status.ROUND_ROBIN
    event.save(update_fields=["advancing_count", "status", "updated_at"])
    audit.log(actor, "bracket removed", event, event=event)


# --- Results move teams along ---------------------------------------------

def _place(target: Match | None, letter: str, side_id: int | None) -> None:
    if target is None:
        return
    target = Match.objects.select_for_update().get(pk=target.pk)
    field = f"side_{letter.lower()}_id"
    if getattr(target, field) == side_id:
        return
    if target.status != Match.Status.SCHEDULED or target.submissions.exists():
        raise BracketError(f"That would change who plays in {target}, which already has a score. "
                           "Clear that score first.")
    setattr(target, field, side_id)
    target.save(update_fields=[field])


def after_result(match: Match) -> None:
    """A bracket match just became final: send the winner (and semifinal loser) on."""
    if match.stage != Match.Stage.BRACKET:
        return
    _place(match.winner_to, match.winner_to_side, match.winning_side.pk)
    if match.loser_to_id:
        _place(match.loser_to, match.loser_to_side, match.losing_side.pk)
    _update_complete(match.event)


def after_clear(match: Match) -> None:
    """A bracket match lost its score: take its teams back out of later matches."""
    if match.stage != Match.Stage.BRACKET:
        return
    for target, letter in ((match.winner_to, match.winner_to_side), (match.loser_to, match.loser_to_side)):
        if target is not None:
            _place(target, letter, None)
    _update_complete(match.event)


def _update_complete(event: Event) -> None:
    bracket = event.matches.filter(stage=Match.Stage.BRACKET)
    final = bracket.filter(winner_to__isnull=True, third_place=False).first()
    third = bracket.filter(third_place=True).first()
    done = final and final.is_final and (third is None or third.is_final)
    status = Event.Status.COMPLETE if done else Event.Status.BRACKET
    if event.status != status and event.status in (Event.Status.BRACKET, Event.Status.COMPLETE):
        Event.objects.filter(pk=event.pk).update(status=status)
        event.status = status


# --- Showing it -------------------------------------------------------------

def bracket_rounds(event: Event):
    """[(round name, [matches])] in play order, ready for the bracket screen."""
    matches = (
        event.matches.filter(stage=Match.Stage.BRACKET)
        .select_related("side_a", "side_b", "round")
        .prefetch_related("side_a__players", "side_b__players", "games")
        .order_by("bracket_round", "third_place", "bracket_slot")
    )
    out = []
    for (_, _, label), group in groupby(matches, key=lambda m: (m.bracket_round, m.third_place, m.bracket_label)):
        out.append((label, list(group)))
    return out


def champion(event: Event) -> Side | None:
    final = (event.matches.filter(stage=Match.Stage.BRACKET, winner_to__isnull=True, third_place=False)
             .select_related("side_a", "side_b").first())
    if final and final.is_final:
        return final.winning_side
    return None
