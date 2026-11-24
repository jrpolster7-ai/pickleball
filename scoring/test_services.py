"""Score entry, confirmation, disputes, locking, admin fixes, forfeits (section 7)."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse

from accounts.services import player_for
from core.models import AuditLog
from events import registration, teams
from events.models import Division
from scheduling import services as scheduling
from scheduling.models import Match
from scoring import services
from scoring.models import ScoreSubmission
from scoring.services import ScoreError

pytestmark = pytest.mark.django_db
UTC = ZoneInfo("UTC")
Status = ScoreSubmission.Status


@pytest.fixture
def setup(make_event, make_user, admin_user):
    """A Men's event, 2 teams, 1 match, best of 3, play started."""
    def _make(start=True, **kw):
        event = make_event(Division.Kind.MENS, team_count=2, matches_per_team=1, total_matches=1, **kw)
        players = []
        for _ in range(4):
            p = player_for(make_user())
            registration.admin_add(event, p)
            players.append(p)
        teams.admin_build_team(event, players[:2])
        teams.admin_build_team(event, players[2:])
        scheduling.publish(event, 1)
        if start:
            scheduling.start_play(event)
        event.refresh_from_db()
        match = Match.objects.get(event=event)
        a = list(match.side_a.players.all())
        b = list(match.side_b.players.all())
        return event, match, a, b
    return _make


def reload(match):
    return Match.objects.get(pk=match.pk)


def games_of(match):
    return list(match.games.values_list("side_a_points", "side_b_points"))


def test_one_side_enters_and_the_other_confirms(setup):
    event, match, a, b = setup()
    sub = services.submit(match, a[0], [(11, 7), (11, 9)])
    assert sub.status == Status.PENDING
    assert reload(match).status == Match.Status.PENDING
    assert games_of(match) == []  # nothing official until confirmed

    services.confirm(sub, b[1])
    match = reload(match)
    assert match.status == Match.Status.CONFIRMED
    assert match.winner == "A"
    assert games_of(match) == [(11, 7), (11, 9)]
    sub.refresh_from_db()
    assert sub.status == Status.CONFIRMED and sub.confirmed_by == b[1]
    assert AuditLog.objects.filter(event=event, action="score entered").exists()
    assert AuditLog.objects.filter(event=event, action="score confirmed").exists()


def test_your_own_side_cannot_confirm(setup):
    _, match, a, _ = setup()
    sub = services.submit(match, a[0], [(11, 7), (11, 9)])
    with pytest.raises(ScoreError, match="other side"):
        services.confirm(sub, a[1])


def test_both_sides_enter_the_same_score(setup):
    _, match, a, b = setup()
    services.submit(match, a[0], [(5, 11), (11, 8), (9, 11)])
    services.submit(match, b[0], [(5, 11), (11, 8), (9, 11)])
    match = reload(match)
    assert match.status == Match.Status.CONFIRMED
    assert match.winner == "B"


def test_a_correction_goes_back_to_the_other_side(setup):
    _, match, a, b = setup()
    services.submit(match, a[0], [(11, 7), (11, 9)])
    services.submit(match, b[0], [(11, 7), (9, 11), (8, 11)])
    match = reload(match)
    assert match.status == Match.Status.PENDING, "no organizer needed"
    assert list(match.submissions.order_by("id").values_list("status", flat=True)) == [Status.SUPERSEDED, Status.PENDING]
    view = services.player_view(match, a[0])
    assert view.action == "confirm" and "changed the score to 11-7, 9-11, 8-11" in view.label
    assert AuditLog.objects.filter(action="score corrected", old_value="11-7, 11-9").exists()

    services.confirm(view.waiting, a[0])
    match = reload(match)
    assert match.status == Match.Status.CONFIRMED and match.winner == "B"
    assert games_of(match) == [(11, 7), (9, 11), (8, 11)]


def test_corrections_can_go_back_and_forth(setup):
    _, match, a, b = setup()
    services.submit(match, a[0], [(11, 7), (11, 9)])
    services.submit(match, b[0], [(7, 11), (9, 11)])
    services.submit(match, a[1], [(11, 7), (11, 8)])  # a's partner corrects again
    assert reload(match).status == Match.Status.PENDING
    services.submit(match, b[1], [(11, 7), (11, 8)])  # same score: final
    match = reload(match)
    assert match.status == Match.Status.CONFIRMED and games_of(match) == [(11, 7), (11, 8)]


