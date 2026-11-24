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

from .brackets import FINAL, LOSERS, BracketError, double_elimination, feed_label, single_elimination


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


def plan_for(event: Event, count: int):
    """The bracket shape for this event's settings."""
    play_in = event.bracket_sizing == BracketSizing.PLAY_IN
    if event.bracket_type == BracketType.DOUBLE:
        return double_elimination(count, play_in=play_in)
    return single_elimination(count, play_in=play_in, third_place=event.third_place_match)


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
    plan = plan_for(event, count)

    session, first, number = _schedule_start(event, date, start)
    step = datetime.timedelta(minutes=event.minutes_per_match + event.break_minutes)
    courts = event.court_count
    by_key: dict[int, Match] = {}
    slot_time = first
    # One time slot per wave (more if there are more matches than courts).
    for _, group in groupby(sorted(plan.matches, key=lambda m: m.wave), key=lambda m: m.wave):
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
                    bracket_round=planned.round, bracket_slot=planned.position, bracket_side=planned.side,
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
    """A bracket match just became final: send the winner (and a loser who plays on) along."""
    if match.stage != Match.Stage.BRACKET:
        return
    if match.winner_to_id:
        _place(match.winner_to, match.winner_to_side, match.winning_side.pk)
    if match.loser_to_id:
        _place(match.loser_to, match.loser_to_side, match.losing_side.pk)
    if _is_grand_final(match):
        if match.winner == "B":
            _ensure_reset(match)
        else:
            _remove_reset(match.event)
    _update_complete(match.event)


def after_clear(match: Match) -> None:
    """A bracket match lost its score: take its teams back out of later matches."""
    if match.stage != Match.Stage.BRACKET:
        return
    for target, letter in ((match.winner_to, match.winner_to_side), (match.loser_to, match.loser_to_side)):
        if target is not None:
            _place(target, letter, None)
    if _is_grand_final(match):
        _remove_reset(match.event)
    _update_complete(match.event)


# --- Double elimination grand final ---------------------------------------
# Side A of the grand final is the winners bracket champion (no losses).
# If side B, the losers bracket champion, wins, both have one loss, so they
# play once more: the reset (ASSUMED, section 9).

def _is_grand_final(match: Match) -> bool:
    return match.bracket_side == FINAL and match.bracket_round == 1


def _reset_match(event: Event) -> Match | None:
    return event.matches.filter(stage=Match.Stage.BRACKET, bracket_side=FINAL, bracket_round=2).first()


def _ensure_reset(grand_final: Match) -> Match:
    reset = _reset_match(grand_final.event)
    if reset:
        return reset
    event = grand_final.event
    rnd = grand_final.round
    step = datetime.timedelta(minutes=event.minutes_per_match + event.break_minutes)
    last_number = rnd.session.rounds.aggregate(m=Max("number"))["m"]
    slot = Round.objects.create(event=event, session=rnd.session, number=last_number + 1,
                                start_time=rnd.start_time + step, label="Grand final reset")
    return Match.objects.create(
        event=event, round=slot, court=1, start_time=slot.start_time, stage=Match.Stage.BRACKET,
        bracket_round=2, bracket_slot=1, bracket_side=FINAL, bracket_label="Grand final reset",
        side_a=grand_final.side_a, side_b=grand_final.side_b,
        feed_a=grand_final.feed_a, feed_b=grand_final.feed_b,
    )


def _remove_reset(event: Event) -> None:
    reset = _reset_match(event)
    if reset is None:
        return
    if reset.status != Match.Status.SCHEDULED or reset.submissions.exists():
        raise BracketError("The grand final reset already has a score. Clear that score first.")
    rnd = reset.round
    reset.delete()
    if not rnd.matches.exists():
        rnd.delete()


def _deciding_match(event: Event) -> Match | None:
    """The match whose winner is champion: the final, or the grand final (or its reset)."""
    bracket = event.matches.filter(stage=Match.Stage.BRACKET).select_related("side_a", "side_b")
    reset = bracket.filter(bracket_side=FINAL, bracket_round=2).first()
    if reset:
        return reset
    grand_final = bracket.filter(bracket_side=FINAL, bracket_round=1).first()
    if grand_final:
        return grand_final if grand_final.is_final and grand_final.winner == "A" else None
    return bracket.filter(winner_to__isnull=True, third_place=False).first()


def _update_complete(event: Event) -> None:
    deciding = _deciding_match(event)
    third = event.matches.filter(stage=Match.Stage.BRACKET, third_place=True).first()
    done = bool(deciding and deciding.is_final and (third is None or third.is_final))
    status = Event.Status.COMPLETE if done else Event.Status.BRACKET
    if event.status != status and event.status in (Event.Status.BRACKET, Event.Status.COMPLETE):
        Event.objects.filter(pk=event.pk).update(status=status)
        event.status = status


def champion(event: Event) -> Side | None:
    deciding = _deciding_match(event)
    return deciding.winning_side if deciding and deciding.is_final else None


def third_place(event: Event) -> Side | None:
    """Single elimination: the third-place match winner. Double: the losers final loser (section 9)."""
    bracket = event.matches.filter(stage=Match.Stage.BRACKET).select_related("side_a", "side_b")
    match = bracket.filter(third_place=True).first()
    if match:
        return match.winning_side if match.is_final else None
    losers_final = bracket.filter(bracket_side=LOSERS).order_by("-bracket_round").first()
    if losers_final and losers_final.is_final:
        return losers_final.losing_side
    return None


# --- Showing it -------------------------------------------------------------

def bracket_sections(event: Event):
    """[(section name, [(round name, [matches])])] for the bracket screen.

    Single elimination is one unnamed section. Double elimination has the
    winners bracket, the losers bracket, and the grand final.
    """
    matches = list(
        event.matches.filter(stage=Match.Stage.BRACKET)
        .select_related("side_a", "side_b", "round")
        .prefetch_related("side_a__players", "side_b__players", "games")
        .order_by("bracket_round", "third_place", "bracket_slot")
    )
    order = {"WINNERS": 0, "LOSERS": 1, FINAL: 2}
    names = {"WINNERS": "Winners bracket", "LOSERS": "Losers bracket", FINAL: "Grand final"}
    double = any(m.bracket_side in ("LOSERS", FINAL) for m in matches)
    matches.sort(key=lambda m: (order.get(m.bracket_side, 0), m.bracket_round, m.third_place, m.bracket_slot))
    sections = []
    for side, side_matches in groupby(matches, key=lambda m: m.bracket_side):
        rounds = [(label, list(ms)) for (_, _, label), ms in
                  groupby(side_matches, key=lambda m: (m.bracket_round, m.third_place, m.bracket_label))]
        sections.append((names.get(side, "") if double else "", rounds))
    return sections
