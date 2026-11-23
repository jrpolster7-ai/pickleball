"""Scheduling engine tests (section 6). These must never be wrong."""

import datetime
import time
from collections import Counter
from itertools import combinations

import pytest

from scheduling import engine
from scheduling.engine import ScheduleError


def team_counts(pairs, n):
    c = Counter()
    for a, b in pairs:
        c[a] += 1
        c[b] += 1
    return [c[t] for t in range(n)]


def all_matches(plan):
    return [(m.a, m.b) for rnd in plan.rounds for m in rnd]


def assert_valid_rounds(plan, courts):
    for rnd in plan.rounds:
        assert 1 <= len(rnd) <= courts
        teams = [t for m in rnd for t in (m.a, m.b)]
        assert len(teams) == len(set(teams)), "a team is booked twice in one round"
        assert sorted(m.court for m in rnd) == list(range(1, len(rnd) + 1))
        for m in rnd:
            assert m.a != m.b


# --- Circle method --------------------------------------------------------

@pytest.mark.parametrize("n", range(2, 17))
def test_circle_method_everyone_plays_everyone_once(n):
    rounds = engine.circle_rounds(n)
    pairs = [p for r in rounds for p in r]
    assert sorted(pairs) == sorted(combinations(range(n), 2))
    for r in rounds:
        teams = [t for p in r for t in p]
        assert len(teams) == len(set(teams))


@pytest.mark.parametrize("n", [3, 5, 7, 9, 11])
def test_odd_count_gives_one_bye_per_round_and_byes_rotate(n):
    rounds = engine.circle_rounds(n)
    assert len(rounds) == n
    byes = []
    for r in rounds:
        playing = {t for p in r for t in p}
        missing = set(range(n)) - playing
        assert len(missing) == 1
        byes.append(missing.pop())
    assert sorted(byes) == list(range(n)), "every team sits out exactly once"


@pytest.mark.parametrize("n", range(2, 30))
def test_partial_cycle_order_has_every_pair_once(n):
    order = engine.partial_cycle_order(n)
    assert sorted(order) == sorted(combinations(range(n), 2))


# --- Choosing matchups ----------------------------------------------------

def test_every_total_is_balanced_and_opponents_repeat_evenly():
    """For 2 to 20 teams and every total up to 3 full round robins."""
    for n in range(2, 21):
        cycle = n * (n - 1) // 2
        for total in range(1, 3 * cycle + 1):
            pairs = [p for g in engine.choose_pairs(n, total) for p in g]
            assert len(pairs) == total
            counts = team_counts(pairs, n)
            assert max(counts) - min(counts) <= 1, (n, total, counts)
            per_pair = Counter(pairs)
            values = [per_pair.get(p, 0) for p in combinations(range(n), 2)]
            assert max(values) - min(values) <= 1, (n, total)


def test_three_teams_sixteen_matches_each():
    """The spec's example: 3 teams at 16 per team is 24 matches."""
    plan = engine.round_robin(3, courts=4, per_team=16, total=24)
    assert plan.total_matches == 24
    assert plan.matches_per_team == {0: 16, 1: 16, 2: 16}
    assert set(Counter(all_matches(plan)).values()) == {8}
    assert len(plan.rounds) == 24  # only one match fits per round with 3 teams
    assert_valid_rounds(plan, 4)


def test_fewer_matches_than_a_full_round_robin_spreads_opponents():
    plan = engine.round_robin(10, courts=8, per_team=3, total=15)
    pairs = all_matches(plan)
    assert len(pairs) == 15
    assert len(set(pairs)) == 15, "no repeat opponents when there are plenty to go around"
    assert set(plan.matches_per_team.values()) == {3}


def test_uneven_total_differs_by_at_most_one():
    plan = engine.round_robin(5, courts=2, total=8)
    assert plan.total_matches == 8
    assert sorted(set(plan.matches_per_team.values())) == [3, 4]


def test_needs_two_teams():
    with pytest.raises(ScheduleError):
        engine.round_robin(1, courts=2, total=1)


# --- Rounds, courts, byes -------------------------------------------------

@pytest.mark.parametrize("n", range(2, 17))
def test_full_round_robin_with_enough_courts_uses_fewest_rounds(n):
    plan = engine.round_robin(n, courts=8, per_team=n - 1)  # 16 teams fill all 8 courts
    assert len(plan.rounds) == engine.full_round_robin_rounds(n)
    assert_valid_rounds(plan, 8)
    byes = set(plan.byes_per_team().values())
    assert byes == ({1} if n % 2 else {0})


