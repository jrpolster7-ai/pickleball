"""Turn an event's settings into a schedule, and save it. Logic lives in engine.py."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from core import audit
from events import rules
from events.codes import new_code
from events.models import MAX_COURTS, Event, Registration, Side

from . import engine
from .engine import ScheduleError
from .models import Match, Round, Session


def pool_name(index: int | None) -> str:
    """Pools show as letters: Pool A, Pool B, ... (0-based index in)."""
    if index is None:
        return ""
    return f"Pool {chr(65 + index)}" if index < 26 else f"Pool {index + 1}"


# --- Preview ---------------------------------------------------------------

@dataclass
class PreviewMatch:
    court: int
    side_a: str
    side_b: str
    pool: str = ""


@dataclass
class PreviewRound:
    number: int
    start_time: datetime.datetime
    matches: list[PreviewMatch]
    sitting_out: list[str] = field(default_factory=list)


@dataclass
class CountRow:
    label: str
    per_week: int
    sit_outs: int
    pool: str = ""


@dataclass
class Preview:
    event: Event
    seed: int
    rounds: list[PreviewRound]  # week 1
    dates: list[datetime.date]
    counts: list[CountRow]
    notes: list[str]
    team_count: int = 0
    player_count: int = 0
    pool_count: int = 1
    plan: object = None
    labels: list[str] = field(default_factory=list)

    @property
    def matches_per_week(self) -> int:
        return sum(len(r.matches) for r in self.rounds)

    @property
    def total_matches(self) -> int:
        return self.matches_per_week * len(self.dates)

    @property
    def count_range(self) -> tuple[int, int]:
        values = [c.per_week for c in self.counts]
        return (min(values), max(values)) if values else (0, 0)


def _first_start(event: Event, date: datetime.date) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime.combine(date, event.start_time))


def _times(event: Event, date: datetime.date, count: int) -> list[datetime.datetime]:
    return engine.round_start_times(
        _first_start(event, date), count,
        minutes_per_match=event.minutes_per_match, break_minutes=event.break_minutes,
    )


def _team_sides(event: Event) -> list[Side]:
    return list(event.sides.filter(slot__isnull=True).prefetch_related("players").order_by("id"))


def _scramble_players(event: Event):
    regs = (
        event.registrations.filter(status=Registration.Status.ACTIVE)
        .select_related("player").order_by("id")
    )
    return [r.player for r in regs]


def build_preview(event: Event, seed: int = 1) -> Preview:
    """The schedule this event would get with this seed. Nothing is saved."""
    dates = engine.session_dates(event.start_date, event.weeks, event.weekly_day)
    courts = min(event.court_count, MAX_COURTS)
    notes: list[str] = []

    if event.is_scramble:
        players = _scramble_players(event)
        if not event.scramble_rounds:
            raise ScheduleError("Set the number of rounds in the event settings first.")
        if len(players) < 4:
            raise ScheduleError(f"Scramble needs at least 4 players. {len(players)} signed up so far.")
        plan = engine.scramble(len(players), rounds=event.scramble_rounds, courts=courts, seed=seed)
        labels = [p.full_name for p in players]
        games = min(courts, len(players) // 4)
        sitting = len(players) - games * 4
        if sitting:
            notes.append(f"{games} games per round, so {sitting} players sit out each round. Sit-outs take turns.")
        times = _times(event, dates[0], len(plan.rounds))
        rounds = []
        for i, rnd in enumerate(plan.rounds):
            in_round = {p for (a, b) in rnd for p in (*a, *b)}
            rounds.append(PreviewRound(
                number=i + 1,
                start_time=times[i],
                matches=[
                    PreviewMatch(court=c + 1, side_a=f"{labels[a1]} & {labels[a2]}", side_b=f"{labels[b1]} & {labels[b2]}")
                    for c, ((a1, a2), (b1, b2)) in enumerate(rnd)
                ],
                sitting_out=[labels[p] for p in range(len(players)) if p not in in_round],
            ))
        played = plan.games_per_player()
        sat = plan.sit_outs_per_player()
        counts = [CountRow(label=labels[p], per_week=played[p], sit_outs=sat[p]) for p in range(len(players))]
        return Preview(event=event, seed=seed, rounds=rounds, dates=dates, counts=counts, notes=notes,
                       player_count=len(players), plan=plan, labels=labels)

    if not event.team_count:
        raise ScheduleError("Set the number of teams in the event settings first.")
    if not event.matches_per_team and not event.total_matches:
        raise ScheduleError("Set matches per team in the event settings first.")
    sides = _team_sides(event)
    n = max(event.team_count, len(sides))
    if len(sides) > event.team_count:
        notes.append(f"There are {len(sides)} teams but the event is set for {event.team_count}. "
                     f"The schedule uses all {len(sides)}.")
    if n == event.team_count and event.total_matches:
        total = event.total_matches
    else:
        total = rules.total_from_per_team(n, event.matches_per_team)
    plan = engine.round_robin(
        n, courts=courts, total=total, per_team=event.matches_per_team,
        pool_size=event.pool_size, seed=seed,
    )
    labels = [s.name for s in sides] + [f"Team {i + 1} (open spot)" for i in range(len(sides), n)]
    open_spots = n - len(sides)
    if open_spots:
        notes.append(f"{open_spots} of {n} team spots are still open. New teams fill them as they sign up.")
    if len(plan.pools) > 1:
        sizes = sorted({len(p) for p in plan.pools})
        notes.append(f"{len(plan.pools)} pools of {' or '.join(map(str, sizes))} teams, snake-seeded. "
                     "Each pool plays its own round robin.")
    full_per_team, _ = rules.full_round_robin(n)
    if len(plan.pools) == 1:
        notes.append(f"For reference, a full round robin is {full_per_team} matches per team "
                     f"({rules.full_round_robin(n)[1]} total).")

    times = _times(event, dates[0], len(plan.rounds))
    multi_pool = len(plan.pools) > 1
    rounds = []
    for i, rnd in enumerate(plan.rounds):
        busy = {t for m in rnd for t in (m.a, m.b)}
        rounds.append(PreviewRound(
            number=i + 1,
            start_time=times[i],
            matches=[PreviewMatch(court=m.court, side_a=labels[m.a], side_b=labels[m.b],
                                  pool=pool_name(m.pool) if multi_pool else "") for m in rnd],
            sitting_out=[labels[t] for t in range(n) if t not in busy],
        ))
    pool_of = {t: idx for idx, members in enumerate(plan.pools) for t in members}
    byes = plan.byes_per_team()
    counts = [
        CountRow(label=labels[t], per_week=plan.matches_per_team[t], sit_outs=byes[t],
                 pool=pool_name(pool_of[t]) if multi_pool else "")
        for t in range(n)
    ]
    return Preview(event=event, seed=seed, rounds=rounds, dates=dates, counts=counts, notes=notes,
                   team_count=n, pool_count=len(plan.pools), plan=plan, labels=labels)


# --- Publish and clear -----------------------------------------------------

def _check_can_change(event: Event) -> None:
    if event.schedule_locked:
        raise ScheduleError("Play has started, so the schedule can't be rebuilt. Edit matches one at a time instead.")


@transaction.atomic
def publish(event: Event, seed: int, actor=None) -> Preview:
    """Save the previewed schedule. The same seed gives exactly what the admin saw."""
    event = Event.objects.select_for_update().select_related("division", "level").get(pk=event.pk)
    _check_can_change(event)
    if event.has_schedule:
        raise ScheduleError("This event already has a schedule. Clear it first to make a new one.")
    preview = build_preview(event, seed)
    plan = preview.plan
    orders = engine.week_round_orders(len(preview.rounds), len(preview.dates), seed)

    if event.is_scramble:
        players = _scramble_players(event)
    else:
        sides = _team_sides(event)
        pool_of = {t: idx for idx, members in enumerate(plan.pools) for t in members}
        multi_pool = len(plan.pools) > 1
        for slot in range(len(sides), preview.team_count):
            sides.append(Side.objects.create(event=event, team_code=new_code()))
        for slot, side in enumerate(sides):
            side.slot = slot + 1
            side.pool = pool_of[slot] + 1 if multi_pool else None
        Side.objects.bulk_update(sides, ["slot", "pool"])
        if multi_pool:
            for side in sides:
                Registration.objects.filter(event=event, player__in=side.players.all()).update(pool=side.pool)

    match_rows = []
    scramble_lineups = []  # (match index, side a players, side b players)
    for week, (date, order) in enumerate(zip(preview.dates, orders), start=1):
        session = Session.objects.create(event=event, week=week, date=date)
        times = _times(event, date, len(order))
        for number, source in enumerate(order, start=1):
            rnd = Round.objects.create(event=event, session=session, number=number, start_time=times[number - 1])
            if event.is_scramble:
                for court, ((a1, a2), (b1, b2)) in enumerate(plan.rounds[source], start=1):
                    scramble_lineups.append((len(match_rows), (players[a1], players[a2]), (players[b1], players[b2])))
                    match_rows.append(Match(event=event, round=rnd, court=court, start_time=rnd.start_time,
                                            side_a_id=0, side_b_id=0))
            else:
                for m in plan.rounds[source]:
                    match_rows.append(Match(
                        event=event, round=rnd, court=m.court, start_time=rnd.start_time,
                        side_a=sides[m.a], side_b=sides[m.b],
                        pool=m.pool + 1 if multi_pool else None,
                    ))

    if event.is_scramble:
        _make_scramble_sides(event, match_rows, scramble_lineups)
    Match.objects.bulk_create(match_rows, batch_size=500)

    event.schedule_seed = seed
    event.save(update_fields=["schedule_seed", "updated_at"])
    audit.log(actor, "schedule published", event, new=f"seed {seed}, {len(match_rows)} matches", event=event)
    return preview


def _make_scramble_sides(event, match_rows, lineups) -> None:
    """Scramble sides are made fresh for every game (section 16)."""
    new_sides = [Side(event=event) for _ in range(2 * len(lineups))]
    Side.objects.bulk_create(new_sides, batch_size=500)
    Through = Side.players.through
    links = []
    for k, (index, team_a, team_b) in enumerate(lineups):
        side_a, side_b = new_sides[2 * k], new_sides[2 * k + 1]
        match_rows[index].side_a = side_a
        match_rows[index].side_b = side_b
        links += [Through(side_id=side_a.pk, player_id=p.pk) for p in team_a]
        links += [Through(side_id=side_b.pk, player_id=p.pk) for p in team_b]
    Through.objects.bulk_create(links, batch_size=1000)


@transaction.atomic
def clear(event: Event, actor=None) -> None:
    """Throw away the schedule so a new one can be made. Teams and players stay."""
    event = Event.objects.select_for_update().select_related("division").get(pk=event.pk)
    _check_can_change(event)
    count = event.matches.count()
    event.matches.all().delete()
    event.rounds.all().delete()
    event.sessions.all().delete()
    if event.is_scramble:
        event.sides.filter(slot__isnull=True, team_code__isnull=True).delete()
    else:
        event.sides.filter(slot__isnull=False, players=None).delete()
        event.sides.update(slot=None, pool=None)
        event.registrations.update(pool=None)
    event.schedule_seed = None
    event.save(update_fields=["schedule_seed", "updated_at"])
    audit.log(actor, "schedule cleared", event, old=f"{count} matches", event=event)


@transaction.atomic
def start_play(event: Event, actor=None) -> None:
    """Move to the round robin. After this the schedule is never regenerated."""
    if not event.has_schedule:
        raise ScheduleError("Publish a schedule before starting play.")
    if event.status not in (Event.Status.DRAFT, Event.Status.OPEN):
        raise ScheduleError("Play has already started.")
    old = event.get_status_display()
    event.status = Event.Status.ROUND_ROBIN
    event.save(update_fields=["status", "updated_at"])
    audit.log(actor, "status changed", event, old=old, new=event.get_status_display(), event=event)


# --- Editing times and courts ---------------------------------------------

def _fmt(dt: datetime.datetime) -> str:
    return timezone.localtime(dt).strftime("%Y-%m-%d %I:%M %p")


@transaction.atomic
def set_round_time(rnd: Round, new_time: datetime.time, actor=None) -> None:
    """Move a round. Every match in it moves too."""
    new_start = _first_start_for(rnd.session.date, new_time)
    old = rnd.start_time
    rnd.start_time = new_start
    rnd.save(update_fields=["start_time"])
    rnd.matches.update(start_time=new_start)
    audit.log(actor, "round time changed", rnd, old=_fmt(old), new=_fmt(new_start), event=rnd.event)


def _first_start_for(date: datetime.date, time: datetime.time) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime.combine(date, time))


@transaction.atomic
def edit_match(match: Match, *, start_time: datetime.time, court: int, actor=None) -> None:
    """Change one match's start time or court."""
    if not 1 <= court <= MAX_COURTS:
        raise ScheduleError(f"Court must be 1 to {MAX_COURTS}.")
    clash = Match.objects.filter(round=match.round, court=court).exclude(pk=match.pk).first()
    if clash:
        raise ScheduleError(f"Court {court} is already used in this round. Move that match first.")
    new_start = _first_start_for(match.round.session.date, start_time)
    old = f"court {match.court}, {_fmt(match.start_time)}"
    match.court = court
    match.start_time = new_start
    match.save(update_fields=["court", "start_time"])
    audit.log(actor, "match edited", match, old=old, new=f"court {court}, {_fmt(new_start)}", event=match.event)


