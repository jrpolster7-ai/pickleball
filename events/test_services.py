"""Codes, eligibility, registration, teams, and saved defaults."""

import datetime

import pytest

from accounts.models import Gender, Player
from events import codes, defaults, registration, teams
from events.eligibility import registration_problem, team_problem
from events.models import Division, Event, Level, OrganizationDefaults, RegistrationMode, TeamInvite

K = Division.Kind
M, F = Gender.MALE, Gender.FEMALE


def P(gender, name="P"):
    return Player(first_name=name, last_name="X", gender=gender)


# --- Codes ---------------------------------------------------------------

@pytest.mark.django_db
class TestCodes:
    def test_event_gets_distinct_codes(self, make_event):
        e = make_event()
        assert len(e.player_code) == 6
        assert e.player_code != e.spectator_code

    def test_find_code_by_kind_and_case(self, make_event):
        e = make_event()
        assert codes.find_code(e.player_code.lower()).kind == codes.PLAYER
        assert codes.find_code(e.spectator_code).kind == codes.SPECTATOR
        assert codes.find_code("NOPE99") is None
        assert codes.find_code("") is None

    def test_team_code_lookup(self, make_event, make_user):
        e = make_event()
        p = make_user(gender=M).player
        registration.join(e, p)
        side = teams.create_team(e, p)
        match = codes.find_code(side.team_code)
        assert match.kind == codes.TEAM and match.side == side

    def test_rotate_kills_old_code(self, make_event):
        e = make_event()
        old = e.player_code
        new = codes.rotate_code(e, codes.PLAYER)
        assert new != old
        assert codes.find_code(old) is None
        assert codes.find_code(new).event == e

    def test_disable_and_enable(self, make_event):
        e = make_event()
        codes.set_code_enabled(e, codes.SPECTATOR, False)
        assert codes.find_code(e.spectator_code).enabled is False
        codes.set_code_enabled(e, codes.SPECTATOR, True)
        assert codes.find_code(e.spectator_code).enabled is True


# --- Eligibility ---------------------------------------------------------

@pytest.mark.django_db
class TestEligibility:
    @pytest.mark.parametrize("kind,gender,ok", [
        (K.MENS, M, True), (K.MENS, F, False),
        (K.WOMENS, F, True), (K.WOMENS, M, False),
        (K.MIXED, M, True), (K.MIXED, F, True),
        (K.SCRAMBLE, M, True), (K.SCRAMBLE, F, True),
    ])
    def test_registration(self, division, kind, gender, ok):
        assert (registration_problem(division(kind), P(gender)) is None) is ok

    def test_missing_gender_blocks_gendered_divisions(self, division):
        assert registration_problem(division(K.MENS), P("")) is not None
        assert registration_problem(division(K.MIXED), P("")) is None

    @pytest.mark.parametrize("kind,genders,ok", [
        (K.MENS, (M, M), True), (K.MENS, (M, F), False),
        (K.WOMENS, (F, F), True), (K.WOMENS, (F, M), False),
        (K.MIXED, (M, F), True), (K.MIXED, (F, M), True),
        (K.MIXED, (M, M), False), (K.MIXED, (F, F), False),
    ])
    def test_teams(self, division, kind, genders, ok):
        pair = [P(g, f"p{i}") for i, g in enumerate(genders)]
        assert (team_problem(division(kind), pair) is None) is ok

    def test_scramble_has_no_teams(self, division):
        assert team_problem(division(K.SCRAMBLE), [P(M), P(F)]) is not None


# --- Registration --------------------------------------------------------

