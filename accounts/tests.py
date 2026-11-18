import pytest
from django.urls import reverse

from accounts import services
from accounts.models import Gender, Player, User

pytestmark = pytest.mark.django_db


class TestSignupAndLogin:
    def test_signup_creates_user_and_player(self, client):
        response = client.post(reverse("accounts:signup"), {
            "username": "rachel", "first_name": "Rachel", "last_name": "Carter", "gender": "F",
            "password1": "court-time-2027", "password2": "court-time-2027",
        })
        assert response.status_code == 302
        user = User.objects.get(username="rachel")
        assert user.gender == Gender.FEMALE
        assert user.player.full_name == "Rachel Carter"
        assert user.player.public_name == "Rachel C."

    def test_signup_requires_gender(self, client):
        response = client.post(reverse("accounts:signup"), {
            "username": "x", "first_name": "X", "last_name": "Y",
            "password1": "court-time-2027", "password2": "court-time-2027",
        })
        assert "gender" in response.context["form"].errors

    def test_stay_signed_in_is_default(self, client, make_user):
        make_user("joe")
        client.post(reverse("accounts:login"), {"username": "joe", "password": "pickle-pass-123", "remember_me": "on"})
        assert client.session.get_expire_at_browser_close() is False
        assert client.session.get_expiry_age() >= 60 * 60 * 24 * 365

    def test_unticked_stay_signed_in_ends_at_browser_close(self, client, make_user):
        make_user("joe")
        client.post(reverse("accounts:login"), {"username": "joe", "password": "pickle-pass-123"})
        assert client.session.get_expire_at_browser_close() is True

    def test_login_form_ticks_stay_signed_in(self, client):
        html = client.get(reverse("accounts:login")).content.decode()
        assert 'name="remember_me"' in html and "checked" in html

    def test_profile_update_syncs_player(self, client, make_user):
        user = make_user()
        client.force_login(user)
        client.post(reverse("accounts:profile"), {"first_name": "Sam", "last_name": "Lee", "gender": "F"})
        user.refresh_from_db()
        assert user.player.first_name == "Sam"
        assert user.player.gender == "F"


class TestClaim:
    def test_admin_added_player_can_claim(self, client, admin_user):
        player = services.add_player(first_name="Pat", last_name="Doe", gender="M", created_by=admin_user)
        assert len(player.claim_code) == 8
        response = client.post(reverse("accounts:claim", args=[player.claim_code.lower()]), {
            "username": "patd", "password1": "court-time-2027", "password2": "court-time-2027",
        })
        assert response.status_code == 302
        player.refresh_from_db()
        assert player.user.username == "patd"
        assert player.user.first_name == "Pat"
        assert player.user.gender == "M"
        assert player.claim_code is None

    def test_used_code_stops_working(self, client, admin_user):
        player = services.add_player(first_name="Pat", last_name="Doe", gender="M", created_by=admin_user)
        code = player.claim_code
        services.claim_player(player, username="patd", password="court-time-2027")
        response = client.get(reverse("accounts:claim", args=[code]))
        assert response.url == reverse("accounts:claim_start")

    def test_admin_adds_player_via_page(self, client, admin_user):
        client.force_login(admin_user)
        client.post(reverse("accounts:manage_players"), {"first_name": "Lou", "last_name": "Ng", "gender": "F"})
        player = Player.objects.get(first_name="Lou")
        page = client.get(reverse("accounts:manage_player", args=[player.pk])).content.decode()
        assert player.claim_code in page


