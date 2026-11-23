"""Saved defaults, the "memory" feature (section 12)."""

import datetime

from . import rules
from .models import SETTING_FIELDS, Event, OrganizationDefaults


def initial_from_defaults() -> dict:
    """Starting values for a new event form."""
    d = OrganizationDefaults.get_solo()
    initial = {f: getattr(d, f) for f in SETTING_FIELDS}
    initial.update(
        location=d.default_location,
        team_count=d.team_count,
        matches_per_team=d.matches_per_team,
        total_matches=rules.total_from_per_team(d.team_count, d.matches_per_team),
        weeks=1,
    )
    return initial


def initial_from_event(event: Event) -> dict:
    """Starting values copied from an existing event. Dates and codes are left out."""
    initial = {f: getattr(event, f) for f in SETTING_FIELDS}
    initial.update(
        title=f"{event.title} (copy)",
        level=event.level_id,
        division=event.division_id,
        location=event.location,
        weeks=event.weeks,
        weekly_day=event.weekly_day,
        team_count=event.team_count,
        matches_per_team=event.matches_per_team,
        total_matches=event.total_matches,
        scramble_rounds=event.scramble_rounds,
    )
    return initial


def remember(event: Event) -> None:
    """Save this event's settings as the new defaults."""
    d = OrganizationDefaults.get_solo()
    for f in SETTING_FIELDS:
        setattr(d, f, getattr(event, f))
    if event.location:
        d.default_location = event.location
    if event.team_count:
        d.team_count = event.team_count
    if event.matches_per_team:
        d.matches_per_team = event.matches_per_team
    d.save()


def quick_create(*, level, division, start_date: datetime.date, weeks: int, created_by) -> Event:
    """Level, Division, start date, and weeks in. Everything else from defaults."""
    d = OrganizationDefaults.get_solo()
    event = Event(
        title=f"{level.name} {division.name} · {start_date:%b} {start_date.day}",
        level=level,
        division=division,
        location=d.default_location,
        start_date=start_date,
        weeks=weeks,
        end_date=rules.end_date_from_weeks(start_date, weeks),
        weekly_day=start_date.weekday(),
        created_by=created_by,
    )
    for f in SETTING_FIELDS:
        setattr(event, f, getattr(d, f))
    if not division.is_scramble:
        event.team_count = d.team_count
        event.matches_per_team = d.matches_per_team
        event.total_matches = rules.total_from_per_team(d.team_count, d.matches_per_team)
    event.full_clean(exclude=["player_code", "spectator_code"])  # save() makes the codes
    event.save()
    return event
