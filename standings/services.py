"""Load an event's results and rank them. The ranking rules live in standings.py."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Prefetch

from events.models import Event, Registration, Side
from scheduling.models import Match
from scheduling.services import pool_name
from scoring.models import Game

from . import standings
from .standings import Result, Row, Seeding


@dataclass
class Table:
    event: Event
    rows: list[Row]               # one per team (or player for Scramble), unranked
    pools: list[tuple[str, list[Row]]]  # (pool name, rows) when the event has pools
    remaining: int                # round robin matches not final yet

    @property
    def win_loss(self) -> list[Row]:
        return standings.win_loss_ranking(self.rows)

    @property
    def total_points(self) -> list[Row]:
        return standings.total_points_ranking(self.rows)

    def pool_rankings(self, view: str) -> list[tuple[str, list[Row]]]:
        rank = standings.total_points_ranking if view == "points" else standings.win_loss_ranking
        return [(name, rank(rows)) for name, rows in self.pools]

    def seeding(self) -> Seeding:
        return standings.seeding(self.rows, {r.key: r.extra["tiebreak"] for r in self.rows
                                             if r.extra.get("tiebreak") is not None})


def _round_robin_matches(event: Event):
    return (
        Match.objects.filter(event=event, stage=Match.Stage.ROUND_ROBIN)
        .only("id", "round_id", "side_a_id", "side_b_id", "status", "winner")
        .prefetch_related(Prefetch("games", queryset=Game.objects.only("match_id", "side_a_points", "side_b_points")))
    )


def table(event: Event, *, spectator: bool = False) -> Table:
    """Every round robin result added up. Multi-week events sum all weeks.

    For spectators, only rounds where every match is final count, and names
    are first name and last initial (section 10).
    """
    matches = list(_round_robin_matches(event))
    final = [m for m in matches if m.status == Match.Status.CONFIRMED]
    remaining = len(matches) - len(final)
    if spectator:
        from scheduling.display import revealed_round_ids

        revealed = revealed_round_ids(event)
        final = [m for m in final if m.round_id in revealed]

    if event.is_scramble:
        Through = Side.players.through
        side_ids = {m.side_a_id for m in final} | {m.side_b_id for m in final}
        members: dict[int, list[int]] = {}
        for side_id, player_id in Through.objects.filter(side_id__in=side_ids).values_list("side_id", "player_id"):
            members.setdefault(side_id, []).append(player_id)
        regs = (event.registrations.filter(status=Registration.Status.ACTIVE)
                .select_related("player").order_by("player__last_name", "player__first_name"))
        players = [r.player for r in regs]
        results = [Result(tuple(members.get(m.side_a_id, ())), tuple(members.get(m.side_b_id, ())),
                          tuple((g.side_a_points, g.side_b_points) for g in m.games.all()), m.winner)
                   for m in final]
        rows = standings.tally(results, [p.pk for p in players])
        names = {p.pk: (p.public_name if spectator else p.full_name) for p in players}
        for key, row in rows.items():
            row.extra = {"label": names.get(key, "Former player"), "pool": "", "tiebreak": None}
        return Table(event=event, rows=list(rows.values()), pools=[], remaining=remaining)

    sides = list(event.sides.filter(slot__isnull=False).prefetch_related("players").order_by("slot"))
    results = [Result((m.side_a_id,), (m.side_b_id,),
                      tuple((g.side_a_points, g.side_b_points) for g in m.games.all()), m.winner)
               for m in final]
    rows = standings.tally(results, [s.pk for s in sides])
    by_id = {s.pk: s for s in sides}
    for key, row in rows.items():
        side = by_id[key]
        row.extra = {"label": side.public_name if spectator else side.name, "slot": side.slot,
                     "tiebreak": side.tiebreak,
                     "pool": pool_name(side.pool - 1) if side.pool else ""}
    pool_groups: dict[str, list[Row]] = {}
    for row in rows.values():
        if row.extra["pool"]:
            pool_groups.setdefault(row.extra["pool"], []).append(row)
    pools = sorted(pool_groups.items())
    return Table(event=event, rows=list(rows.values()), pools=pools, remaining=remaining)
