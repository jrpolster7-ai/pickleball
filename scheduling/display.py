"""What each audience sees of the schedule (section 10).

Audiences:
  "admin"     everything, with links to fix scores
  "player"    everything, with links to enter their own scores
  "spectator" read-only. A round's results show only once every match in
              it is final (ASSUMED rule in section 10). Names are first
              name and last initial.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from django.db.models import Prefetch
from django.urls import reverse

from .models import Match, Round

ADMIN, PLAYER, SPECTATOR = "admin", "player", "spectator"


def revealed_round_ids(event) -> set[int]:
    """Rounds where every match is final. Spectators see results for these only."""
    open_rounds = (Match.objects.filter(event=event).exclude(status=Match.Status.CONFIRMED)
                   .values_list("round_id", flat=True))
    return set(Round.objects.filter(event=event).exclude(pk__in=open_rounds).values_list("pk", flat=True))


def side_name(side, audience: str, fallback: str = "To be decided") -> str:
    if side is None:
        return fallback
    return side.public_name if audience == SPECTATOR else side.name


def has_player(side, player) -> bool:
    return bool(side and player and any(p.pk == player.pk for p in side.players.all()))


@dataclass
class MatchRow:
    court: int
    start_time: datetime.datetime
    side_a: str
    side_b: str
    score: str = ""
    note: str = ""
    winner: str = ""  # "A" or "B" once shown as final
    mine: bool = False
    link: str = ""
    pool: str = ""


@dataclass
class RoundPanel:
    index: int  # 1-based position in the viewer
    number: int
    week: int
    start_time: datetime.datetime
    matches: list[MatchRow] = field(default_factory=list)
    revealed: bool = True
    done: bool = False

    @property
    def has_mine(self) -> bool:
        return any(m.mine for m in self.matches)


def match_row(match: Match, audience: str, *, player=None, revealed: bool = True) -> MatchRow:
    mine = has_player(match.side_a, player) or has_player(match.side_b, player)
    row = MatchRow(
        court=match.court, start_time=match.start_time,
        side_a=side_name(match.side_a, audience, match.feed_a or "To be decided"),
        side_b=side_name(match.side_b, audience, match.feed_b or "To be decided"),
        mine=mine, pool=match.pool_label,
    )
    if audience == ADMIN:
        row.link = reverse("scoring:admin_match", args=[match.event_id, match.pk])
    elif audience == PLAYER and mine:
        row.link = reverse("scoring:match_score", args=[match.pk])

    final = match.status == Match.Status.CONFIRMED
    if audience == SPECTATOR and not revealed:
        return row
    if final:
        row.score = match.score + (" (forfeit)" if match.forfeit else "")
        row.winner = match.winner
    elif match.status == Match.Status.PENDING:
        row.note = "Waiting for confirmation"
    elif match.status == Match.Status.DISPUTED:
        row.note = "Being checked by the organizer"
    return row


def round_robin_rounds(event):
    """Round robin rounds with their matches, sides, players, and games. A fixed number of queries."""
    matches = (Match.objects.filter(stage=Match.Stage.ROUND_ROBIN).order_by("court")
               .select_related("side_a", "side_b")
               .prefetch_related("side_a__players", "side_b__players", "games"))
    return (Round.objects.filter(event=event, label="").select_related("session")
            .order_by("session__week", "number")
            .prefetch_related(Prefetch("matches", queryset=matches)))


def round_viewer(event, audience: str, *, player=None) -> list[RoundPanel]:
    revealed = revealed_round_ids(event) if audience == SPECTATOR else None
    panels = []
    for i, rnd in enumerate(round_robin_rounds(event), start=1):
        matches = list(rnd.matches.all())
        if not matches:
            continue
        shown = revealed is None or rnd.pk in revealed
        panels.append(RoundPanel(
            index=i, number=rnd.number, week=rnd.session.week, start_time=rnd.start_time,
            matches=[match_row(m, audience, player=player, revealed=shown) for m in matches],
            revealed=shown,
            done=all(m.status == Match.Status.CONFIRMED for m in matches),
        ))
    for index, panel in enumerate(panels, start=1):
        panel.index = index
    return panels


def current_index(panels: list[RoundPanel], requested: str | None = None) -> int:
    """The round to open on: the one asked for, else the first one still being played."""
    if requested and requested.isdigit() and 1 <= int(requested) <= len(panels):
        return int(requested)
    for panel in panels:
        if not panel.done:
            return panel.index
    return panels[-1].index if panels else 1
