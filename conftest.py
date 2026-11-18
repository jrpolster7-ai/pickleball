"""Shared test fixtures."""

import datetime
import itertools

import pytest

from accounts.models import Gender, Player, User
from events.models import Division, Event, Level

_seq = itertools.count(1)


@pytest.fixture
def make_user(db):
    def _make(username=None, *, gender=Gender.MALE, staff=False, password="pickle-pass-123", **kw):
        username = username or f"user{next(_seq)}"
        user = User.objects.create_user(
            username=username, password=password, first_name=kw.pop("first_name", username.title()),
            last_name=kw.pop("last_name", "Tester"), gender=gender, is_staff=staff, **kw,
        )
        Player.objects.create(user=user, first_name=user.first_name, last_name=user.last_name, gender=gender)
        return user
    return _make


@pytest.fixture
def admin_user(make_user):
    return make_user("boss", staff=True)


@pytest.fixture
def division(db):
    def _get(kind):
        return Division.objects.get(kind=kind)
    return _get


@pytest.fixture
def make_event(db, division):
    def _make(kind=Division.Kind.MIXED, *, status=Event.Status.OPEN, **kw):
        defaults = dict(
            title="Test event",
            level=Level.objects.get(name="Beginner"),
            division=division(kind),
            location="Waco Regional Tennis and Fitness Center",
            start_date=datetime.date(2027, 3, 1),
            end_date=datetime.date(2027, 3, 1),
            team_count=4,
            matches_per_team=3,
            total_matches=6,
            status=status,
        )
        defaults.update(kw)
        return Event.objects.create(**defaults)
    return _make
