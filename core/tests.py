"""Phase 0 smoke tests: settings, config parsing, and the base template."""

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from config.env import env_str, parse_database_url


def test_time_zone_is_central():
    assert settings.TIME_ZONE == "America/Chicago"
    assert settings.USE_TZ is True


def test_custom_user_model_in_use():
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model()._meta.label == "accounts.User"


def test_long_lived_sessions():
    assert settings.SESSION_COOKIE_AGE >= 60 * 60 * 24 * 365


def test_sqlite_url_is_relative_to_project():
    base = Path("/project")
    db = parse_database_url("sqlite:///db.sqlite3", base)
    assert db["ENGINE"] == "django.db.backends.sqlite3"
    assert Path(db["NAME"]) == base / "db.sqlite3"


def test_postgres_url_is_parsed():
    db = parse_database_url(
        "postgres://joe:s%40cret@db.example.com:5433/pickle?sslmode=require",
        Path("/project"),
    )
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["NAME"] == "pickle"
    assert db["USER"] == "joe"
    assert db["PASSWORD"] == "s@cret"
    assert db["HOST"] == "db.example.com"
    assert db["PORT"] == "5433"
    assert db["OPTIONS"] == {"sslmode": "require"}


def test_blank_env_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SOME_SETTING", "   ")
    assert env_str("SOME_SETTING", default="fallback") == "fallback"
    monkeypatch.setenv("SOME_SETTING", "real")
    assert env_str("SOME_SETTING", default="fallback") == "real"


def test_unknown_database_scheme_is_rejected():
    with pytest.raises(ValueError):
        parse_database_url("mysql://x@y/z", Path("/project"))


@pytest.mark.django_db
def test_home_page_renders_with_base_template(client):
    response = client.get(reverse("core:home"))
    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="viewport"' in html
    assert "css/app.css" in html
    assert "js/htmx.min.js" in html
    assert "logo-slot" in html
