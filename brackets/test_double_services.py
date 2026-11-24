"""Double elimination in the database: build, play out, grand final reset, third place."""

import pytest
from django.urls import reverse

from brackets import services
from brackets.test_services import league, play_round_robin  # noqa: F401  (fixture and helper)
from events.models import BracketSizing, BracketType, Event
from scheduling.models import Match
from scoring import services as scoring
from scoring.services import ScoreError

pytestmark = pytest.mark.django_db


def win(match, letter, admin):
    match = Match.objects.get(pk=match.pk)
    scoring.admin_set_score(match, [(11, 4)] if letter == "A" else [(4, 11)], admin)


def ready_matches(event):
    """Unplayed bracket matches with both teams known, in time order."""
    return list(event.matches.filter(stage=Match.Stage.BRACKET, status=Match.Status.SCHEDULED,
                                     side_a__isnull=False, side_b__isnull=False)
                .order_by("start_time", "court"))


def play_out(event, admin, pick=lambda m: "A", include_reset=False):
    """Score every match as it becomes ready until nothing is left. The reset waits unless asked."""
    for _ in range(200):
        ready = [m for m in ready_matches(event) if include_reset or m.bracket_label != "Grand final reset"]
        if not ready:
            return
        for m in ready:
            win(m, pick(m), admin)
    raise AssertionError("bracket never finished")


def by_label(event, label):
    return Match.objects.get(event=event, stage=Match.Stage.BRACKET, bracket_label=label)


@pytest.fixture
def double(league, admin_user):  # noqa: F811
    def _make(n=4, count=None, **kw):
        event = league(n, bracket_type=BracketType.DOUBLE, **kw)
        play_round_robin(event, admin_user)
        services.build(event, count or n, admin_user)
        event.refresh_from_db()
        return event
    return _make


def test_four_team_double_elimination_is_built(double):
    event = double(4)
    matches = event.matches.filter(stage=Match.Stage.BRACKET)
    assert matches.count() == 6  # 2n - 2, no reset yet
    assert set(matches.values_list("bracket_side", flat=True)) == {"WINNERS", "LOSERS", "FINAL"}
    assert event.status == Event.Status.BRACKET
    losers_final = by_label(event, "Losers final")
    assert losers_final.feed_b == "Loser of the winners final"


def test_winners_champion_wins_the_grand_final(double, admin_user):
    event = double(4)
    play_out(event, admin_user, pick=lambda m: "A")
    event.refresh_from_db()
    assert event.status == Event.Status.COMPLETE
    assert not Match.objects.filter(event=event, bracket_label="Grand final reset").exists()
    grand_final = by_label(event, "Grand final")
    assert services.champion(event) == grand_final.side_a
    losers_final = by_label(event, "Losers final")
    assert services.third_place(event) == losers_final.losing_side