@transaction.atomic
def retime(event: Event, actor=None) -> None:
    """Recalculate every start time from the event's start time and match length.

    Use after changing minutes per match or minutes between rounds. Hand edits
    to times are replaced.
    """
    for session in event.sessions.prefetch_related("rounds"):
        rounds = list(session.rounds.order_by("number"))
        times = _times(event, session.date, len(rounds))
        for rnd, start in zip(rounds, times):
            rnd.start_time = start
        Round.objects.bulk_update(rounds, ["start_time"])
        for rnd in rounds:
            rnd.matches.update(start_time=rnd.start_time)
    audit.log(actor, "times recalculated", event,
              new=f"{event.minutes_per_match} min matches, {event.break_minutes} min breaks", event=event)


# --- Reading a saved schedule ---------------------------------------------

def saved_rounds(event: Event):
    """Sessions with rounds and matches, ready to show. One query per level, no N+1."""
    side_players = ("side_a__players", "side_b__players")
    matches = Match.objects.order_by("court").prefetch_related(*side_players)
    rounds = Round.objects.order_by("number").prefetch_related(Prefetch("matches", queryset=matches))
    return event.sessions.prefetch_related(Prefetch("rounds", queryset=rounds))


def saved_counts(event: Event) -> list[CountRow]:
    """Matches per team (or games per player for Scramble) in the saved schedule, all weeks."""
    weeks = max(event.sessions.count(), 1)
    rounds = event.rounds.count()
    if event.is_scramble:
        Through = Side.players.through
        played = {p.pk: 0 for p in _scramble_players(event)}
        names = {p.pk: p.full_name for p in _scramble_players(event)}
        in_matches = Through.objects.filter(side__event=event, side__slot__isnull=True)
        for player_id in in_matches.values_list("player_id", flat=True):
            if player_id in played:
                played[player_id] += 1
        return [CountRow(label=names[pk], per_week=c // weeks, sit_outs=(rounds - c) // weeks)
                for pk, c in sorted(played.items(), key=lambda kv: names[kv[0]])]
    sides = list(event.sides.filter(slot__isnull=False).prefetch_related("players").order_by("slot"))
    played = {s.pk: 0 for s in sides}
    for a, b in event.matches.values_list("side_a_id", "side_b_id"):
        played[a] = played.get(a, 0) + 1
        played[b] = played.get(b, 0) + 1
    return [CountRow(label=s.name, per_week=played[s.pk] // weeks, sit_outs=(rounds - played[s.pk]) // weeks,
                     pool=pool_name(s.pool - 1) if s.pool else "") for s in sides]
