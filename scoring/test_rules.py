"""Score validation and the midnight Central lock (section 7)."""

import datetime
from zoneinfo import ZoneInfo

import pytest

from scoring.rules import (
    GameRules,
    forfeit_games,
    game_problem,
    lock_deadline,
    match_problem,
    match_winner,
    score_text,
)

UTC = ZoneInfo("UTC")
TO_11 = GameRules(points_to_win=11, win_by_two=True)
NO_WIN_BY_2 = GameRules(points_to_win=11, win_by_two=False)
CAP_15 = GameRules(points_to_win=11, win_by_two=True, point_cap=15)
ONE_GAME = GameRules(games_per_match=1)


@pytest.mark.parametrize("a,b", [(11, 0), (11, 9), (7, 11), (12, 10), (10, 12), (14, 12), (25, 23)])
def test_valid_games_win_by_two(a, b):
    assert game_problem(a, b, TO_11) is None


@pytest.mark.parametrize("a,b", [
    (11, 10),  # the spec's example: not finished with win by two
    (12, 9),   # should have ended at 11-9
    (13, 10),  # should have ended at 12-10
    (10, 8),   # nobody reached 11
    (11, 11),  # tie
    (15, 11),  # over by more than 2
    (-1, 11),
])
def test_impossible_games_win_by_two(a, b):
    assert game_problem(a, b, TO_11) is not None


def test_without_win_by_two_game_ends_at_target():
    assert game_problem(11, 10, NO_WIN_BY_2) is None
    assert game_problem(12, 10, NO_WIN_BY_2) is not None
    assert game_problem(10, 9, NO_WIN_BY_2) is not None


def test_point_cap():
    assert game_problem(15, 14, CAP_15) is None   # cap reached, one point is enough
    assert game_problem(15, 13, CAP_15) is None
    assert game_problem(14, 12, CAP_15) is None
    assert game_problem(16, 14, CAP_15) is not None
    assert game_problem(14, 13, CAP_15) is not None


def test_other_target_like_15():
    rules = GameRules(points_to_win=15)
    assert game_problem(15, 13, rules) is None
    assert game_problem(11, 5, rules) is not None


def test_best_of_three_shapes():
    assert match_problem([(11, 5), (11, 7)], TO_11) is None
    assert match_problem([(11, 5), (7, 11), (11, 9)], TO_11) is None
    assert "isn't finished" in match_problem([(11, 5)], TO_11)
    assert "isn't finished" in match_problem([(11, 5), (5, 11)], TO_11)
    assert "already over" in match_problem([(11, 5), (11, 7), (11, 3)], TO_11)
    assert "Game 2" in match_problem([(11, 5), (11, 10)], TO_11)
    assert match_problem([], TO_11)


def test_single_game_match():
    assert match_problem([(11, 4)], ONE_GAME) is None
    assert match_problem([(11, 4), (11, 2)], ONE_GAME)


def test_match_winner():
    assert match_winner([(11, 5), (7, 11), (9, 11)]) == "B"
    assert match_winner([(11, 0)]) == "A"


def test_forfeit_defaults_to_11_0_per_game_needed():
    assert forfeit_games("A", TO_11) == [(11, 0), (11, 0)]
    assert forfeit_games("B", ONE_GAME) == [(0, 11)]
    assert forfeit_games("A", TO_11, points=7) == [(7, 0), (7, 0)]
    assert match_problem(forfeit_games("B", TO_11), TO_11) is None


def test_score_text():
    assert score_text([(11, 7), (9, 11), (11, 5)]) == "11-7, 9-11, 11-5"


# --- Midnight lock, America/Chicago, across daylight saving ---------------

def test_lock_is_midnight_central_on_a_normal_day():
    deadline = lock_deadline(datetime.date(2027, 6, 7))
    assert deadline.astimezone(UTC) == datetime.datetime(2027, 6, 8, 5, 0, tzinfo=UTC)  # CDT is UTC-5


def test_lock_in_winter():
    deadline = lock_deadline(datetime.date(2027, 1, 11))
    assert deadline.astimezone(UTC) == datetime.datetime(2027, 1, 12, 6, 0, tzinfo=UTC)  # CST is UTC-6


def test_lock_around_spring_forward():
    """Clocks jump ahead at 2 AM on Sunday, March 14, 2027."""
    sat = lock_deadline(datetime.date(2027, 3, 13))  # midnight starting Sunday, still CST
    sun = lock_deadline(datetime.date(2027, 3, 14))  # midnight starting Monday, now CDT
    assert sat.astimezone(UTC) == datetime.datetime(2027, 3, 14, 6, 0, tzinfo=UTC)
    assert sun.astimezone(UTC) == datetime.datetime(2027, 3, 15, 5, 0, tzinfo=UTC)
    # Same-zone subtraction in Python ignores the clock change, so compare in UTC.
    assert sun.astimezone(UTC) - sat.astimezone(UTC) == datetime.timedelta(hours=23)  # the short day


def test_lock_around_fall_back():
    """Clocks fall back at 2 AM on Sunday, November 7, 2027."""
    sat = lock_deadline(datetime.date(2027, 11, 6))
    sun = lock_deadline(datetime.date(2027, 11, 7))
    assert sat.astimezone(UTC) == datetime.datetime(2027, 11, 7, 5, 0, tzinfo=UTC)
    assert sun.astimezone(UTC) == datetime.datetime(2027, 11, 8, 6, 0, tzinfo=UTC)
    assert sun.astimezone(UTC) - sat.astimezone(UTC) == datetime.timedelta(hours=25)  # the long day
