"""End-to-end flows through the web pages."""

from html import unescape

import pytest
from django.urls import reverse

from accounts.models import Gender
from events import registration
from events.models import Division, Event, Level, OrganizationDefaults

pytestmark = pytest.mark.django_db
K = Division.Kind


def event_post_data(**overrides):
    data = {
        "title": "Spring Mixed",
        "level": Level.objects.get(name="Beginner").pk,
        "division": Division.objects.get(kind=K.MIXED).pk,
        "location": "Waco Regional Tennis and Fitness Center",
        "start_date": "2027-03-01",
        "weeks": "4",
        "end_date": "",
        "weekly_day": "",
        "start_time": "18:00",
        "team_count": "3",
        "matches_per_team": "16",
        "total_matches": "",
        "court_count": "4",
        "pool_size": "",
        "games_per_match": "3",
        "points_to_win": "11",
        "win_by_two": "on",
        "point_cap": "",
        "players_enter_scores": "on",
        "minutes_per_match": "20",
        "break_minutes": "5",
        "registration_mode": "BOTH",
        "max_participants": "64",
        "bracket_type": "SINGLE",
        "bracket_sizing": "BYES",
        "third_place_match": "on",
    }
    data.update(overrides)
    return data


# --- Admin ---------------------------------------------------------------

class TestAdminEvents:
    def test_players_cannot_open_manage(self, client, make_user):
        client.force_login(make_user())
        assert client.get(reverse("events:manage_home")).status_code == 403

    def test_anonymous_redirects_to_sign_in(self, client):
        response = client.get(reverse("events:manage_home"))
        assert response.status_code == 302
        assert reverse("accounts:login") in response.url

    def test_create_event(self, client, admin_user):
        client.force_login(admin_user)
        assert client.get(reverse("events:event_create")).status_code == 200
        response = client.post(reverse("events:event_create"), event_post_data())
        assert response.status_code == 302, response.context["form"].errors
        e = Event.objects.get()
        assert e.total_matches == 24  # 3 teams x 16 per team
        assert e.end_date.isoformat() == "2027-03-22"
        assert e.weekly_day == 0
        assert e.status == Event.Status.DRAFT
        # Settings are remembered for next time.
        assert OrganizationDefaults.get_solo().team_count == 3

    def test_create_from_total_matches(self, client, admin_user):
        client.force_login(admin_user)
        client.post(reverse("events:event_create"), event_post_data(matches_per_team="", total_matches="24"))
        assert Event.objects.get().matches_per_team == 16

    def test_edit_total_recalculates_per_team(self, client, admin_user, make_event):
        e = make_event(team_count=4, matches_per_team=3, total_matches=6)
        client.force_login(admin_user)
        data = event_post_data(team_count="4", matches_per_team="3", total_matches="10")
        client.post(reverse("events:event_edit", args=[e.pk]), data)
        e.refresh_from_db()
        assert e.total_matches == 10 and e.matches_per_team == 5

    def test_end_date_sets_weeks(self, client, admin_user):
        client.force_login(admin_user)
        client.post(reverse("events:event_create"), event_post_data(weeks="", end_date="2027-03-15"))
        assert Event.objects.get().weeks == 3

    @pytest.mark.parametrize("field,value", [("court_count", "9"), ("max_participants", "501"), ("point_cap", "10")])
    def test_rejects_bad_values(self, client, admin_user, field, value):
        client.force_login(admin_user)
        response = client.post(reverse("events:event_create"), event_post_data(**{field: value}))
        assert response.status_code == 200
        assert field in response.context["form"].errors
        assert not Event.objects.exists()

    def test_quick_create(self, client, admin_user):
        client.force_login(admin_user)
        response = client.post(reverse("events:quick_create"), {
            "level": Level.objects.first().pk, "division": Division.objects.first().pk,
            "start_date": "2027-03-01", "weeks": "1",
        })
        e = Event.objects.get()
        assert response.url == reverse("events:manage_event", args=[e.pk])

    def test_copy_last_event_prefills(self, client, admin_user, make_event):
        make_event(title="Monday League", court_count=6)
        client.force_login(admin_user)
        form = client.get(reverse("events:event_create") + "?copy=last").context["form"]
        assert form.initial["title"] == "Monday League (copy)"
        assert form.initial["court_count"] == 6

    def test_manage_page_and_qr(self, client, admin_user, make_event):
        e = make_event()
        client.force_login(admin_user)
        page = client.get(reverse("events:manage_event", args=[e.pk]))
        assert e.player_code in page.content.decode()
        qr = client.get(reverse("events:qr_code", args=[e.pk, "player"]))
        assert qr["Content-Type"] == "image/svg+xml"
        assert b"<svg" in qr.content

    def test_rotate_code(self, client, admin_user, make_event):
        e = make_event()
        old = e.spectator_code
        client.force_login(admin_user)
        client.post(reverse("events:code_action", args=[e.pk, "spectator", "rotate"]))
        e.refresh_from_db()
        assert e.spectator_code != old

    def test_open_signups(self, client, admin_user, make_event):
        e = make_event(status=Event.Status.DRAFT)
        client.force_login(admin_user)
        client.post(reverse("events:set_status", args=[e.pk]), {"status": "OPEN"})
        e.refresh_from_db()
        assert e.status == Event.Status.OPEN

    def test_admin_add_and_remove_player(self, client, admin_user, make_event, make_user):
        e = make_event()
        p = make_user().player
        client.force_login(admin_user)
        client.post(reverse("events:admin_add_player", args=[e.pk]), {"player": p.pk})
        assert registration.is_registered(e, p)
        client.post(reverse("events:admin_remove_player", args=[e.pk, p.pk]))
        assert not registration.is_registered(e, p)


