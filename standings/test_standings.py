"""Ranking and seeding rules (section 8). These must never be wrong."""

from standings.standings import Result, seeding, tally, total_points_ranking, win_loss_ranking


def res(a, b, *games):
    """Result where a and b are single team keys. Winner from the games."""
    wins_a = sum(1 for x, y in games if x > y)
    return Result((a,), (b,), tuple(games), "A" if wins_a * 2 > len(games) else "B")


def keys(rows):
    return [r.key for r in rows]


def test_tally_adds_wins_losses_and_points():
    rows = tally([res("x", "y", (11, 7), (9, 11), (11, 5)), res("x", "z", (11, 0), (11, 0))], ["x", "y", "z"])
    x, y, z = rows["x"], rows["y"], rows["z"]
    assert (x.played, x.wins, x.losses, x.points_for, x.points_against) == (2, 2, 0, 53, 23)
    assert (y.wins, y.losses, y.points_for, y.diff) == (0, 1, 23, -8)
    assert (z.played, z.points_for, z.diff) == (1, 0, -22)


def test_teams_with_no_matches_still_appear():
    rows = tally([], ["a", "b"])
    assert set(rows) == {"a", "b"}
    assert rows["a"].played == 0


def test_forfeit_scores_count_like_any_other():
    rows = tally([res("a", "b", (11, 0), (11, 0))], ["a", "b"])
    assert rows["a"].points_for == 22


def test_win_loss_ranking_uses_wins_then_points_then_difference():
    results = [
        res("a", "b", (11, 9)),   # a: 1 win, 11 pts
        res("c", "d", (15, 13)),  # c: 1 win, 15 pts
        res("e", "f", (11, 2)),   # e: 1 win, 11 pts, but bigger difference than a
    ]
    rows = tally(results, list("abcdef")).values()
    assert keys(win_loss_ranking(rows))[:3] == ["c", "e", "a"]


def test_total_points_ranking_uses_points_then_wins():
    results = [res("a", "b", (11, 13), (13, 11), (9, 11)),  # b wins; a scores 33, b 35
               res("c", "d", (11, 0), (11, 0))]               # c wins with 22
    rows = tally(results, list("abcd")).values()
    assert keys(total_points_ranking(rows)) == ["b", "a", "c", "d"]
    assert keys(win_loss_ranking(rows))[:2] == ["b", "c"]


def test_tied_rows_share_a_rank():
    rows = tally([res("a", "b", (11, 5)), res("c", "d", (11, 5))], list("abcd")).values()
    ranked = win_loss_ranking(rows)
    assert [r.rank for r in ranked] == [1, 1, 3, 3]
    assert all(r.tied for r in ranked)


def test_seeding_looks_at_losses_after_wins():
    """Uneven schedules: same wins, fewer losses seeds higher, even with fewer points."""
    results = [res("a", "x", (11, 0)), res("a", "y", (11, 0)), res("a", "z", (0, 11)),
               res("b", "x", (11, 9)), res("b", "y", (11, 9))]
    rows = tally(results, ["a", "b", "x", "y", "z"]).values()
    order = keys(seeding(rows).order)
    assert order[:2] == ["b", "a"]  # both 2 wins; b has 0 losses


def test_seeding_ties_are_flagged_not_broken_automatically():
    # A beats B, B beats C, C beats A, all 11-5: everyone 1-1 with 16 points.
    results = [res("a", "b", (11, 5)), res("b", "c", (11, 5)), res("c", "a", (11, 5))]
    s = seeding(tally(results, ["a", "b", "c"]).values())
    assert len(s.ties) == 1 and len(s.unresolved) == 1
    assert set(keys(s.unresolved[0])) == {"a", "b", "c"}
    assert s.unresolved_within(1)


def test_admin_tiebreak_decides_the_order():
    results = [res("a", "b", (11, 5)), res("b", "c", (11, 5)), res("c", "a", (11, 5))]
    rows = tally(results, ["a", "b", "c"]).values()
    s = seeding(rows, {"c": 1, "a": 2, "b": 3})
    assert keys(s.order) == ["c", "a", "b"]
    assert s.unresolved == [] and len(s.ties) == 1
    partial = seeding(rows, {"c": 1})
    assert partial.unresolved, "every tied team needs a place"


def test_ties_below_the_cut_do_not_block():
    results = [res("a", "x", (11, 0)), res("a", "y", (11, 0)), res("b", "x", (11, 0)),
               res("c", "y", (11, 3)), res("d", "x", (11, 3))]
    s = seeding(tally(results, ["a", "b", "c", "d", "x", "y"]).values())
    # c and d are tied (1-0, 11 pts, +8) as seeds 3 and 4.
    assert any(set(keys(g)) == {"c", "d"} for g in s.unresolved)
    assert s.unresolved_within(2) == []
    assert s.unresolved_within(3)  # the tie straddles the cut


def test_scramble_results_count_for_each_player():
    r = Result(("p1", "p2"), ("p3", "p4"), ((11, 6),), "A")
    rows = tally([r], ["p1", "p2", "p3", "p4"])
    assert rows["p1"].wins == rows["p2"].wins == 1
    assert rows["p3"].losses == 1 and rows["p4"].points_for == 6


def test_multi_week_results_simply_add_up():
    week = [res("a", "b", (11, 5)), res("b", "a", (11, 9))]
    rows = tally(week * 4, ["a", "b"])
    assert rows["a"].wins == 4 and rows["a"].losses == 4
    assert rows["a"].points_for == (11 + 9) * 4