def test_either_side_can_ask_an_organizer(setup):
    _, match, a, b = setup()
    with pytest.raises(services.ScoreError, match="Enter the score first"):
        services.ask_organizer(match, a[0])
    services.submit(match, a[0], [(11, 7), (11, 9)])
    assert services.player_view(reload(match), a[0]).can_ask, "the side that entered can ask too"
    assert services.player_view(reload(match), b[0]).can_ask
    services.ask_organizer(match, b[0])
    match = reload(match)
    assert match.status == Match.Status.DISPUTED
    assert set(match.submissions.values_list("status", flat=True)) == {Status.DISPUTED}
    assert AuditLog.objects.filter(action="organizer asked", new_value="11-7, 11-9").exists()
    with pytest.raises(services.ScoreError, match="already been asked"):
        services.ask_organizer(match, a[0])
    assert not services.player_view(match, a[0]).can_ask


def test_after_asking_an_organizer_players_can_still_agree(setup):
    _, match, a, b = setup()
    services.submit(match, a[0], [(11, 7), (11, 9)])
    services.ask_organizer(match, b[0])
    services.submit(match, b[0], [(7, 11), (9, 11)])
    assert reload(match).status == Match.Status.DISPUTED, "a different score keeps it flagged"
    services.submit(match, a[0], [(7, 11), (9, 11)])
    match = reload(match)
    assert match.status == Match.Status.CONFIRMED and match.winner == "B"


def test_resubmitting_replaces_your_own_entry(setup):
    _, match, a, _ = setup()
    services.submit(match, a[0], [(11, 7), (11, 9)])
    services.submit(match, a[1], [(11, 7), (11, 8)])
    assert list(match.submissions.order_by("id").values_list("status", flat=True)) == [Status.SUPERSEDED, Status.PENDING]


def test_impossible_scores_are_rejected(setup):
    _, match, a, _ = setup()
    with pytest.raises(ScoreError, match="win by two"):
        services.submit(match, a[0], [(11, 10), (11, 5)])
    with pytest.raises(ScoreError, match="isn't finished"):
        services.submit(match, a[0], [(11, 5)])
    assert not match.submissions.exists()


def test_only_players_in_the_match(setup, make_user):
    _, match, _, _ = setup()
    with pytest.raises(ScoreError, match="Only players in this match"):
        services.submit(match, player_for(make_user()), [(11, 7), (11, 9)])


def test_scores_wait_until_play_starts(setup):
    _, match, a, _ = setup(start=False)
    with pytest.raises(ScoreError, match="starts play"):
        services.submit(match, a[0], [(11, 7), (11, 9)])


def test_event_without_player_entry(setup, admin_user):
    _, match, a, _ = setup(players_enter_scores=False)
    with pytest.raises(ScoreError, match="organizer enters"):
        services.submit(match, a[0], [(11, 7), (11, 9)])
    services.admin_set_score(match, [(11, 7), (11, 9)], admin_user)
    assert reload(match).status == Match.Status.CONFIRMED


# --- Midnight lock --------------------------------------------------------

def test_player_edits_lock_at_midnight_central(setup):
    day = datetime.date(2027, 6, 7)
    _, match, a, b = setup(start_date=day, end_date=day)
    just_before = datetime.datetime(2027, 6, 8, 4, 59, tzinfo=UTC)  # 11:59 PM CDT
    midnight = datetime.datetime(2027, 6, 8, 5, 0, tzinfo=UTC)
    sub = services.submit(match, a[0], [(11, 7), (11, 9)], now=just_before)
    with pytest.raises(ScoreError, match="closed at midnight"):
        services.confirm(sub, b[0], now=midnight)
    with pytest.raises(ScoreError, match="closed at midnight"):
        services.submit(match, b[0], [(11, 7), (11, 9)], now=midnight)


