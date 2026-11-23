"""Publishing, clearing, and editing a saved schedule."""

import datetime
from collections import Counter

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Gender
from accounts.services import player_for
from core.models import AuditLog
from events import registration, teams
from events.models import Division, Event, Side
from scheduling import services
from scheduling.engine import ScheduleError
from scheduling.models import Match, Round, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def mixed_team(make_user):
    """Make a full registered Mixed team in an event."""
    def _make(event):
        man = player_for(make_user(gender=Gender.MALE))
        woman = player_for(make_user(gender=Gender.FEMALE))
        registration.admin_add(event, man)
        registration.admin_add(event, woman)
        return teams.admin_build_team(event, [man, woman])
    return _make


def local(dt):
    return timezone.localtime(dt)


def matchups(event, week):
    return Counter(
        tuple(sorted(pair))
        for pair in Match.objects.filter(event=event, round__session__week=week).values_list("side_a_id", "side_b_id")
    )


def test_preview_saves_nothing(make_event):
    event = make_event(team_count=4, matches_per_team=3, total_matches=6)
    preview = services.build_preview(event)
    assert preview.total_matches == 6
    assert len(preview.rounds) == 3
    assert {c.per_week for c in preview.counts} == {3}
    assert not Round.objects.exists()


def test_publish_matches_the_preview_and_fills_open_spots(make_event, mixed_team, admin_user):
    event = make_event(team_count=6, matches_per_team=5, total_matches=15, court_count=3)
    first = mixed_team(event)
    preview = services.build_preview(event, seed=4)
    services.publish(event, 4, actor=admin_user)

    assert event.sides.count() == 6
    assert list(event.sides.order_by("slot").values_list("slot", flat=True)) == [1, 2, 3, 4, 5, 6]
    first.refresh_from_db()
    assert first.slot == 1
    assert event.sides.filter(players=None).count() == 5

    rounds = list(Round.objects.filter(event=event).order_by("number"))
    assert len(rounds) == len(preview.rounds)
    for saved, planned in zip(rounds, preview.rounds):
        saved_courts = sorted(saved.matches.values_list("court", flat=True))
        assert saved_courts == [m.court for m in planned.matches]
        assert saved.start_time == planned.start_time
    assert Match.objects.filter(event=event).count() == 15
    event.refresh_from_db()
    assert event.schedule_seed == 4
    assert AuditLog.objects.filter(action="schedule published", event=event).exists()


def test_round_times_follow_settings(make_event):
    event = make_event(team_count=4, matches_per_team=3, total_matches=6, court_count=2,
                       start_time=datetime.time(18, 0), minutes_per_match=20, break_minutes=5)
    services.publish(event, 1)
    times = [local(r.start_time).strftime("%H:%M") for r in Round.objects.filter(event=event).order_by("number")]
    assert times == ["18:00", "18:25", "18:50"]
    for match in Match.objects.filter(event=event):
        assert match.start_time == match.round.start_time


def test_no_side_twice_in_a_round(make_event):
    event = make_event(team_count=9, matches_per_team=8, total_matches=36, court_count=3)
    services.publish(event, 2)
    for rnd in Round.objects.filter(event=event):
        sides = [s for m in rnd.matches.all() for s in (m.side_a_id, m.side_b_id)]
        assert len(sides) == len(set(sides))
        assert rnd.matches.count() <= 3


def test_multi_week_clones_week_one(make_event):
    event = make_event(team_count=6, matches_per_team=2, total_matches=6, court_count=2, weeks=4,
                       start_date=datetime.date(2027, 3, 1), end_date=datetime.date(2027, 3, 22), weekly_day=0)
    services.publish(event, 3)
    sessions = list(Session.objects.filter(event=event))
    assert [s.date for s in sessions] == [datetime.date(2027, 3, 1) + datetime.timedelta(weeks=w) for w in range(4)]
    week1 = matchups(event, 1)
    assert sum(week1.values()) == 6
    for week in (2, 3, 4):
        assert matchups(event, week) == week1
    assert Match.objects.filter(event=event).count() == 24
    counts = services.saved_counts(event)
    assert {c.per_week for c in counts} == {2}


def test_scramble_makes_fresh_sides_per_game(make_event, make_user):
    event = make_event(Division.Kind.SCRAMBLE, scramble_rounds=4, court_count=2, team_count=None,
                       matches_per_team=None, total_matches=None)
    for _ in range(10):
        registration.admin_add(event, player_for(make_user()))
    services.publish(event, 1)
    matches = Match.objects.filter(event=event)
    assert matches.count() == 8  # 2 games a round, 4 rounds
    for match in matches:
        assert match.side_a.players.count() == 2
        assert match.side_b.players.count() == 2
        assert match.side_a.slot is None
    counts = services.saved_counts(event)
    assert len(counts) == 10
    assert sum(c.per_week for c in counts) == 8 * 4
    assert max(c.per_week for c in counts) - min(c.per_week for c in counts) <= 1


