"""Score rules (CLAUDE.md section 7). Pure Python, no database, easy to test.

Games are (side A points, side B points) pairs, always in A-B order no matter
who typed them in.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
A, B = "A", "B"

Game = tuple[int, int]


@dataclass(frozen=True)
class GameRules:
    points_to_win: int = 11
    win_by_two: bool = True
    point_cap: int | None = None
    games_per_match: int = 3  # 1, or best of 3

    @classmethod
    def from_event(cls, event) -> "GameRules":
        return cls(
            points_to_win=event.points_to_win,
            win_by_two=event.win_by_two,
            point_cap=event.point_cap,
            games_per_match=event.games_per_match,
        )

    @property
    def games_to_win(self) -> int:
        return self.games_per_match // 2 + 1


def game_problem(a: int, b: int, rules: GameRules) -> str | None:
    """Why this game score can't happen, or None if it can."""
    target, cap = rules.points_to_win, rules.point_cap
    if a < 0 or b < 0:
        return "Scores can't be negative."
    if a == b:
        return "A game can't end in a tie."
    high, low = max(a, b), min(a, b)
    if cap and high > cap:
        return f"No one can score more than {cap}. That's the point cap."
    if high < target:
        return f"Games go to {target}. The winner needs {target} points."
    if not rules.win_by_two:
        if high != target:
            return f"Games end as soon as someone reaches {target}, so {high} to {low} isn't possible."
        return None
    if low <= target - 2:
        if high != target:
            return f"With win by two, the game ends at {target} to {low}, so {high} to {low} isn't possible."
        return None
    # Close game: past (target - 1) all, play on until someone leads by two,
    # or until the cap, where one point is enough.
    if high - low == 2 or (cap and high == cap and high - low == 1):
        return None
    if high - low == 1:
        return f"{high} to {low} isn't a finished game. With win by two, play goes on until someone leads by 2."
    return f"{high} to {low} isn't possible. A close game ends as soon as someone leads by 2."


def game_winner(game: Game) -> str:
    return A if game[0] > game[1] else B


def match_problem(games: list[Game], rules: GameRules) -> str | None:
    """Why this list of games isn't a complete, valid match, or None if it is."""
    if not games:
        return "Enter the score for each game."
    if rules.games_per_match == 1 and len(games) != 1:
        return "This match is one game. Enter just one score."
    if len(games) > rules.games_per_match:
        return f"This match is best of {rules.games_per_match}."
    for number, (a, b) in enumerate(games, start=1):
        problem = game_problem(a, b, rules)
        if problem:
            return f"Game {number}: {problem}"
    wins = {A: 0, B: 0}
    for number, game in enumerate(games, start=1):
        if max(wins.values()) >= rules.games_to_win:
            return f"The match was already over after game {number - 1}. Remove game {number}."
        wins[game_winner(game)] += 1
    if max(wins.values()) < rules.games_to_win:
        return f"The match isn't finished. Someone needs to win {rules.games_to_win} games."
    return None


def match_winner(games: list[Game]) -> str:
    wins = {A: 0, B: 0}
    for game in games:
        wins[game_winner(game)] += 1
    return A if wins[A] > wins[B] else B


def forfeit_games(winner: str, rules: GameRules, points: int | None = None) -> list[Game]:
    """The recorded score for a forfeit.

    ASSUMED (section 6): the winner gets the games they needed, each at
    `points` to 0. `points` defaults to the points to win, so 11 to 0.
    """
    points = points or rules.points_to_win
    game = (points, 0) if winner == A else (0, points)
    return [game] * rules.games_to_win


def lock_deadline(day: datetime.date) -> datetime.datetime:
    """Player edits lock at midnight at the end of the match's day, Central time."""
    next_day = day + datetime.timedelta(days=1)
    return datetime.datetime.combine(next_day, datetime.time(0, 0), tzinfo=CENTRAL)


def score_text(games: list[Game]) -> str:
    """'11-7, 9-11, 11-5' for logs and screens."""
    return ", ".join(f"{a}-{b}" for a, b in games)
