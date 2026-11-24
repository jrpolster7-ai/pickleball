"""Standings from real results, building the bracket, and playing it out."""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.services import player_for
from core.models import AuditLog
from events import registration, teams
from events.models import BracketSizing, BracketType, Division, Event
from scheduling import services as scheduling
from scheduling.models import Match
from scoring import services as scoring
from scoring.services import ScoreError
from standings import services as standings

from brackets import services
from brackets.brackets import BracketError

pytestmark = pytest.mark.django_db


@pytest.fixture
def league(make_event, make_user, admin_user):
    """A Men's event with n full teams, one game per match, full round robin, play started."""
    def _make(n=6, **kw):
        kw.setdefault("games_per_match", 1)
        kw.setdefault("court_count", 4)
        kw.setdefault("matches_per_team", n - 1)
        kw.setdefault("total_matches", n * kw["matches_per_team"] // 2)
        event = make_event(Division.Kind.MENS, team_count=n, **kw)
        for _ in range(n):
            p1, p2 = player_for(make_user()), player_for(make_user())
            registration.admin_add(event, p1, override=True)
            registration.admin_add(event, p2, override=True)
            teams.admin_build_team(event, [p1, p2], override=True)
        scheduling.publish(event, 1)
        scheduling.start_play(event)
        event.refresh_from_db()
        return event
    return _make


def play_round_robin(event, admin, loser_points=lambda w, l: 5):
    """Lower team slot always wins 11 to something, so slot 1 is best."""
    for m in Match.objects.filter(event=event, stage=Match.Stage.ROUND_ROBIN).select_related("side_a", "side_b"):
        a_wins = m.side_a.slot < m.side_b.slot
        winner, loser = (m.side_a, m.side_b) if a_wins else (m.side_b, m.side_a)
        lp = loser_points(winner.slot, loser.slot)
        scoring.admin_set_score(m, [(11, lp)] if a_wins else [(lp, 11)], admin)


def slot_of(side_id):
    from events.models import Side
    return Side.objects.get(pk=side_id).slot


def win(match, letter, admin):
    match = Match.objects.get(pk=match.pk)
    scoring.admin_set_score(match, [(11, 4)] if letter == "A" else [(4, 11)], admin)


def bracket_matches(event):
    return list(event.matches.filter(stage=Match.Stage.BRACKET).order_by("bracket_round", "third_place", "bracket_slot"))


# --- Standings from saved results ----------------------------------------

def test_standings_table_from_results(league, admin_user):
    event = league(4)
    play_round_robin(event, admin_user, loser_points=lambda w, l: l)  # loser scores its slot number
    table = standings.table(event)
    assert table.remaining == 0
    ranked = table.win_loss
    assert [slot_of(r.key) for r in ranked] == [1, 2, 3, 4]
    assert [(r.wins, r.losses) for r in ranked] == [(3, 0), (2, 1), (1, 2), (0, 3)]
    assert ranked[3].points_for == 4 * 3


def test_unfinished_matches_are_counted_as_remaining(league, admin_user):
    event = league(4)
    assert standings.table(event).remaining == 6
    assert "not final yet" in services.build_problem(event, 4)


def test_pools_get_their_own_tables(league, admin_user):
    event = league(8, pool_size=4, matches_per_team=3)
    play_round_robin(event, admin_user)
    table = standings.table(event)
    assert [name for name, _ in table.pools] == ["Pool A", "Pool B"]
    assert all(len(rows) == 4 for _, rows in table.pools)
    # Seeding crosses pools: two 3-0 teams, one from each pool, take seeds 1 and 2.
    top = table.seeding().order[:2]
    assert {r.extra["pool"] for r in top} == {"Pool A", "Pool B"}


def test_scramble_standings_are_per_player(make_event, make_user, admin_user):
    event = make_event(Division.Kind.SCRAMBLE, scramble_rounds=2, court_count=1, games_per_match=1,
                       team_count=None, matches_per_team=None, total_matches=None)
    for _ in range(4):
        registration.admin_add(event, player_for(make_user()))
    scheduling.publish(event, 1)
    scheduling.start_play(event)
    event.refresh_from_db()
    for m in Match.objects.filter(event=event):
        scoring.admin_set_score(m, [(11, 6)], admin_user)
    table = standings.table(event)
    assert len(table.rows) == 4
    assert sum(r.wins for r in table.rows) == 4 and sum(r.losses for r in table.rows) == 4
    assert "Scramble" in services.build_problem(event, 2)


# --- Building ---------------------------------------------------------------

def test_build_six_team_bracket_with_play_ins(league, admin_user):
    event = league(6, bracket_sizing=BracketSizing.PLAY_IN, third_place_match=True)
    play_round_robin(event, admin_user)
    services.build(event, 6, admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.BRACKET and event.advancing_count == 6

    matches = bracket_matches(event)
    labels = [m.bracket_label for m in matches]
    assert labels == ["Play-in", "Play-in", "Semifinals", "Semifinals", "Final", "Third place"]
    play_ins = matches[:2]
    assert [(slot_of(m.side_a_id), slot_of(m.side_b_id)) for m in play_ins] == [(4, 5), (3, 6)]
    semis = matches[2:4]
    assert slot_of(semis[0].side_a_id) == 1 and semis[0].side_b_id is None
    assert semis[0].feed_b == "Winner of Play-in 1"
    assert matches[5].feed_a == "Loser of Semifinal 1"
    assert AuditLog.objects.filter(action="bracket built", event=event).exists()


def test_bracket_is_scheduled_after_the_round_robin(league, admin_user):
    event = league(4, court_count=2, minutes_per_match=20, break_minutes=5)
    play_round_robin(event, admin_user)
    last_rr = event.rounds.order_by("-number").first()
    services.build(event, 4, admin_user)
    bracket = bracket_matches(event)
    semis_round = bracket[0].round
    assert semis_round.start_time == last_rr.start_time + datetime.timedelta(minutes=25)
    assert semis_round.label == "Semifinals"
    assert bracket[2].round.label == "Final and third place"
    assert sorted(m.court for m in bracket[2].round.matches.all()) == [1, 2]


def test_build_on_another_day(league, admin_user):
    event = league(4)
    play_round_robin(event, admin_user)
    day = event.start_date + datetime.timedelta(days=7)
    services.build(event, 4, admin_user, date=day, start=datetime.time(9, 0))
    first = bracket_matches(event)[0]
    assert timezone.localtime(first.start_time).strftime("%Y-%m-%d %H:%M") == f"{day} 09:00"
    assert first.round.session.week == 2


def test_advancing_count_must_fit(league, admin_user):
    event = league(4)
    play_round_robin(event, admin_user)
    assert services.build_problem(event, 1)
    assert services.build_problem(event, 5)
    assert services.build_problem(event, 2) is None


# --- Ties -------------------------------------------------------------------

def test_ties_block_the_bracket_until_the_admin_decides(league, admin_user):
    event = league(3)
    # A cycle: 1 beats 2, 2 beats 3, 3 beats 1, all 11-5. Everyone 1-1, 16 points.
    for m in Match.objects.filter(event=event).select_related("side_a", "side_b"):
        pair = {m.side_a.slot, m.side_b.slot}
        winner_slot = {frozenset({1, 2}): 1, frozenset({2, 3}): 2, frozenset({1, 3}): 3}[frozenset(pair)]
        scoring.admin_set_score(m, [(11, 5)] if m.side_a.slot == winner_slot else [(5, 11)], admin_user)
    assert "tied" in services.build_problem(event, 2)
    sides = {s.slot: s.pk for s in event.sides.all()}
    services.set_tiebreak(event, [sides[3], sides[1], sides[2]], admin_user)
    assert services.build_problem(event, 2) is None
    order = [slot_of(r.key) for r in standings.table(event).seeding().order]
    assert order == [3, 1, 2]
    assert AuditLog.objects.filter(action="seeding tie decided").exists()


# --- Playing it out ---------------------------------------------------------

def test_winners_move_on_and_the_event_completes(league, admin_user):
    event = league(4, third_place_match=True)
    play_round_robin(event, admin_user)
    services.build(event, 4, admin_user)
    semi1, semi2, final, third = bracket_matches(event)
    assert (slot_of(semi1.side_a_id), slot_of(semi1.side_b_id)) == (1, 4)

    win(semi1, "B", admin_user)  # 4 upsets 1
    win(semi2, "A", admin_user)
    final.refresh_from_db()
    third.refresh_from_db()
    assert slot_of(final.side_a_id) == 4 and final.side_b_id == semi2.side_a_id
    assert third.side_a_id == semi1.side_a_id and third.side_b_id == semi2.side_b_id

    win(final, "A", admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.BRACKET, "third place still to play"
    win(third, "B", admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.COMPLETE
    assert services.champion(event).slot == 4

    scoring.admin_clear_score(Match.objects.get(pk=final.pk), admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.BRACKET


def test_play_in_winner_takes_the_spot(league, admin_user):
    event = league(5, bracket_sizing=BracketSizing.PLAY_IN, third_place_match=False)
    play_round_robin(event, admin_user)
    services.build(event, 5, admin_user)
    play_in = bracket_matches(event)[0]
    assert (slot_of(play_in.side_a_id), slot_of(play_in.side_b_id)) == (4, 5)
    win(play_in, "B", admin_user)
    target = Match.objects.get(pk=play_in.winner_to_id)
    assert slot_of(target.side_b_id) == 5 and slot_of(target.side_a_id) == 1


def test_players_enter_bracket_scores_the_same_way(league, admin_user):
    event = league(4, players_enter_scores=True)
    play_round_robin(event, admin_user)
    services.build(event, 4, admin_user)
    semi1 = bracket_matches(event)[0]
    a = semi1.side_a.players.first()
    b = semi1.side_b.players.first()
    sub = scoring.submit(semi1, a, [(11, 8)])
    scoring.confirm(sub, b)
    final = Match.objects.get(pk=semi1.winner_to_id)
    assert final.side_a_id == semi1.side_a_id


def test_waiting_matches_cannot_be_scored(league, admin_user):
    event = league(4)
    play_round_robin(event, admin_user)
    services.build(event, 4, admin_user)
    final = bracket_matches(event)[2]
    with pytest.raises(ScoreError, match="waiting for its teams"):
        scoring.admin_set_score(final, [(11, 3)], admin_user)


def test_changing_a_result_after_the_next_match_is_played_is_blocked(league, admin_user):
    event = league(4, third_place_match=False)
    play_round_robin(event, admin_user)
    services.build(event, 4, admin_user)
    semi1, semi2, final = bracket_matches(event)
    win(semi1, "A", admin_user)
    win(semi2, "A", admin_user)
    win(final, "A", admin_user)
    with pytest.raises(ScoreError, match="already has a score"):
        win(semi1, "B", admin_user)
    assert Match.objects.get(pk=semi1.pk).winner == "A", "nothing changed"
    with pytest.raises(ScoreError):
        scoring.admin_clear_score(Match.objects.get(pk=semi1.pk), admin_user)

    # Same winner, new score is fine.
    scoring.admin_set_score(Match.objects.get(pk=semi1.pk), [(11, 9)], admin_user)
    # Clear the final first, then the semi can change.
    scoring.admin_clear_score(Match.objects.get(pk=final.pk), admin_user)
    win(semi1, "B", admin_user)
    assert Match.objects.get(pk=final.pk).side_a_id == semi1.side_b_id


def test_delete_bracket_only_before_scores(league, admin_user):
    event = league(4)
    play_round_robin(event, admin_user)
    services.build(event, 4, admin_user)
    services.delete(event, admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.ROUND_ROBIN and event.advancing_count is None
    assert not event.matches.filter(stage=Match.Stage.BRACKET).exists()
    assert not event.rounds.exclude(label="").exists()

    services.build(event, 2, admin_user)
    win(bracket_matches(event)[0], "A", admin_user)
    with pytest.raises(BracketError, match="already have scores"):
        services.delete(event, admin_user)


def test_round_robin_counts_ignore_bracket_matches(league, admin_user):
    event = league(4)
    play_round_robin(event, admin_user)
    services.build(event, 4, admin_user)
    assert {c.per_week for c in scheduling.saved_counts(event)} == {3}


# --- Pages ------------------------------------------------------------------

def test_standings_pages(client, admin_user, league, django_assert_max_num_queries):
    event = league(8)
    play_round_robin(event, admin_user)
    client.force_login(admin_user)
    url = reverse("standings:standings", args=[event.pk])
    with django_assert_max_num_queries(12):
        page = client.get(url)
    assert page.status_code == 200 and b"Wins and losses" in page.content
    assert client.get(url + "?view=points").status_code == 200


def test_bracket_pages_preview_build_and_show(client, admin_user, league):
    event = league(6, bracket_sizing=BracketSizing.PLAY_IN)
    play_round_robin(event, admin_user)
    client.force_login(admin_user)
    url = reverse("brackets:bracket", args=[event.pk])
    page = client.get(url + "?count=6")
    assert page.status_code == 200
    assert b"Preview: 6 teams" in page.content and b"Play-in" in page.content
    assert client.post(reverse("brackets:build", args=[event.pk]), {"count": "6"}).status_code == 302
    shown = client.get(url)
    assert b"Winner of Play-in 1" in shown.content
    assert b"Remove bracket" in shown.content


def test_tiebreak_view(client, admin_user, league):
    event = league(3)
    sides = list(event.sides.order_by("slot"))
    client.force_login(admin_user)
    r = client.post(reverse("brackets:tiebreak", args=[event.pk]),
                    {f"order_{sides[0].pk}": "2", f"order_{sides[1].pk}": "1", "count": "2"})
    assert r.status_code == 302 and r.url.endswith("?count=2")
    sides[1].refresh_from_db()
    assert sides[1].tiebreak == 1


def test_players_cannot_open_admin_bracket_pages(client, make_user, league):
    event = league(4)
    client.force_login(make_user())
    assert client.get(reverse("brackets:bracket", args=[event.pk])).status_code == 403
    assert client.get(reverse("standings:standings", args=[event.pk])).status_code == 403