def test_lock_on_spring_forward_day(setup):
    """March 14, 2027: the match day is only 23 hours long."""
    day = datetime.date(2027, 3, 14)
    _, match, a, _ = setup(start_date=day, end_date=day)
    assert services.lock_time(match).astimezone(UTC) == datetime.datetime(2027, 3, 15, 5, 0, tzinfo=UTC)
    assert not services.is_locked(match, now=datetime.datetime(2027, 3, 15, 4, 59, tzinfo=UTC))
    assert services.is_locked(match, now=datetime.datetime(2027, 3, 15, 5, 0, tzinfo=UTC))


def test_lock_on_fall_back_day(setup):
    """November 7, 2027: the match day is 25 hours long."""
    day = datetime.date(2027, 11, 7)
    _, match, a, _ = setup(start_date=day, end_date=day)
    assert services.lock_time(match).astimezone(UTC) == datetime.datetime(2027, 11, 8, 6, 0, tzinfo=UTC)
    assert not services.is_locked(match, now=datetime.datetime(2027, 11, 8, 5, 30, tzinfo=UTC))


def test_lock_follows_a_moved_match(setup):
    day = datetime.date(2027, 6, 7)
    event, match, a, _ = setup(start_date=day, end_date=day)
    match.start_time = match.start_time + datetime.timedelta(days=1)
    match.save()
    assert services.match_day(match) == datetime.date(2027, 6, 8)


def test_admin_can_edit_after_the_lock(setup, admin_user):
    day = datetime.date(2020, 1, 6)  # long past
    _, match, a, _ = setup(start_date=day, end_date=day)
    with pytest.raises(ScoreError, match="closed"):
        services.submit(match, a[0], [(11, 7), (11, 9)])
    services.admin_set_score(match, [(11, 7), (11, 9)], admin_user)
    assert reload(match).status == Match.Status.CONFIRMED


# --- Admin fixes, audit, forfeits ----------------------------------------

def test_admin_settles_a_dispute_and_it_is_logged(setup, admin_user):
    event, match, a, b = setup()
    services.submit(match, a[0], [(11, 7), (11, 9)])
    services.ask_organizer(match, b[0])
    services.submit(match, b[0], [(7, 11), (9, 11)])
    services.admin_set_score(match, [(11, 7), (11, 9)], admin_user)
    match = reload(match)
    assert match.status == Match.Status.CONFIRMED
    assert set(match.submissions.values_list("status", flat=True)) == {Status.RESOLVED}

    services.admin_set_score(match, [(11, 7), (8, 11), (11, 2)], admin_user)
    entry = AuditLog.objects.filter(action="score set by admin").first()
    assert entry.actor == admin_user
    assert entry.old_value == "11-7, 11-9"
    assert entry.new_value == "11-7, 8-11, 11-2"
    assert entry.object_id == match.pk and entry.event == event


def test_admin_scores_are_validated_too(setup, admin_user):
    _, match, _, _ = setup()
    with pytest.raises(ScoreError):
        services.admin_set_score(match, [(11, 10), (11, 0)], admin_user)


def test_players_can_correct_a_confirmed_score_before_the_lock(setup):
    _, match, a, b = setup()
    services.submit(match, a[0], [(11, 7), (11, 9)])
    services.submit(match, b[0], [(11, 7), (11, 9)])
    fix = services.submit(match, b[0], [(11, 7), (11, 8)])
    assert reload(match).status == Match.Status.PENDING
    assert games_of(match) == [(11, 7), (11, 9)]  # old result stands until confirmed
    services.confirm(fix, a[0])
    assert games_of(match) == [(11, 7), (11, 8)]


def test_clear_score(setup, admin_user):
    _, match, a, _ = setup()
    services.admin_set_score(match, [(11, 7), (11, 9)], admin_user)
    services.admin_clear_score(match, admin_user)
    match = reload(match)
    assert match.status == Match.Status.SCHEDULED and match.winner == "" and games_of(match) == []
    assert AuditLog.objects.filter(action="score cleared", old_value="11-7, 11-9").exists()