def test_losers_champion_forces_a_reset(double, admin_user):
    event = double(4)
    play_out(event, admin_user, pick=lambda m: "B" if m.bracket_label == "Grand final" else "A")
    reset = by_label(event, "Grand final reset")
    grand_final = by_label(event, "Grand final")
    assert reset.side_a_id == grand_final.side_a_id and reset.side_b_id == grand_final.side_b_id
    assert reset.round.label == "Grand final reset"
    assert reset.start_time > grand_final.start_time
    event.refresh_from_db()
    assert event.status == Event.Status.BRACKET, "the reset still has to be played"
    assert services.champion(event) is None

    win(reset, "B", admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.COMPLETE
    assert services.champion(event) == grand_final.side_b


def test_correcting_the_grand_final_removes_an_unplayed_reset(double, admin_user):
    event = double(4)
    play_out(event, admin_user, pick=lambda m: "B" if m.bracket_label == "Grand final" else "A")
    reset = by_label(event, "Grand final reset")
    reset_round = reset.round_id
    win(by_label(event, "Grand final"), "A", admin_user)  # it was really side A
    assert not Match.objects.filter(pk=reset.pk).exists()
    assert not event.rounds.filter(pk=reset_round).exists()
    event.refresh_from_db()
    assert event.status == Event.Status.COMPLETE


def test_a_played_reset_blocks_changing_the_grand_final(double, admin_user):
    event = double(4)
    play_out(event, admin_user, pick=lambda m: "B" if m.bracket_label == "Grand final" else "A")
    play_out(event, admin_user, include_reset=True)  # plays the reset
    with pytest.raises(ScoreError, match="reset already has a score"):
        win(by_label(event, "Grand final"), "A", admin_user)
    with pytest.raises(ScoreError):
        scoring.admin_clear_score(by_label(event, "Grand final"), admin_user)
    assert Match.objects.filter(event=event, bracket_label="Grand final reset").exists()


@pytest.mark.parametrize("n,count", [(5, 5), (6, 6), (8, 8), (10, 10), (7, 6)])
def test_several_sizes_play_out_and_everyone_gets_two_losses(double, admin_user, n, count):
    event = double(n, count=count, court_count=4,
                   bracket_sizing=BracketSizing.PLAY_IN if n % 2 else BracketSizing.BYES)
    assert event.matches.filter(stage=Match.Stage.BRACKET).count() == 2 * count - 2
    play_out(event, admin_user, pick=lambda m: "B" if m.bracket_slot % 2 == 0 else "A", include_reset=True)
    event.refresh_from_db()
    assert event.status == Event.Status.COMPLETE
    losses = {}
    for m in event.matches.filter(stage=Match.Stage.BRACKET).select_related("side_a", "side_b"):
        losses[m.losing_side.pk] = losses.get(m.losing_side.pk, 0) + 1
    champion = services.champion(event)
    assert losses.get(champion.pk, 0) <= 1
    assert sorted(v for k, v in losses.items() if k != champion.pk) == [2] * (count - 1)


def test_opening_losers_play_on_in_the_losers_bracket(double, admin_user):
    event = double(6, bracket_sizing=BracketSizing.PLAY_IN)
    opening = list(event.matches.filter(stage=Match.Stage.BRACKET, bracket_label="Play-in"))
    assert len(opening) == 2
    win(opening[0], "A", admin_user)
    loser = opening[0].side_b_id
    assert Match.objects.filter(event=event, bracket_side="LOSERS").filter(side_a_id=loser).exists() \
        or Match.objects.filter(event=event, bracket_side="LOSERS").filter(side_b_id=loser).exists()


def test_rounds_share_time_slots_without_double_booking(double):
    event = double(8, court_count=8)
    for rnd in event.rounds.exclude(label=""):
        sides = [s for m in rnd.matches.all() for s in (m.side_a_id, m.side_b_id) if s]
        assert len(sides) == len(set(sides))
        assert rnd.matches.count() <= 8
    labels = list(event.rounds.exclude(label="").order_by("number").values_list("label", flat=True))
    assert labels[0] == "Winners round 1"
    assert "Winners round 2 and losers round 1" in labels


def test_delete_double_bracket(double, admin_user):
    event = double(4)
    services.delete(event, admin_user)
    event.refresh_from_db()
    assert event.status == Event.Status.ROUND_ROBIN
    assert not event.matches.filter(stage=Match.Stage.BRACKET).exists()


def test_bracket_page_shows_both_brackets(client, admin_user, double):
    event = double(4)
    client.force_login(admin_user)
    page = client.get(reverse("brackets:bracket", args=[event.pk]))
    assert page.status_code == 200
    for text in (b"Winners bracket", b"Losers bracket", b"Grand final", b"Lose twice"):
        assert text in page.content


def test_double_preview_page(client, admin_user, league):  # noqa: F811
    event = league(6, bracket_type=BracketType.DOUBLE)
    play_round_robin(event, admin_user)
    client.force_login(admin_user)
    page = client.get(reverse("brackets:bracket", args=[event.pk]) + "?count=6")
    assert page.status_code == 200
    assert b"Losers bracket" in page.content and b"drop to the losers bracket" in page.content