@pytest.mark.django_db
class TestRegistration:
    def test_join_open_event(self, make_event, make_user):
        e = make_event()
        p = make_user().player
        reg = registration.join(e, p)
        assert reg.event == e
        assert registration.join(e, p) == reg  # joining twice is harmless

    @pytest.mark.parametrize("status", [Event.Status.DRAFT, Event.Status.ROUND_ROBIN])
    def test_closed_events_block_join(self, make_event, make_user, status):
        e = make_event(status=status)
        with pytest.raises(registration.RegistrationError):
            registration.join(e, make_user().player)

    def test_admin_only_mode_blocks_self_join(self, make_event, make_user):
        e = make_event(registration_mode=RegistrationMode.ADMIN)
        with pytest.raises(registration.RegistrationError, match="organizer adds"):
            registration.join(e, make_user().player)

    def test_wrong_gender_blocked(self, make_event, make_user):
        e = make_event(K.WOMENS)
        with pytest.raises(registration.RegistrationError):
            registration.join(e, make_user(gender=M).player)

    def test_capacity_from_team_count(self, make_event, make_user):
        e = make_event(team_count=2)  # 4 player spots
        for _ in range(4):
            registration.join(e, make_user().player)
        with pytest.raises(registration.RegistrationError, match="full"):
            registration.join(e, make_user().player)

    def test_capacity_from_max_participants(self, make_event, make_user):
        e = make_event(K.SCRAMBLE, team_count=None, max_participants=2)
        registration.join(e, make_user().player)
        registration.join(e, make_user().player)
        with pytest.raises(registration.RegistrationError):
            registration.join(e, make_user().player)

    def test_admin_override(self, make_event, make_user):
        e = make_event(K.MENS, status=Event.Status.DRAFT)
        woman = make_user(gender=F).player
        with pytest.raises(registration.RegistrationError):
            registration.admin_add(e, woman)
        assert registration.admin_add(e, woman, override=True)

    def test_admin_add_ignores_status_and_mode(self, make_event, make_user):
        e = make_event(status=Event.Status.DRAFT, registration_mode=RegistrationMode.ADMIN)
        assert registration.admin_add(e, make_user().player)

    def test_remove_clears_team(self, make_event, make_user):
        e = make_event()
        a, b = make_user(gender=M).player, make_user(gender=F).player
        registration.join(e, a)
        registration.join(e, b)
        side = teams.admin_build_team(e, [a, b])
        registration.remove(e, a)
        assert not registration.is_registered(e, a)
        assert list(side.players.all()) == [b]
        registration.remove(e, b)
        assert not e.sides.exists()

    def test_move(self, make_event, make_user):
        e1, e2 = make_event(), make_event(title="Other")
        p = make_user().player
        registration.join(e1, p)
        registration.move(p, e1, e2)
        assert not registration.is_registered(e1, p)
        assert registration.is_registered(e2, p)

    def test_move_failure_keeps_old_spot(self, make_event, make_user):
        e1, e2 = make_event(), make_event(K.WOMENS, title="Women")
        p = make_user(gender=M).player
        registration.join(e1, p)
        with pytest.raises(registration.RegistrationError):
            registration.move(p, e1, e2)
        assert registration.is_registered(e1, p)


# --- Teams ---------------------------------------------------------------