def test_forfeit_default_and_custom_score(setup, admin_user):
    _, match, _, _ = setup()
    services.forfeit(match, "A", admin_user)
    match = reload(match)
    assert match.forfeit and match.winner == "B"
    assert games_of(match) == [(0, 11), (0, 11)]

    event, match2, _, _ = setup(forfeit_points=7, games_per_match=1)
    services.forfeit(match2, "B", admin_user)
    assert games_of(match2) == [(7, 0)]
    assert AuditLog.objects.filter(action="forfeit", event=event).exists()


def test_withdrawal_forfeits_only_unfinished_matches(make_event, make_user, admin_user):
    event = make_event(Division.Kind.MENS, team_count=3, matches_per_team=2, total_matches=3)
    sides = []
    for _ in range(3):
        p1, p2 = player_for(make_user()), player_for(make_user())
        registration.admin_add(event, p1)
        registration.admin_add(event, p2)
        sides.append(teams.admin_build_team(event, [p1, p2]))
    scheduling.publish(event, 1)
    scheduling.start_play(event)
    event.refresh_from_db()
    leaving = sides[0]
    theirs = list(Match.objects.filter(event=event).filter(side_a=leaving) | Match.objects.filter(event=event, side_b=leaving))
    services.admin_set_score(theirs[0], [(11, 3), (11, 4)], admin_user)

    assert services.withdraw(leaving, admin_user) == 1
    played, forfeited = reload(theirs[0]), reload(theirs[1])
    assert not played.forfeit
    assert forfeited.forfeit and forfeited.status == Match.Status.CONFIRMED
    assert forfeited.winner == ("B" if forfeited.side_a_id == leaving.pk else "A")
    assert AuditLog.objects.filter(action="team withdrawn").exists()


def test_withdraw_needs_play_started(setup, admin_user):
    _, match, _, _ = setup(start=False)
    with pytest.raises(ScoreError):
        services.withdraw(match.side_a, admin_user)


# --- What players see -----------------------------------------------------

def test_player_view_states(setup):
    _, match, a, b = setup()
    assert services.player_view(reload(match), a[0]).action == "enter"
    services.submit(match, a[0], [(11, 7), (11, 9)])
    assert "Waiting" in services.player_view(reload(match), a[0]).label
    view = services.player_view(reload(match), b[0])
    assert view.action == "confirm" and view.waiting is not None
    services.confirm(view.waiting, b[0])
    assert services.player_view(reload(match), b[0]).label == "Final: 11-7, 11-9"


# --- Pages -----------------------------------------------------------------

def test_player_enters_and_confirms_through_the_pages(client, setup):
    event, match, a, b = setup()
    url = reverse("scoring:match_score", args=[match.pk])

    client.force_login(a[0].user)
    detail = client.get(reverse("events:event_detail", args=[event.pk]))
    assert b"Enter score" in detail.content
    assert client.get(url).status_code == 200
    r = client.post(url, {"action": "enter", "g1_a": "11", "g1_b": "6", "g2_a": "11", "g2_b": "8", "g3_a": "", "g3_b": ""})
    assert r.status_code == 302

    client.force_login(b[0].user)
    page = client.get(url)
    assert b"Is this score right?" in page.content
    sub = match.submissions.get()
    client.post(url, {"action": "confirm", "submission": sub.pk})
    assert reload(match).status == Match.Status.CONFIRMED


def test_bad_score_shows_a_friendly_error(client, setup):
    _, match, a, _ = setup()
    client.force_login(a[0].user)
    r = client.post(reverse("scoring:match_score", args=[match.pk]),
                    {"action": "enter", "g1_a": "11", "g1_b": "10", "g2_a": "11", "g2_b": "3"})
    assert r.status_code == 200
    assert b"win by two" in r.content
    assert not match.submissions.exists()


def test_outsiders_cannot_open_a_match(client, setup, make_user):
    _, match, _, _ = setup()
    client.force_login(make_user())
    assert client.get(reverse("scoring:match_score", args=[match.pk])).status_code == 404
    assert client.get(reverse("scoring:admin_match", args=[match.event_id, match.pk])).status_code == 403


