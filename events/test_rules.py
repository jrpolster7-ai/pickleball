import datetime

import pytest

from core.codes import ALPHABET, normalize, random_code
from events import rules


class TestMatchCounts:
    def test_spec_example_per_team_to_total(self):
        # CLAUDE.md section 4: 3 teams at 16 matches per team is 24 total.
        assert rules.total_from_per_team(3, 16) == 24

    def test_spec_example_total_to_per_team(self):
        assert rules.per_team_from_total(3, 24) == 16

    def test_no_cap_from_team_count(self):
        # 16 per team is allowed even though a full round robin is only 2.
        assert rules.full_round_robin(3) == (2, 3)
        assert rules.total_from_per_team(3, 16) == 24

    @pytest.mark.parametrize("teams", [2, 3, 4, 5, 7, 8, 16, 250])
    def test_full_round_robin(self, teams):
        per, total = rules.full_round_robin(teams)
        assert per == teams - 1
        assert total == teams * (teams - 1) // 2
        assert rules.total_from_per_team(teams, per) == total

    def test_odd_slots_round_up_so_everyone_gets_their_matches(self):
        # 3 teams, 1 match each is 1.5 matches. Round up to 2; one team plays twice.
        assert rules.total_from_per_team(3, 1) == 2
        assert rules.per_team_range(3, 2) == (1, 2)

    @pytest.mark.parametrize("teams,total", [(3, 5), (5, 7), (7, 10), (8, 13), (6, 1)])
    def test_uneven_totals_differ_by_at_most_one(self, teams, total):
        low, high = rules.per_team_range(teams, total)
        assert high - low <= 1
        # The slots add up: low*teams <= 2*total <= high*teams
        assert low * teams <= 2 * total <= high * teams

    def test_even_split(self):
        assert rules.per_team_range(4, 6) == (3, 3)

    @pytest.mark.parametrize("teams,per", [(3, 16), (4, 3), (5, 4), (6, 7), (9, 2)])
    def test_round_trip(self, teams, per):
        total = rules.total_from_per_team(teams, per)
        assert rules.per_team_from_total(teams, total) == per


class TestDates:
    def test_one_week_is_one_day(self):
        d = datetime.date(2027, 3, 1)
        assert rules.end_date_from_weeks(d, 1) == d

    def test_four_week_league(self):
        d = datetime.date(2027, 3, 1)  # a Monday
        assert rules.end_date_from_weeks(d, 4) == datetime.date(2027, 3, 22)
        assert rules.weeks_from_end_date(d, datetime.date(2027, 3, 22)) == 4

    def test_partial_week_counts_as_started_week(self):
        d = datetime.date(2027, 3, 1)
        assert rules.weeks_from_end_date(d, datetime.date(2027, 3, 3)) == 1
        assert rules.weeks_from_end_date(d, datetime.date(2027, 3, 8)) == 2

    def test_end_before_start_is_rejected(self):
        with pytest.raises(ValueError):
            rules.weeks_from_end_date(datetime.date(2027, 3, 8), datetime.date(2027, 3, 1))


class TestCodeHelpers:
    def test_no_confusing_characters(self):
        for ch in "0O1IL":
            assert ch not in ALPHABET

    def test_random_code_uses_alphabet(self):
        code = random_code(6)
        assert len(code) == 6
        assert set(code) <= set(ALPHABET)

    def test_normalize(self):
        assert normalize(" abc-12 3 ") == "ABC123"
