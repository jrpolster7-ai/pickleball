"""Player and spectator screens, the round viewer, and notices (section 10, Phase 6)."""

import datetime

import pytest
from django.urls import reverse

from brackets import display as bracket_display
from brackets import services as brackets
from brackets.test_services import league, play_round_robin  # noqa: F401  (fixture and helper)
from events import codes
from events.models import Notice
from scheduling import display
from scheduling import services as scheduling
from scheduling.models import Match, Round
from scoring import services as scoring
from standings import services as standings

pytestmark = pytest.mark.django_db


def first_round(event):
    return Round.objects.filter(event=event, label="").order_by("number").first()


def score_round(rnd, admin, *, leave_one=False):
    matches = list(rnd.matches.order_by("court"))
    for m in matches[:-1] if leave_one else matches:
        scoring.admin_set_score(m, [(11, 6)], admin)
    return matches


def a_player(event):
    return event.sides.filter(slot=1).first().players.first()


# --- The confirmed-round rule ---------------------------------------------

def test_a_round_is_revealed_only_when_every_match_is_final(league, admin_user):  # noqa: F811
    event = league(6, court_count=3)
    rnd = first_round(event)
    assert rnd.pk not in display.revealed_round_ids(event)
    matches = score_round(rnd, admin_user, leave_one=True)
    assert rnd.pk not in display.revealed_round_ids(event)
    scoring.admin_set_score(matches[-1], [(11, 2)], admin_user)
    assert rnd.pk in display.revealed_round_ids(event)


def test_a_disputed_match_holds_the_round(league, admin_user):  # noqa: F811
    event = league(4, court_count=2, players_enter_scores=True)
    rnd = first_round(event)
    first, second = rnd.matches.order_by("court")
    scoring.admin_set_score(first, [(11, 3)], admin_user)
    a = second.side_a.players.first()
    b = second.side_b.players.first()
    scoring.submit(second, a, [(11, 5)])
    scoring.ask_organizer(second, b)
    assert Match.objects.get(pk=second.pk).status == Match.Status.DISPUTED
    assert rnd.pk not in display.revealed_round_ids(event)
    scoring.admin_set_score(second, [(11, 5)], admin_user)
    assert rnd.pk in display.revealed_round_ids(event)


def test_spectator_round_viewer_hides_scores_until_the_round_is_final(league, admin_user):  # noqa: F811
    event = league(4, court_count=2)
    rnd = first_round(event)
    score_round(rnd, admin_user, leave_one=True)
    panel = display.round_viewer(event, display.SPECTATOR)[0]
    assert not panel.revealed
    assert all(m.score == "" for m in panel.matches)
    admin_panel = display.round_viewer(event, display.ADMIN)[0]
    assert admin_panel.matches[0].score == "11-6"

    score_round(rnd, admin_user)
    panel = display.round_viewer(event, display.SPECTATOR)[0]
    assert panel.revealed and panel.matches[0].score == "11-6"


def test_spectators_see_first_name_and_last_initial(league, admin_user):  # noqa: F811
    event = league(4)
    panel = display.round_viewer(event, display.SPECTATOR)[0]
    assert all(" T." in m.side_a and "Tester" not in m.side_a for m in panel.matches)
    player_panel = display.round_viewer(event, display.PLAYER)[0]
    assert "Tester" in player_panel.matches[0].side_a


def test_spectator_standings_count_only_revealed_rounds(league, admin_user):  # noqa: F811
    event = league(4, court_count=2)
    rnd = first_round(event)
    score_round(rnd, admin_user, leave_one=True)
    assert sum(r.wins for r in standings.table(event, spectator=True).rows) == 0
    assert sum(r.wins for r in standings.table(event).rows) == 1
    score_round(rnd, admin_user)
    spectator = standings.table(event, spectator=True)
    assert sum(r.wins for r in spectator.rows) == 2
    assert all("Tester" not in r.extra["label"] for r in spectator.rows)


def test_spectator_bracket_does_not_leak_winners_early(league, admin_user):  # noqa: F811
    event = league(4, court_count=2, third_place_match=False)
    play_round_robin(event, admin_user)
    brackets.build(event, 4, admin_user)
    semi1, semi2 = event.matches.filter(stage=Match.Stage.BRACKET, bracket_label="Semifinals").order_by("bracket_slot")
    scoring.admin_set_score(semi1, [(11, 7)], admin_user)

    sections, champion, _ = bracket_display.sections(event, display.SPECTATOR)
    final_cell = sections[0][1][-1][1][0]
    assert final_cell.label_a == "Winner of Semifinal 1", "semis time slot isn't final yet"
    semi_cell = sections[0][1][0][1][0]
    assert semi_cell.winner == "" and semi_cell.footer == "Result soon"

    admin_sections, _, _ = bracket_display.sections(event, display.ADMIN)
    assert admin_sections[0][1][-1][1][0].label_a != "Winner of Semifinal 1"

    scoring.admin_set_score(semi2, [(11, 7)], admin_user)
    sections, _, _ = bracket_display.sections(event, display.SPECTATOR)
    assert sections[0][1][-1][1][0].label_a.endswith(" T.")
    final = event.matches.get(stage=Match.Stage.BRACKET, bracket_label="Final")
    scoring.admin_set_score(final, [(11, 9)], admin_user)
    _, champion, _ = bracket_display.sections(event, display.SPECTATOR)
    assert champion and champion.endswith(" T.")


# --- Round viewer ----------------------------------------------------------

def test_round_viewer_opens_on_the_first_unfinished_round(league, admin_user):  # noqa: F811
    event = league(4, court_count=2)
    score_round(first_round(event), admin_user)
    panels = display.round_viewer(event, display.PLAYER)
    assert display.current_index(panels) == 2
    assert display.current_index(panels, "3") == 3
    assert display.current_index(panels, "99") == 2
    assert display.current_index(panels, "abc") == 2