def test_admin_pages(client, setup, admin_user):
    event, match, a, b = setup()
    client.force_login(admin_user)
    url = reverse("scoring:admin_match", args=[event.pk, match.pk])
    assert client.get(url).status_code == 200
    client.post(url, {"action": "set", "g1_a": "11", "g1_b": "2", "g2_a": "11", "g2_b": "4"})
    assert reload(match).status == Match.Status.CONFIRMED
    client.post(url, {"action": "forfeit", "side": "B"})
    assert reload(match).forfeit
    client.post(url, {"action": "clear"})
    assert reload(match).status == Match.Status.SCHEDULED
    log = client.get(reverse("scoring:audit_log", args=[event.pk]))
    assert log.status_code == 200 and b"Forfeit" in log.content
    schedule = client.get(reverse("scheduling:schedule", args=[event.pk]))
    assert b"Enter score" in schedule.content


ENTRY = {"action": "enter", "g1_a": "11", "g1_b": "6", "g2_a": "11", "g2_b": "8", "g3_a": "", "g3_b": ""}


def test_confirm_page_shows_the_score_in_team_columns(client, setup):
    event, match, a, b = setup()
    url = reverse("scoring:match_score", args=[match.pk])
    client.force_login(a[0].user)
    client.post(url, ENTRY)

    client.force_login(b[0].user)
    html = client.get(url).content.decode()
    from html import unescape
    table = unescape(html.split("Is this score right?")[1].split("Yes, that")[0])
    assert match.label_a in table and match.label_b in table
    assert table.index(">11<") < table.index(">6<") < table.index(">11<", table.index(">6<")) < table.index(">8<")
    assert ">You<" in table
    assert f"Winner: <strong>{match.label_a}</strong> (your opponent)" in table


def test_player_can_correct_a_wrong_entry_from_the_confirm_page(client, setup):
    event, match, a, b = setup()
    url = reverse("scoring:match_score", args=[match.pk])
    client.force_login(a[0].user)
    client.post(url, ENTRY)

    client.force_login(b[0].user)
    html = client.get(url).content.decode()
    fix = html.split('id="fix"')[1]
    assert 'name="g1_a"' in fix and 'value="11"' in fix and 'value="6"' in fix, "boxes start with their score"

    r = client.post(url, {**ENTRY, "g2_a": "9", "g2_b": "11", "g3_a": "8", "g3_b": "11"})
    assert r.status_code == 302
    assert reload(match).status == Match.Status.PENDING, "goes back to them, not the organizer"

    client.force_login(a[0].user)
    html = client.get(url).content.decode()
    assert "Your opponent changed the score you entered." in html
    assert "Your opponent entered this score." not in html
    client.post(url, {"action": "confirm", "submission": match.submissions.get(status=Status.PENDING).pk})
    assert reload(match).status == Match.Status.CONFIRMED


def test_correcting_to_the_same_score_makes_it_final(client, setup):
    event, match, a, b = setup()
    url = reverse("scoring:match_score", args=[match.pk])
    client.force_login(a[0].user)
    client.post(url, ENTRY)
    client.force_login(b[0].user)
    client.post(url, ENTRY)
    assert reload(match).status == Match.Status.CONFIRMED


def test_a_bad_correction_keeps_the_boxes_open_with_the_error(client, setup):
    event, match, a, b = setup()
    url = reverse("scoring:match_score", args=[match.pk])
    client.force_login(a[0].user)
    client.post(url, ENTRY)
    client.force_login(b[0].user)
    r = client.post(url, {**ENTRY, "g1_a": "11", "g1_b": "10"})
    html = r.content.decode()
    assert r.status_code == 200
    assert '<details id="fix" class="mt-6 border-t border-line pt-4" open>' in html
    assert reload(match).status == Match.Status.PENDING


def test_ask_an_organizer_button(client, setup):
    event, match, a, b = setup()
    url = reverse("scoring:match_score", args=[match.pk])
    client.force_login(a[0].user)
    assert b"Ask an organizer to decide" not in client.get(url).content, "nothing entered yet"
    client.post(url, ENTRY)
    client.force_login(b[0].user)
    assert b"Ask an organizer to decide" in client.get(url).content
    client.post(url, {"action": "ask"})
    assert reload(match).status == Match.Status.DISPUTED
    html = client.get(url).content.decode()
    assert "An organizer has been asked to decide." in html
    assert "Ask an organizer to decide" not in html