def test_scramble_needs_rounds_and_players(make_event, make_user):
    event = make_event(Division.Kind.SCRAMBLE, scramble_rounds=None, team_count=None)
    with pytest.raises(ScheduleError, match="rounds"):
        services.build_preview(event)
    event.scramble_rounds = 3
    event.save()
    with pytest.raises(ScheduleError, match="at least 4"):
        services.build_preview(event)


def test_pools_are_saved_on_sides_and_registrations(make_event, mixed_team):
    event = make_event(team_count=8, matches_per_team=3, total_matches=12, pool_size=4, court_count=4)
    team = mixed_team(event)
    services.publish(event, 1)
    assert set(event.sides.values_list("pool", flat=True)) == {1, 2}
    team.refresh_from_db()
    assert set(event.registrations.values_list("pool", flat=True)) == {team.pool}
    for match in Match.objects.filter(event=event).select_related("side_a", "side_b"):
        assert match.side_a.pool == match.side_b.pool == match.pool


def test_cannot_publish_twice(make_event):
    event = make_event()
    services.publish(event, 1)
    with pytest.raises(ScheduleError, match="already has a schedule"):
        services.publish(event, 2)


def test_clear_then_publish_again(make_event, mixed_team):
    event = make_event(team_count=4)
    team = mixed_team(event)
    services.publish(event, 1)
    services.clear(event)
    assert not Match.objects.filter(event=event).exists()
    assert not Round.objects.filter(event=event).exists()
    assert list(event.sides.all()) == [team]  # the empty open spots are gone
    team.refresh_from_db()
    assert team.slot is None
    services.publish(event, 2)
    assert Match.objects.filter(event=event).count() == 6