def test_court_limit_pushes_matches_to_later_rounds():
    plan = engine.round_robin(8, courts=1, per_team=7)
    assert plan.total_matches == 28
    assert len(plan.rounds) == 28
    assert_valid_rounds(plan, 1)


def test_eight_courts_is_the_most_per_round():
    plan = engine.round_robin(20, courts=8, per_team=5)
    assert_valid_rounds(plan, 8)
    assert max(len(r) for r in plan.rounds) == 8
    assert plan.total_matches == 50


@pytest.mark.parametrize("n,courts", [(5, 2), (7, 3), (8, 3), (9, 2), (12, 5), (6, 2)])
def test_sit_outs_rotate_fairly_with_limited_courts(n, courts):
    plan = engine.round_robin(n, courts=courts, per_team=n - 1)
    assert_valid_rounds(plan, courts)
    assert set(plan.matches_per_team.values()) == {n - 1}
    # Through the event, nobody gets far ahead: after every round, match
    # counts stay within 2 of each other.
    played = Counter()
    for rnd in plan.rounds:
        for m in rnd:
            played[m.a] += 1
            played[m.b] += 1
        values = [played[t] for t in range(n)]
        assert max(values) - min(values) <= 2


def test_same_seed_same_schedule_and_new_seed_new_mix():
    a = engine.round_robin(10, courts=4, per_team=5, seed=7)
    b = engine.round_robin(10, courts=4, per_team=5, seed=7)
    c = engine.round_robin(10, courts=4, per_team=5, seed=8)
    assert a.rounds == b.rounds
    assert a.rounds != c.rounds
    assert set(c.matches_per_team.values()) == {5}


# --- Pools ----------------------------------------------------------------

def assert_pools_balanced(plan, per_team):
    """Odd pools round up (section 4): one team may play one extra match."""
    for members in plan.pools:
        counts = [plan.matches_per_team[t] for t in members]
        assert min(counts) == per_team
        assert max(counts) - min(counts) <= 1


def test_pool_count_never_exceeds_pool_size():
    assert engine.pool_count(12, 6) == 2
    assert engine.pool_count(13, 6) == 3
    assert engine.pool_count(6, 6) == 1
    assert engine.pool_count(10, None) == 1


def test_snake_seeding():
    assert engine.snake_pools(10, 3) == [[0, 5, 6], [1, 4, 7], [2, 3, 8, 9]]
    assert engine.snake_pools(8, 2) == [[0, 3, 4, 7], [1, 2, 5, 6]]


def test_pools_only_play_inside_their_pool():
    plan = engine.round_robin(24, courts=8, per_team=5, pool_size=6)
    assert len(plan.pools) == 4
    pool_of = {t: i for i, members in enumerate(plan.pools) for t in members}
    for rnd in plan.rounds:
        for m in rnd:
            assert pool_of[m.a] == pool_of[m.b] == m.pool
    assert set(plan.matches_per_team.values()) == {5}
    assert len(set(all_matches(plan))) == 4 * 15  # full round robin in each pool
    assert_valid_rounds(plan, 8)


def test_uneven_pools_round_up_like_section_4():
    plan = engine.round_robin(10, courts=4, per_team=3, pool_size=4)
    sizes = sorted(len(p) for p in plan.pools)
    assert sizes == [3, 3, 4]
    assert_pools_balanced(plan, 3)


def test_pool_smaller_than_two_is_refused():
    with pytest.raises(ScheduleError):
        engine.round_robin(5, courts=2, per_team=2, pool_size=1)


# --- 500 players ----------------------------------------------------------

def test_500_players_250_teams_8_courts():
    start = time.perf_counter()
    plan = engine.round_robin(250, courts=8, per_team=7, total=875)
    assert time.perf_counter() - start < 5
    assert plan.total_matches == 875
    assert set(plan.matches_per_team.values()) == {7}
    assert_valid_rounds(plan, 8)
    assert len(plan.rounds) == 110  # 875 / 8, rounded up