@pytest.mark.django_db
class TestTeams:
    def _joined(self, event, make_user, gender, name=None):
        p = make_user(name, gender=gender).player
        registration.join(event, p)
        return p

    def test_create_and_join_by_team_code(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        b = make_user(gender=F).player  # not registered yet
        side = teams.create_team(e, a)
        teams.join_by_team_code(side, b)
        assert set(side.players.all()) == {a, b}
        assert registration.is_registered(e, b)

    def test_mixed_rejects_same_gender_partner(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        side = teams.create_team(e, a)
        with pytest.raises(teams.TeamError, match="one male and one female"):
            teams.join_by_team_code(side, make_user(gender=M).player)

    def test_team_full(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        side = teams.create_team(e, a)
        teams.join_by_team_code(side, make_user(gender=F).player)
        with pytest.raises(teams.TeamError, match="full"):
            teams.join_by_team_code(side, make_user(gender=F).player)

    def test_one_team_per_player(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        teams.create_team(e, a)
        with pytest.raises(teams.TeamError):
            teams.create_team(e, a)

    def test_team_slots_limit(self, make_event, make_user):
        e = make_event(K.SCRAMBLE)
        with pytest.raises(teams.TeamError):
            teams.create_team(e, self._joined(e, make_user, M))
        e = make_event(team_count=2, title="Two teams")
        teams.create_team(e, self._joined(e, make_user, M))
        teams.create_team(e, self._joined(e, make_user, M))
        with pytest.raises(teams.TeamError, match="team spots"):
            teams.create_team(e, self._joined(e, make_user, F))

    def test_invite_by_username_and_accept(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        partner_user = make_user("Sally", gender=F)
        side = teams.create_team(e, a)
        invite = teams.invite_by_username(side, a, "sally")  # case-insensitive
        assert invite.status == TeamInvite.Status.PENDING
        teams.accept_invite(invite, partner_user.player)
        invite.refresh_from_db()
        assert invite.status == TeamInvite.Status.ACCEPTED
        assert side.players.count() == 2

    def test_invite_checks_gender_up_front(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        make_user("bob", gender=M)
        side = teams.create_team(e, a)
        with pytest.raises(teams.TeamError):
            teams.invite_by_username(side, a, "bob")

    def test_invite_unknown_username(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        side = teams.create_team(e, a)
        with pytest.raises(teams.TeamError, match="couldn't find"):
            teams.invite_by_username(side, a, "ghost")

    def test_accepting_cancels_other_invites(self, make_event, make_user):
        e = make_event()
        a1 = self._joined(e, make_user, M)
        a2 = self._joined(e, make_user, M)
        her = make_user("her", gender=F)
        s1, s2 = teams.create_team(e, a1), teams.create_team(e, a2)
        i1 = teams.invite_by_username(s1, a1, "her")
        i2 = teams.invite_by_username(s2, a2, "her")
        teams.accept_invite(i1, her.player)
        i2.refresh_from_db()
        assert i2.status == TeamInvite.Status.CANCELLED

    def test_someone_else_cannot_accept(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        make_user("her", gender=F)
        side = teams.create_team(e, a)
        invite = teams.invite_by_username(side, a, "her")
        with pytest.raises(teams.TeamError):
            teams.accept_invite(invite, make_user(gender=F).player)

    def test_admin_build_with_override(self, make_event, make_user):
        e = make_event(K.MENS)
        a = self._joined(e, make_user, M)
        b = make_user(gender=F).player
        registration.admin_add(e, b, override=True)
        with pytest.raises(teams.TeamError):
            teams.admin_build_team(e, [a, b])
        side = teams.admin_build_team(e, [a, b], override=True)
        assert side.players.count() == 2

    def test_leave_deletes_empty_team(self, make_event, make_user):
        e = make_event()
        a = self._joined(e, make_user, M)
        side = teams.create_team(e, a)
        teams.leave_team(side, a)
        assert not e.sides.exists()


# --- Saved defaults ------------------------------------------------------

@pytest.mark.django_db
class TestDefaults:
    def test_default_location(self):
        assert OrganizationDefaults.get_solo().default_location == "Waco Regional Tennis and Fitness Center"

    def test_quick_create_uses_defaults(self, admin_user, division):
        d = OrganizationDefaults.get_solo()
        d.court_count, d.team_count, d.matches_per_team = 6, 3, 16
        d.save()
        e = defaults.quick_create(
            level=Level.objects.get(name="Advanced"), division=division(K.MIXED),
            start_date=datetime.date(2027, 3, 1), weeks=4, created_by=admin_user,
        )
        assert e.court_count == 6
        assert e.total_matches == 24
        assert e.end_date == datetime.date(2027, 3, 22)
        assert e.weekly_day == 0  # Monday
        assert e.status == Event.Status.DRAFT
        assert "Advanced Mixed" in e.title

    def test_quick_create_scramble_has_no_team_count(self, admin_user, division):
        e = defaults.quick_create(
            level=Level.objects.first(), division=division(K.SCRAMBLE),
            start_date=datetime.date(2027, 3, 1), weeks=1, created_by=admin_user,
        )
        assert e.team_count is None

    def test_remember_last_used(self, make_event):
        e = make_event(court_count=7, points_to_win=15, location="Somewhere Else")
        defaults.remember(e)
        d = OrganizationDefaults.get_solo()
        assert d.court_count == 7
        assert d.points_to_win == 15
        assert d.default_location == "Somewhere Else"

    def test_copy_event_leaves_out_dates(self, make_event):
        initial = defaults.initial_from_event(make_event(court_count=5))
        assert initial["court_count"] == 5
        assert "start_date" not in initial
        assert "(copy)" in initial["title"]