def test_schedule_is_locked_once_play_starts(make_event, admin_user):
    event = make_event()
    with pytest.raises(ScheduleError):
        services.start_play(event)
    services.publish(event, 1)
    services.start_play(event, actor=admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.ROUND_ROBIN
    with pytest.raises(ScheduleError):
        services.clear(event)
    with pytest.raises(ScheduleError):
        services.start_play(event)


# --- Teams after publishing ----------------------------------------------

def test_new_team_takes_an_open_spot(make_event, make_user):
    event = make_event(team_count=4)
    services.publish(event, 1)
    player = player_for(make_user(gender=Gender.MALE))
    registration.join(event, player)
    side = teams.create_team(event, player)
    assert side.slot == 1
    assert event.sides.count() == 4
    assert side.team_code


def test_no_new_teams_once_spots_are_filled(make_event, mixed_team, make_user):
    event = make_event(team_count=2, matches_per_team=1, total_matches=1)
    mixed_team(event)
    mixed_team(event)
    services.publish(event, 1)
    man = player_for(make_user(gender=Gender.MALE))
    woman = player_for(make_user(gender=Gender.FEMALE))
    registration.admin_add(event, man, override=True)
    registration.admin_add(event, woman, override=True)
    with pytest.raises(teams.TeamError, match="every team spot is filled"):
        teams.admin_build_team(event, [man, woman], override=True)


def test_leaving_or_splitting_a_scheduled_team_keeps_its_spot(make_event, mixed_team):
    event = make_event(team_count=4)
    team = mixed_team(event)
    services.publish(event, 1)
    old_code = team.team_code
    p1, p2 = list(team.players.all())
    teams.leave_team(team, p1)
    registration.remove(event, p2)
    team.refresh_from_db()
    assert team.players.count() == 0
    assert team.slot == 1
    assert team.team_code != old_code
    assert Match.objects.filter(side_a=team).exists() or Match.objects.filter(side_b=team).exists()

    other = mixed_team(event)  # fills the first open spot, which is this one
    assert other.pk == team.pk
    teams.delete_team(other)
    assert Side.objects.filter(pk=team.pk, slot=1).exists()


# --- Editing ---------------------------------------------------------------

def test_moving_a_round_moves_its_matches_and_is_logged(make_event, admin_user):
    event = make_event()
    services.publish(event, 1)
    rnd = Round.objects.filter(event=event).order_by("number").first()
    services.set_round_time(rnd, datetime.time(19, 15), actor=admin_user)
    rnd.refresh_from_db()
    assert local(rnd.start_time).strftime("%H:%M") == "19:15"
    assert all(local(m.start_time).strftime("%H:%M") == "19:15" for m in rnd.matches.all())
    entry = AuditLog.objects.get(action="round time changed")
    assert entry.actor == admin_user
    assert "06:00 PM" in entry.old_value and "07:15 PM" in entry.new_value


def test_edit_match_court_and_time(make_event, admin_user):
    event = make_event(team_count=4, court_count=2)
    services.publish(event, 1)
    rnd = Round.objects.filter(event=event).order_by("number").first()
    first, second = rnd.matches.order_by("court")
    with pytest.raises(ScheduleError, match="already used"):
        services.edit_match(first, start_time=datetime.time(18, 0), court=2)
    services.edit_match(first, start_time=datetime.time(18, 10), court=5, actor=admin_user)
    first.refresh_from_db()
    assert first.court == 5
    assert local(first.start_time).strftime("%H:%M") == "18:10"
    assert AuditLog.objects.filter(action="match edited", object_id=first.pk).exists()
    with pytest.raises(ScheduleError):
        services.edit_match(first, start_time=datetime.time(18, 0), court=9)


def test_retime_uses_new_match_length(make_event):
    event = make_event(team_count=4, court_count=2, minutes_per_match=20, break_minutes=5)
    services.publish(event, 1)
    event.minutes_per_match = 30
    event.break_minutes = 0
    event.save()
    services.retime(event)
    times = [local(r.start_time).strftime("%H:%M") for r in Round.objects.filter(event=event).order_by("number")]
    assert times == ["18:00", "18:30", "19:00"]


def test_daylight_saving_day_keeps_wall_clock_times(make_event):
    """March 14, 2027 is the spring-forward Sunday in Chicago."""
    day = datetime.date(2027, 3, 14)
    event = make_event(team_count=4, court_count=2, start_date=day, end_date=day)
    services.publish(event, 1)
    first = Round.objects.filter(event=event).order_by("number").first()
    assert local(first.start_time).strftime("%Y-%m-%d %H:%M %Z") == "2027-03-14 18:00 CDT"


# --- Pages -----------------------------------------------------------------

def test_admin_previews_shuffles_and_publishes(client, admin_user, make_event, mixed_team):
    event = make_event(team_count=6, matches_per_team=5, total_matches=15)
    mixed_team(event)
    client.force_login(admin_user)
    url = reverse("scheduling:schedule", args=[event.pk])
    page = client.get(url)
    assert page.status_code == 200
    assert b"This is a preview" in page.content
    assert b"Team 2 (open spot)" in page.content
    assert client.get(url + "?seed=5").status_code == 200

    response = client.post(reverse("scheduling:publish", args=[event.pk]), {"seed": "5"})
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.schedule_seed == 5
    saved = client.get(url)
    assert saved.status_code == 200
    assert b"Start play" in saved.content


def test_saved_schedule_page_has_no_n_plus_1(client, admin_user, make_event, django_assert_max_num_queries):
    event = make_event(team_count=40, matches_per_team=6, total_matches=120, court_count=8)
    services.publish(event, 1)
    client.force_login(admin_user)
    with django_assert_max_num_queries(25):
        assert client.get(reverse("scheduling:schedule", args=[event.pk])).status_code == 200


def test_schedule_page_explains_missing_settings(client, admin_user, make_event):
    event = make_event(Division.Kind.SCRAMBLE, scramble_rounds=None, team_count=None)
    client.force_login(admin_user)
    page = client.get(reverse("scheduling:schedule", args=[event.pk]))
    assert page.status_code == 200
    assert b"number of rounds" in page.content


def test_round_and_match_edit_views(client, admin_user, make_event):
    event = make_event(team_count=4, court_count=2)
    services.publish(event, 1)
    client.force_login(admin_user)
    rnd = Round.objects.filter(event=event).first()
    match = rnd.matches.first()
    r = client.post(reverse("scheduling:round_time", args=[event.pk, rnd.pk]), {"start_time": "17:30"})
    assert r.status_code == 302 and r.url.endswith(f"#round-{rnd.pk}")
    r = client.post(reverse("scheduling:match_edit", args=[event.pk, match.pk]), {"start_time": "17:40", "court": "6"})
    assert r.status_code == 302
    match.refresh_from_db()
    assert match.court == 6


def test_players_cannot_touch_the_schedule(client, make_user, make_event):
    event = make_event()
    client.force_login(make_user())
    assert client.get(reverse("scheduling:schedule", args=[event.pk])).status_code == 403
    assert client.post(reverse("scheduling:publish", args=[event.pk]), {"seed": "1"}).status_code == 403
    assert not Round.objects.exists()
