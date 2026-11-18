"""Pure math for event settings. No database access, easy to test.

Matches per team and total matches are two views of one setting (section 4).
Each match uses two team slots, so total = teams * per_team / 2.
"""

import datetime
import math


def full_round_robin(team_count: int) -> tuple[int, int]:
    """(matches per team, total matches) for everyone playing everyone once.

    Shown to the admin as a hint, never used as a limit.
    """
    if team_count < 2:
        return (0, 0)
    return (team_count - 1, team_count * (team_count - 1) // 2)


def total_from_per_team(team_count: int, per_team: int) -> int:
    """Total matches so every team gets at least `per_team` matches.

    ASSUMED: when teams * per_team is odd, round up. One team plays one extra.
    """
    return math.ceil(team_count * per_team / 2)


def per_team_range(team_count: int, total: int) -> tuple[int, int]:
    """(fewest, most) matches any team plays when `total` is spread evenly.

    ASSUMED (section 4): no team differs from another by more than one match.
    """
    if team_count < 1:
        return (0, 0)
    slots = 2 * total
    low = slots // team_count
    high = low + (1 if slots % team_count else 0)
    return (low, high)


def per_team_from_total(team_count: int, total: int) -> int:
    return per_team_range(team_count, total)[0]


def end_date_from_weeks(start: datetime.date, weeks: int) -> datetime.date:
    """Week 1 is the start date. A 4-week league ends 3 weeks later."""
    return start + datetime.timedelta(weeks=weeks - 1)


def weeks_from_end_date(start: datetime.date, end: datetime.date) -> int:
    if end < start:
        raise ValueError("The end date is before the start date.")
    return (end - start).days // 7 + 1
