"""Single elimination structure (section 9). These must never be wrong."""

import pytest

from brackets.brackets import (
    BracketError,
    feed_label,
    main_size,
    opening_pairs,
    seed_positions,
    single_elimination,
)


def matchups(bracket, round_number):
    return [(m.a, m.b) for m in bracket.matches if m.round == round_number and not m.third_place]


def seeds_in(bracket):
    return sorted(f.value for m in bracket.matches for f in (m.a, m.b) if f.kind == "seed")


def test_seed_positions():
    assert seed_positions(2) == [1, 2]
    assert seed_positions(4) == [1, 4, 2, 3]
    assert seed_positions(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert sorted(seed_positions(16)) == list(range(1, 17))


def test_one_and_two_can_only_meet_in_the_final():
    order = seed_positions(16)
    assert order.index(1) < 8 <= order.index(2)


def test_main_size():
    assert [main_size(n) for n in (2, 3, 4, 5, 7, 8, 9, 15, 16, 17)] == [2, 2, 4, 4, 4, 8, 8, 8, 16, 16]


def test_opening_pairs_start_at_the_cutoff():
    """DECIDED with Joe: the last team in plays the first team out, then work outward."""
    assert opening_pairs(9) == [(8, 9)]
    assert opening_pairs(10) == [(8, 9), (7, 10)]
    assert opening_pairs(12) == [(8, 9), (7, 10), (6, 11), (5, 12)]
    assert opening_pairs(8) == []
    assert opening_pairs(3) == [(2, 3)]


@pytest.mark.parametrize("n", range(2, 33))
@pytest.mark.parametrize("play_in", [True, False])
def test_every_size_is_a_valid_bracket(n, play_in):
    b = single_elimination(n, play_in=play_in, third_place=False)
    assert seeds_in(b) == list(range(1, n + 1)), "every seed appears exactly once"
    assert len(b.matches) == n - 1, "one loss knocks you out, so n - 1 matches"
    finals = [m for m in b.matches if m.winner_to is None]
    assert len(finals) == 1 and finals[0].label == "Final"
    for m in b.matches:
        if m.winner_to:
            target = b.by_key()[m.winner_to[0]]
            side = target.a if m.winner_to[1] == "A" else target.b
            assert side.kind == "winner" and side.value == m.key


@pytest.mark.parametrize("n", [2, 4, 8, 16])
def test_power_of_two_has_no_opening_round(n):
    b = single_elimination(n, play_in=True, third_place=False)
    assert not [m for m in b.matches if m.round == 0]
    assert len(matchups(b, 1)) == n // 2


def test_ten_teams_with_play_ins():
    b = single_elimination(10, play_in=True, third_place=True)
    opening = [m for m in b.matches if m.round == 0]
    assert [(m.a.value, m.b.value) for m in opening] == [(8, 9), (7, 10)]
    assert {m.label for m in opening} == {"Play-in"}
    names = [name for name, _ in b.rounds()]
    assert names == ["Play-in", "Quarterfinals", "Semifinals", "Final", "Third place"]
    # Seed 1 plays the winner of 8 v 9; seed 2 plays the winner of 7 v 10.
    quarters = {m.position: m for m in b.matches if m.round == 1}
    assert quarters[1].a.value == 1 and feed_label(quarters[1].b, b) == "Winner of Play-in 1"
    assert quarters[3].a.value == 2 and feed_label(quarters[3].b, b) == "Winner of Play-in 2"


def test_byes_give_the_same_matchups_with_different_names():
    play_in = single_elimination(12, play_in=True, third_place=False)
    byes = single_elimination(12, play_in=False, third_place=False)
    shape = lambda b: [(m.round, m.position, m.a, m.b) for m in b.matches]  # noqa: E731
    assert shape(play_in) == shape(byes)
    assert [n for n, _ in byes.rounds()] == ["Round 1", "Quarterfinals", "Semifinals", "Final"]
    # Seeds 1 to 4 skip round 1: that's the bye.
    round_one = {f.value for m in byes.matches if m.round == 0 for f in (m.a, m.b)}
    assert round_one == set(range(5, 13))


def test_third_place_match_takes_the_semifinal_losers():
    b = single_elimination(8, play_in=True, third_place=True)
    third = [m for m in b.matches if m.third_place]
    assert len(third) == 1
    semis = [m for m in b.matches if m.label == "Semifinals"]
    assert {third[0].a.value, third[0].b.value} == {s.key for s in semis}
    assert all(s.loser_to == (third[0].key, side) for s, side in zip(semis, "AB"))
    assert third[0].a.kind == "loser"


def test_no_third_place_without_semifinals():
    assert not [m for m in single_elimination(3, play_in=True, third_place=True).matches if m.third_place]
    assert not [m for m in single_elimination(8, play_in=True, third_place=False).matches if m.third_place]


def test_round_names_for_bigger_brackets():
    b = single_elimination(20, play_in=False, third_place=False)
    assert [n for n, _ in b.rounds()] == ["Round 1", "Round 2", "Quarterfinals", "Semifinals", "Final"]
    b = single_elimination(20, play_in=True, third_place=False)
    assert [n for n, _ in b.rounds()] == ["Play-in", "Round 1", "Quarterfinals", "Semifinals", "Final"]


def test_needs_two_teams():
    with pytest.raises(BracketError):
        single_elimination(1, play_in=True, third_place=False)
