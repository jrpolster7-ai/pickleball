"""Double elimination structure (section 9, Phase 5). These must never be wrong."""

import random
from collections import Counter

import pytest

from brackets.brackets import FINAL, LOSERS, WINNERS, BracketError, double_elimination, feed_label


def simulate(bracket, rng):
    """Play every match with random winners. Returns (losses per seed, champion, played pairs per match)."""
    result, losses, pairs = {}, Counter(), {}

    def team(feed):
        if feed.kind == "seed":
            return feed.value
        winner, loser = result[feed.value]
        return winner if feed.kind == "winner" else loser

    for m in bracket.matches:
        a, b = team(m.a), team(m.b)
        assert a != b, "a team can't play itself"
        winner, loser = (a, b) if rng.random() < 0.5 else (b, a)
        result[m.key] = (winner, loser)
        pairs[m.key] = {a, b}
        losses[loser] += 1
    grand_final = bracket.matches[-1]
    winner, loser = result[grand_final.key]
    if winner == team(grand_final.b):  # losers bracket champion won: reset
        winner, loser = (winner, loser) if rng.random() < 0.5 else (loser, winner)
        losses[loser] += 1
    return losses, winner, pairs


@pytest.mark.parametrize("n", range(2, 34))
def test_everyone_is_out_after_exactly_two_losses(n):
    for trial in range(25):
        b = double_elimination(n, play_in=trial % 2 == 0)
        losses, champion, _ = simulate(b, random.Random(trial))
        for seed in range(1, n + 1):
            if seed == champion:
                assert losses[seed] <= 1
            else:
                assert losses[seed] == 2, (n, seed, dict(losses))


@pytest.mark.parametrize("n", range(2, 34))
def test_match_count_and_every_seed_once(n):
    b = double_elimination(n, play_in=False)
    assert len(b.matches) == 2 * n - 2, "the reset is extra, only when needed"
    seeds = sorted(f.value for m in b.matches for f in (m.a, m.b) if f.kind == "seed")
    assert seeds == list(range(1, n + 1))
    assert b.matches[-1].side == FINAL and b.matches[-1].label == "Grand final"


@pytest.mark.parametrize("n", [4, 5, 6, 8, 10, 12, 16, 20, 32])
def test_no_team_is_booked_twice_in_one_wave(n):
    """Matches in the same wave can share a time slot, so a team can't be in two."""
    b = double_elimination(n, play_in=True)
    for trial in range(10):
        _, _, pairs = simulate(b, random.Random(trial))
        by_wave = {}
        for m in b.matches:
            by_wave.setdefault(m.wave, []).extend(pairs[m.key])
        for wave, teams in by_wave.items():
            assert len(teams) == len(set(teams)), (n, wave)


def test_waves_follow_the_rounds():
    b = double_elimination(8, play_in=False)
    by_key = b.by_key()
    for m in b.matches:
        for f in (m.a, m.b):
            if f.kind in ("winner", "loser"):
                assert by_key[f.value].wave < m.wave


@pytest.mark.parametrize("n", [8, 16, 32])
def test_first_drop_into_the_losers_bracket_avoids_rematches(n):
    """Losers from winners round 2 cross over, so they don't meet someone they just beat."""
    b = double_elimination(n, play_in=False)
    second_losers_round = [m for m in b.matches if m.side == LOSERS and m.round == 2]
    for trial in range(20):
        _, _, pairs = simulate(b, random.Random(trial))
        first_round = [pairs[m.key] for m in b.matches if m.side == WINNERS and m.round == 1]
        for m in second_losers_round:
            assert pairs[m.key] not in first_round


def test_eight_team_round_names():
    b = double_elimination(8, play_in=False)
    sections = b.sections()
    assert [s for s, _ in sections] == ["Winners bracket", "Losers bracket", "Grand final"]
    assert [name for name, _ in sections[0][1]] == ["Winners round 1", "Winners round 2", "Winners final"]
    assert [name for name, _ in sections[1][1]] == ["Losers round 1", "Losers round 2", "Losers round 3", "Losers final"]
    losers_final = sections[1][1][-1][1][0]
    assert feed_label(losers_final.b, b) == "Loser of the winners final"


def test_ten_teams_opening_losers_drop_to_the_losers_bracket():
    """DECIDED with Joe: losing an opening match drops you to the losers bracket."""
    b = double_elimination(10, play_in=True)
    opening = [m for m in b.matches if m.side == WINNERS and m.round == 1]
    assert [(m.a.value, m.b.value) for m in opening] == [(8, 9), (7, 10)]
    assert {m.label for m in opening} == {"Play-in"}
    for m in opening:
        assert m.loser_to is not None
        assert b.by_key()[m.loser_to[0]].side == LOSERS
    assert [n for n, _ in b.sections()[0][1]] == ["Play-in", "Winners round 1", "Winners round 2", "Winners final"]


def test_byes_name_the_opening_round_winners_round_1():
    b = double_elimination(10, play_in=False)
    assert [n for n, _ in b.sections()[0][1]][:2] == ["Winners round 1", "Winners round 2"]


def test_two_teams_play_a_final_then_a_grand_final():
    b = double_elimination(2, play_in=False)
    assert [m.label for m in b.matches] == ["Winners final", "Grand final"]
    grand_final = b.matches[1]
    assert grand_final.b.kind == "loser"


def test_three_teams():
    b = double_elimination(3, play_in=True)
    assert len(b.matches) == 4
    assert [m.label for m in b.matches] == ["Play-in", "Winners final", "Losers final", "Grand final"]


def test_needs_two_teams():
    with pytest.raises(BracketError):
        double_elimination(1, play_in=True)