class TestPagesRender:
    """Every page loads without errors, for the right kind of user."""

    def test_admin_pages(self, client, admin_user, make_event, make_user):
        from events import teams

        e = make_event()
        scramble = make_event(K.SCRAMBLE, title="Scramble", team_count=None)
        a, b = make_user(gender=Gender.MALE).player, make_user(gender=Gender.FEMALE).player
        registration.join(e, a)
        registration.join(e, b)
        teams.admin_build_team(e, [a, b])
        client.force_login(admin_user)
        for url in [
            reverse("events:manage_home"),
            reverse("events:edit_defaults"),
            reverse("events:event_create"),
            reverse("events:manage_event", args=[e.pk]),
            reverse("events:manage_event", args=[scramble.pk]),
            reverse("events:event_edit", args=[e.pk]),
            reverse("accounts:manage_players"),
            reverse("accounts:manage_players") + "?q=tes",
            reverse("accounts:manage_player", args=[a.pk]),
            reverse("accounts:manage_admins"),
            reverse("events:event_detail", args=[e.pk]),
        ]:
            assert client.get(url).status_code == 200, url

    def test_player_pages(self, client, make_event, make_user):
        e = make_event()
        user = make_user()
        registration.join(e, user.player)
        client.force_login(user)
        for url in [
            reverse("core:home"),
            reverse("accounts:profile"),
            reverse("events:join_enter"),
            reverse("events:event_detail", args=[e.pk]),
        ]:
            assert client.get(url).status_code == 200, url

    def test_public_pages(self, client, db):
        for url in [
            reverse("core:home"),
            reverse("accounts:login"),
            reverse("accounts:signup"),
            reverse("accounts:claim_start"),
            reverse("events:join_enter"),
        ]:
            assert client.get(url).status_code == 200, url


# --- Joining -------------------------------------------------------------

class TestJoin:
    def test_join_box_redirects_to_code(self, client, make_event):
        e = make_event()
        response = client.get(reverse("events:join_enter"), {"code": e.player_code.lower()})
        assert response.url == reverse("events:join_code", args=[e.player_code])

    def test_anonymous_player_code_goes_to_signup_then_back(self, client, make_event):
        e = make_event()
        join_url = reverse("events:join_code", args=[e.player_code])
        response = client.get(join_url)
        assert response.url.startswith(reverse("accounts:signup"))
        assert "next=" in response.url

        # Sign up, and land back on the join step.
        response = client.post(reverse("accounts:signup") + f"?next={join_url}", {
            "username": "newbie", "first_name": "New", "last_name": "Player", "gender": "F",
            "password1": "court-time-2027", "password2": "court-time-2027", "next": join_url,
        })
        assert response.url == join_url
        assert "Join this event" in client.get(join_url).content.decode()

        client.post(join_url)
        assert e.registrations.filter(player__user__username="newbie").exists()

    def test_signed_in_join(self, client, make_event, make_user):
        e = make_event()
        user = make_user()
        client.force_login(user)
        response = client.post(reverse("events:join_code", args=[e.player_code]))
        assert response.url == reverse("events:event_detail", args=[e.pk])
        assert registration.is_registered(e, user.player)

    def test_problem_shown_instead_of_button(self, client, make_event, make_user):
        e = make_event(K.WOMENS)
        client.force_login(make_user(gender=Gender.MALE))
        html = unescape(client.get(reverse("events:join_code", args=[e.player_code])).content.decode())
        assert "women's event" in html.lower()
        assert "Join this event" not in html

    def test_disabled_code(self, client, make_event):
        e = make_event(player_code_enabled=False)
        response = client.get(reverse("events:join_code", args=[e.player_code]), follow=True)
        assert "turned off" in response.content.decode()

    def test_unknown_code(self, client, db):
        response = client.get(reverse("events:join_code", args=["ZZZZZZ"]), follow=True)
        assert "couldn't find" in unescape(response.content.decode())

    def test_spectator_code_opens_placeholder_without_account(self, client, make_event):
        e = make_event(title="Spring Fling")
        response = client.get(reverse("events:join_code", args=[e.spectator_code]), follow=True)
        html = response.content.decode()
        assert response.status_code == 200
        assert "Spring Fling" in html
        assert "Spectator view" in html

    def test_disabled_spectator_code(self, client, make_event):
        e = make_event(spectator_code_enabled=False)
        assert client.get(reverse("events:watch", args=[e.spectator_code])).status_code == 404

    def test_team_code_from_join_box(self, client, make_event, make_user):
        from events import teams

        e = make_event()
        captain = make_user(gender=Gender.MALE).player
        registration.join(e, captain)
        side = teams.create_team(e, captain)
        partner = make_user(gender=Gender.FEMALE)
        client.force_login(partner)
        client.post(reverse("events:join_code", args=[side.team_code]))
        assert side.players.count() == 2
        assert registration.is_registered(e, partner.player)

    def test_player_team_flow(self, client, make_event, make_user):
        e = make_event()
        me = make_user(gender=Gender.MALE)
        make_user("partner", gender=Gender.FEMALE)
        registration.join(e, me.player)
        client.force_login(me)
        client.post(reverse("events:team_action", args=[e.pk, "create"]))
        client.post(reverse("events:team_action", args=[e.pk, "invite"]), {"username": "partner"})
        html = client.get(reverse("events:event_detail", args=[e.pk])).content.decode()
        assert "Waiting on" in html