class TestMerge:
    """Folding a duplicate profile into another one."""

    @pytest.fixture
    def setup(self, admin_user, make_user, make_event):
        from events import registration

        added = services.add_player(first_name="Pat", last_name="Doe", gender="F", created_by=admin_user)
        signed_up = make_user("patd", gender="F", first_name="Pat", last_name="Doe")
        event = make_event()
        registration.admin_add(event, added)
        return added, signed_up, event

    def test_admin_added_profile_merges_into_account(self, setup):
        from events import registration

        added, signed_up, event = setup
        kept = services.merge_players(keep=signed_up.player, remove=added)
        assert kept.user == signed_up
        assert registration.is_registered(event, kept)
        assert not Player.objects.filter(pk=added.pk).exists()

    def test_merge_the_other_way_keeps_the_login(self, setup):
        added, signed_up, _ = setup
        old_pk = signed_up.player.pk
        kept = services.merge_players(keep=added, remove=signed_up.player)
        assert kept.pk == added.pk
        assert kept.user == signed_up
        assert kept.claim_code is None
        assert not Player.objects.filter(pk=old_pk).exists()

    def test_shared_event_leaves_one_registration(self, setup):
        from events import registration

        added, signed_up, event = setup
        registration.join(event, signed_up.player)
        kept = services.merge_players(keep=signed_up.player, remove=added)
        assert event.registrations.filter(player=kept).count() == 1
        assert event.registrations.count() == 1

    def test_team_moves_over(self, setup, make_user):
        from events import registration, teams

        added, signed_up, event = setup
        partner = make_user(gender="M").player
        registration.join(event, partner)
        side = teams.admin_build_team(event, [added, partner])
        kept = services.merge_players(keep=signed_up.player, remove=added)
        assert set(side.players.all()) == {kept, partner}

    def test_different_teams_in_same_event_blocked(self, setup, make_user):
        from events import registration, teams

        added, signed_up, event = setup
        registration.join(event, signed_up.player)
        teams.create_team(event, added)
        teams.create_team(event, signed_up.player)
        with pytest.raises(services.MergeError, match="different teams"):
            services.merge_players(keep=signed_up.player, remove=added)
        assert Player.objects.filter(pk=added.pk).exists()  # nothing changed

    def test_two_logins_cannot_merge(self, make_user):
        a, b = make_user(), make_user()
        with pytest.raises(services.MergeError, match="own login"):
            services.merge_players(keep=a.player, remove=b.player)

    def test_invite_to_own_team_is_dropped(self, setup):
        from events import teams
        from events.models import TeamInvite

        added, signed_up, event = setup
        side = teams.create_team(event, added)
        # An invite from one profile to the other (created directly; the Mixed rule would refuse it).
        TeamInvite.objects.create(side=side, player=signed_up.player, invited_by=added)
        services.merge_players(keep=signed_up.player, remove=added)
        assert not TeamInvite.objects.exists()

    def test_signed_in_player_links_with_claim_code(self, client, setup):
        from events import registration

        added, signed_up, event = setup
        client.force_login(signed_up)
        url = reverse("accounts:claim", args=[added.claim_code])
        assert "Link to my account" in client.get(url).content.decode()
        client.post(url)
        assert registration.is_registered(event, signed_up.player)
        assert not Player.objects.filter(pk=added.pk).exists()

    def test_admin_merges_from_player_page(self, client, admin_user, setup):
        added, signed_up, event = setup
        client.force_login(admin_user)
        url = reverse("accounts:manage_player", args=[signed_up.player.pk])
        assert "Merge a duplicate" in client.get(url).content.decode()
        client.post(url, {"merge": "1", "duplicate": added.pk})
        assert not Player.objects.filter(pk=added.pk).exists()
        assert event.registrations.filter(player=signed_up.player).exists()

    def test_merge_list_hides_other_logins(self, admin_user, make_user):
        from accounts.forms import MergeForm

        a, b = make_user(), make_user()
        form = MergeForm(player=a.player)
        assert b.player not in form.fields["duplicate"].queryset

    def test_players_cannot_merge(self, client, setup, make_user):
        added, signed_up, _ = setup
        client.force_login(make_user())
        url = reverse("accounts:manage_player", args=[signed_up.player.pk])
        assert client.post(url, {"merge": "1", "duplicate": added.pk}).status_code == 403
        assert Player.objects.filter(pk=added.pk).exists()


class TestAdmins:
    def test_cannot_remove_last_admin(self, admin_user):
        with pytest.raises(services.LastAdminError):
            services.remove_admin(admin_user)
        admin_user.refresh_from_db()
        assert admin_user.is_staff

    def test_any_admin_can_remove_another(self, client, admin_user, make_user):
        other = make_user("co", staff=True)
        client.force_login(other)
        client.post(reverse("accounts:remove_admin", args=[admin_user.pk]))
        admin_user.refresh_from_db()
        assert not admin_user.is_staff

    def test_last_admin_removal_blocked_via_page(self, client, admin_user):
        client.force_login(admin_user)
        response = client.post(reverse("accounts:remove_admin", args=[admin_user.pk]), follow=True)
        assert "last admin" in response.content.decode()
        admin_user.refresh_from_db()
        assert admin_user.is_staff

    def test_promote_existing_user(self, client, admin_user, make_user):
        make_user("helper")
        client.force_login(admin_user)
        client.post(reverse("accounts:manage_admins"), {"promote": "1", "promote-username": "Helper"})
        assert User.objects.get(username="helper").is_staff

    def test_create_new_admin(self, client, admin_user):
        client.force_login(admin_user)
        client.post(reverse("accounts:manage_admins"), {
            "create": "1", "create-username": "newadmin", "create-first_name": "New",
            "create-last_name": "Admin", "create-gender": "F",
            "create-password1": "court-time-2027", "create-password2": "court-time-2027",
        })
        assert User.objects.get(username="newadmin").is_staff

    def test_non_admin_cannot_manage_admins(self, client, make_user):
        client.force_login(make_user())
        assert client.get(reverse("accounts:manage_admins")).status_code == 403


class TestPasswordReset:
    def test_admin_resets_password(self, client, admin_user, make_user):
        user = make_user("forgetful")
        client.force_login(admin_user)
        client.post(reverse("accounts:manage_player", args=[user.player.pk]), {
            "new_password1": "brand-new-pass-77", "new_password2": "brand-new-pass-77",
        })
        user.refresh_from_db()
        assert user.check_password("brand-new-pass-77")

    def test_player_cannot_reset_others(self, client, make_user):
        victim = make_user("victim")
        client.force_login(make_user())
        response = client.post(reverse("accounts:manage_player", args=[victim.player.pk]), {
            "new_password1": "brand-new-pass-77", "new_password2": "brand-new-pass-77",
        })
        assert response.status_code == 403
        victim.refresh_from_db()
        assert not victim.check_password("brand-new-pass-77")