def test_500_players_in_pools():
    plan = engine.round_robin(250, courts=8, per_team=5, pool_size=6)
    assert len(plan.pools) == 42
    assert all(len(p) in (5, 6) for p in plan.pools)
    assert_pools_balanced(plan, 5)
    assert_valid_rounds(plan, 8)


def test_full_round_robin_of_250_teams_still_finishes():
    start = time.perf_counter()
    plan = engine.round_robin(250, courts=8, per_team=249)
    assert time.perf_counter() - start < 30
    assert plan.total_matches == 250 * 249 // 2
    assert set(plan.matches_per_team.values()) == {249}


# --- Multi-week -----------------------------------------------------------

def test_week_orders_keep_week_one_and_shuffle_the_rest():
    orders = engine.week_round_orders(6, 4, seed=3)
    assert orders[0] == list(range(6))
    assert len(orders) == 4
    for order in orders:
        assert sorted(order) == list(range(6))
    assert orders == engine.week_round_orders(6, 4, seed=3)
    assert any(o != orders[0] for o in orders[1:])


# --- Scramble -------------------------------------------------------------

def scramble_stats(plan):
    partners, opponents = Counter(), Counter()
    for rnd in plan.rounds:
        for (a1, a2), (b1, b2) in rnd:
            partners[frozenset((a1, a2))] += 1
            partners[frozenset((b1, b2))] += 1
            for x in (a1, a2):
                for y in (b1, b2):
                    opponents[frozenset((x, y))] += 1
    return partners, opponents


@pytest.mark.parametrize("players,courts", [(4, 1), (8, 2), (9, 2), (13, 3), (22, 4), (40, 8), (17, 8)])
def test_scramble_rounds_are_valid_and_sit_outs_rotate(players, courts):
    plan = engine.scramble(players, rounds=10, courts=courts)
    games = min(courts, players // 4)
    for rnd in plan.rounds:
        assert len(rnd) == games
        everyone = [p for (a, b) in rnd for p in (*a, *b)]
        assert len(everyone) == len(set(everyone)) == games * 4
    played = plan.games_per_player()
    assert max(played.values()) - min(played.values()) <= 1


def test_scramble_eight_players_never_repeat_a_partner():
    plan = engine.scramble(8, rounds=7, courts=2)
    partners, _ = scramble_stats(plan)
    assert max(partners.values()) == 1
    assert len(partners) == 28  # all 28 possible pairs partnered once


def test_scramble_sixteen_players_new_partner_every_round():
    plan = engine.scramble(16, rounds=15, courts=4)
    partners, _ = scramble_stats(plan)
    assert max(partners.values()) == 1


def test_scramble_spreads_opponents():
    plan = engine.scramble(12, rounds=6, courts=3)
    partners, opponents = scramble_stats(plan)
    assert max(partners.values()) == 1
    assert max(opponents.values()) <= 2


def test_scramble_is_repeatable():
    assert engine.scramble(14, rounds=5, courts=3, seed=4).rounds == engine.scramble(14, rounds=5, courts=3, seed=4).rounds
    assert engine.scramble(14, rounds=5, courts=3, seed=4).rounds != engine.scramble(14, rounds=5, courts=3, seed=5).rounds


def test_scramble_500_players():
    start = time.perf_counter()
    plan = engine.scramble(500, rounds=30, courts=8)
    assert time.perf_counter() - start < 5
    played = plan.games_per_player()
    assert max(played.values()) - min(played.values()) <= 1


def test_scramble_needs_four_players():
    with pytest.raises(ScheduleError):
        engine.scramble(3, rounds=2, courts=1)


# --- Times and dates ------------------------------------------------------

def test_round_times_add_match_and_break():
    first = datetime.datetime(2027, 3, 1, 18, 0)
    times = engine.round_start_times(first, 3, minutes_per_match=20, break_minutes=5)
    assert [t.strftime("%H:%M") for t in times] == ["18:00", "18:25", "18:50"]


def test_session_dates_weekly():
    monday = datetime.date(2027, 3, 1)
    assert engine.session_dates(monday, 1, None) == [monday]
    assert engine.session_dates(monday, 4, 0) == [monday + datetime.timedelta(weeks=w) for w in range(4)]
    # Start date on a Saturday, league on Mondays: first session is the next Monday.
    saturday = datetime.date(2027, 2, 27)
    assert engine.session_dates(saturday, 2, 0) == [monday, monday + datetime.timedelta(weeks=1)]
