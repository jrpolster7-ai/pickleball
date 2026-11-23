"""Standings and seeding (CLAUDE.md section 8). Pure Python, no database.

A "key" is whatever identifies a ranked entry: a team (Side) id for doubles,
a player id for Scramble.

Two ranking screens:
  1. Win and loss: wins, then total points, then point differential.
  2. Total points: total points, then wins, then point differential.
Bracket seeding: wins, then losses, then total points, then point
differential. A tie that's still left is flagged for the admin, who
decides. There is no automatic head-to-head rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, Iterable

Key = Hashable


@dataclass(frozen=True)
class Result:
    """One final match. side_a and side_b are tuples of keys (one team, or two Scramble players)."""

    side_a: tuple
    side_b: tuple
    games: tuple  # ((a points, b points), ...)
    winner: str   # "A" or "B"


@dataclass
class Row:
    key: Key
    played: int = 0
    wins: int = 0
    losses: int = 0
    points_for: int = 0
    points_against: int = 0
    rank: int = 0
    tied: bool = False
    extra: dict = field(default_factory=dict)  # labels, pools, and so on for screens

    @property
    def diff(self) -> int:
        return self.points_for - self.points_against


def tally(results: Iterable[Result], keys: Iterable[Key]) -> dict[Key, Row]:
    """Add up every final match. Every key gets a row, even with no matches."""
    rows = {k: Row(key=k) for k in keys}
    for r in results:
        a_points = sum(g[0] for g in r.games)
        b_points = sum(g[1] for g in r.games)
        for keys_, won, pf, pa in ((r.side_a, r.winner == "A", a_points, b_points),
                                   (r.side_b, r.winner == "B", b_points, a_points)):
            for k in keys_:
                row = rows.setdefault(k, Row(key=k))
                row.played += 1
                row.wins += won
                row.losses += not won
                row.points_for += pf
                row.points_against += pa
    return rows


def win_loss_key(row: Row):
    return (-row.wins, -row.points_for, -row.diff)


def total_points_key(row: Row):
    return (-row.points_for, -row.wins, -row.diff)


def seeding_key(row: Row):
    return (-row.wins, row.losses, -row.points_for, -row.diff)


def _ranked(rows: Iterable[Row], key) -> list[Row]:
    """Sort and number. Rows that tie on every rule share a rank (1, 2, 2, 4)."""
    ordered = sorted(rows, key=lambda r: (key(r), str(r.key)))
    ranked = []
    for i, row in enumerate(ordered):
        prev = ordered[i - 1] if i else None
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        same_as_prev = prev is not None and key(prev) == key(row)
        row = Row(**{**row.__dict__})  # a copy, so each screen has its own ranks
        row.rank = ranked[-1].rank if same_as_prev else i + 1
        row.tied = same_as_prev or (nxt is not None and key(nxt) == key(row))
        ranked.append(row)
    return ranked


def win_loss_ranking(rows: Iterable[Row]) -> list[Row]:
    return _ranked(rows, win_loss_key)


def total_points_ranking(rows: Iterable[Row]) -> list[Row]:
    return _ranked(rows, total_points_key)


@dataclass
class Seeding:
    order: list[Row]                 # seed 1 first
    ties: list[list[Row]]            # groups still tied on every rule
    unresolved: list[list[Row]]      # tie groups the admin hasn't ordered yet

    def unresolved_within(self, count: int) -> list[list[Row]]:
        """Ties that affect the top `count` seeds, including one that straddles the cut line."""
        position = {row.key: i for i, row in enumerate(self.order)}
        return [g for g in self.unresolved if min(position[r.key] for r in g) < count]


def seeding(rows: Iterable[Row], tiebreak: dict[Key, int] | None = None) -> Seeding:
    """Bracket seeds. `tiebreak` is the admin's order inside tie groups (lower goes first)."""
    tiebreak = tiebreak or {}
    groups: dict[tuple, list[Row]] = {}
    for row in (Row(**r.__dict__) for r in rows):
        groups.setdefault(seeding_key(row), []).append(row)
    order, ties, unresolved = [], [], []
    for stats in sorted(groups):
        group = groups[stats]
        group.sort(key=lambda r: (tiebreak.get(r.key, 10**6), str(r.key)))
        if len(group) > 1:
            ties.append(group)
            picks = [tiebreak.get(r.key) for r in group]
            if None in picks or len(set(picks)) != len(picks):
                unresolved.append(group)
        order.extend(group)
    for i, row in enumerate(order, start=1):
        row.rank = i
    return Seeding(order=order, ties=ties, unresolved=unresolved)