def test_player_round_viewer_page(client, league):  # noqa: F811
    event = league(4, court_count=2)
    player = a_player(event)
    client.force_login(player.user)
    page = client.get(reverse("events:event_rounds", args=[event.pk]) + "?round=2")
    html = page.content.decode()
    assert page.status_code == 200
    assert 'role="tablist"' in html and 'aria-selected="true"' in html
    assert 'id="round-panel-2"' in html and 'id="round-panel-1"' in html
    assert 'data-prev' in html and 'data-next' in html and "round-viewer.js" in html
    assert "You can also swipe" in html  # an extra, with tabs and arrows always there
    assert "Enter score" in html  # their own match links to score entry


def test_round_viewer_works_for_multi_week(client, make_event, make_user):
    from accounts.services import player_for
    from events import registration, teams
    from events.models import Division

    event = make_event(Division.Kind.MENS, team_count=4, matches_per_team=1, total_matches=2, court_count=1,
                       weeks=3, start_date=datetime.date(2027, 3, 1), end_date=datetime.date(2027, 3, 15),
                       weekly_day=0)
    for _ in range(4):
        p1, p2 = player_for(make_user()), player_for(make_user())
        registration.admin_add(event, p1)
        registration.admin_add(event, p2)
        teams.admin_build_team(event, [p1, p2])
    scheduling.publish(event, 1)
    panels = display.round_viewer(event, display.SPECTATOR)
    assert [(p.week, p.number) for p in panels] == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)]
    page = client.get(reverse("events:watch", args=[event.spectator_code]))
    assert b"Week 3" in page.content


def test_round_viewer_query_count_is_flat(client, league, django_assert_max_num_queries):  # noqa: F811
    event = league(16, court_count=8, matches_per_team=5)
    with django_assert_max_num_queries(15):
        assert client.get(reverse("events:watch", args=[event.spectator_code])).status_code == 200


# --- Access ------------------------------------------------------------------

def test_spectator_pages_need_no_account(client, league, admin_user):  # noqa: F811
    event = league(4)
    code = event.spectator_code
    for name in ("events:watch", "events:watch_standings"):
        assert client.get(reverse(name, args=[code])).status_code == 200
    page = client.get(reverse("events:watch", args=[code]))
    assert b"Following as a spectator" in page.content
    assert b"Bracket" not in page.content.split(b"Event pages")[1].split(b"</nav>")[0]
    play_round_robin(event, admin_user)
    brackets.build(event, 4, admin_user)
    assert client.get(reverse("events:watch_bracket", args=[code])).status_code == 200


def test_turned_off_spectator_code_shows_not_found(client, league):  # noqa: F811
    event = league(4)
    codes.set_code_enabled(event, codes.SPECTATOR, False)
    assert client.get(reverse("events:watch", args=[event.spectator_code])).status_code == 404
    assert client.get(reverse("events:watch_standings", args=["NOPE99"])).status_code == 404


def test_player_pages_are_for_people_in_the_event(client, league, make_user):  # noqa: F811
    event = league(4)
    outsider = make_user()
    client.force_login(outsider)
    for name in ("events:event_rounds", "events:event_standings", "events:event_bracket"):
        assert client.get(reverse(name, args=[event.pk])).status_code == 302
    client.force_login(a_player(event).user)
    for name in ("events:event_rounds", "events:event_standings", "events:event_bracket"):
        assert client.get(reverse(name, args=[event.pk])).status_code == 200


def test_player_dashboard_shows_next_match_and_tabs(client, league):  # noqa: F811
    event = league(4)
    client.force_login(a_player(event).user)
    html = client.get(reverse("events:event_detail", args=[event.pk])).content.decode()
    assert "Your next match" in html
    assert reverse("events:event_rounds", args=[event.pk]) in html
    assert reverse("events:event_standings", args=[event.pk]) in html


# --- Notices -----------------------------------------------------------------

def test_schedule_changes_post_notices(league, admin_user):  # noqa: F811
    event = league(4, court_count=2)
    assert Notice.objects.filter(event=event, message__contains="schedule is out").exists()
    rnd = first_round(event)
    scheduling.set_round_time(rnd, datetime.time(19, 15), actor=admin_user)
    assert Notice.objects.filter(event=event, message="Round 1 now starts at 7:15 PM.").exists()
    match = rnd.matches.first()
    scheduling.edit_match(match, start_time=datetime.time(19, 30), court=5, actor=admin_user)
    assert Notice.objects.filter(event=event, message__contains="is now on court 5 at 7:30 PM").exists()
    scheduling.retime(event, actor=admin_user)
    assert Notice.objects.filter(event=event, message__contains="times were updated").exists()
    play_round_robin(event, admin_user)
    brackets.build(event, 4, admin_user)
    assert Notice.objects.filter(event=event, message__contains="bracket is set").exists()


def test_notices_are_new_until_seen(client, league):  # noqa: F811
    event = league(4)
    player = a_player(event)
    client.force_login(player.user)
    home = client.get(reverse("core:home")).content.decode()
    assert "1 new" in home
    first = client.get(reverse("events:event_detail", args=[event.pk])).content.decode()
    assert "schedule is out" in first and ">New<" in first
    second = client.get(reverse("events:event_detail", args=[event.pk])).content.decode()
    assert ">New<" not in second
    assert "1 new" not in client.get(reverse("core:home")).content.decode()


def test_spectators_do_not_see_notices(client, league):  # noqa: F811
    event = league(4)
    page = client.get(reverse("events:watch", args=[event.spectator_code]))
    assert b"schedule is out" not in page.content
