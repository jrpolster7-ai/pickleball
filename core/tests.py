"""Phase 0 smoke tests: settings, config parsing, and the base template."""

import os
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
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


def test_built_css_includes_app_template_classes():
    """Catches a broken @source line in assets/tailwind.css, or a forgotten rebuild.

    These classes appear only in app templates (not templates/), and the
    desktop layouts depend on the lg: breakpoint.
    """
    css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")
    for needle in [r".sr-only{", r"lg\:grid-cols-3", r"lg\:col-span-2", r"max-md\:hidden", r"page-narrow"]:
        assert needle in css, f"{needle} missing from static/css/app.css. Rebuild Tailwind."


@pytest.mark.django_db
def test_home_page_renders_with_base_template(client):
    response = client.get(reverse("core:home"))
    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="viewport"' in html
    assert "css/app.css" in html
    assert "js/htmx.min.js" in html
    assert "logo-slot" in html


# --- Phase 8: load check, first admin, error pages --------------------------



@pytest.mark.django_db
def test_load_check_runs_a_small_event_and_cleans_up():
    from io import StringIO

    from accounts.models import User
    from events.models import Event

    out = StringIO()
    call_command("load_check", players=24, stdout=out)
    text = out.getvalue()
    assert "Every page stayed under" in text, text
    assert Event.objects.filter(title__startswith="Load check").count() == 2
    assert Event.objects.get(title="Load check Mixed doubles").status == Event.Status.COMPLETE
    call_command("load_check", clean=True, stdout=StringIO())
    assert not Event.objects.filter(title__startswith="Load check").exists()
    assert not User.objects.filter(username__startswith="loadcheck-").exists()


@pytest.mark.django_db
def test_ensure_admin(monkeypatch):
    from io import StringIO

    from accounts.models import User

    monkeypatch.delenv("DJANGO_ADMIN_USERNAME", raising=False)
    call_command("ensure_admin", stdout=StringIO())
    assert not User.objects.exists()

    monkeypatch.setenv("DJANGO_ADMIN_USERNAME", "rachel")
    monkeypatch.setenv("DJANGO_ADMIN_PASSWORD", "short")
    with pytest.raises(CommandError, match="too weak"):
        call_command("ensure_admin", stdout=StringIO())

    monkeypatch.setenv("DJANGO_ADMIN_PASSWORD", "serve-and-volley-2027")
    call_command("ensure_admin", stdout=StringIO())
    admin = User.objects.get(username="rachel")
    assert admin.is_staff and admin.check_password("serve-and-volley-2027")
    assert admin.player

    monkeypatch.setenv("DJANGO_ADMIN_PASSWORD", "a-different-password-99")
    call_command("ensure_admin", stdout=StringIO())
    admin.refresh_from_db()
    assert admin.check_password("serve-and-volley-2027"), "never changes an existing admin"
    assert os.environ["DJANGO_ADMIN_USERNAME"] == "rachel"


@pytest.mark.django_db
def test_friendly_404(client):
    response = client.get("/no-such-page/")
    assert response.status_code == 404
    assert b"We couldn't find that page." in response.content


@pytest.mark.django_db
def test_skip_link_and_favicon(client):
    html = client.get("/").content.decode()
    assert 'href="#main"' in html and 'id="main"' in html
    assert "favicon.svg" in html


def test_no_template_comment_spans_lines():
    """Django's {# #} comments are one line only. A longer one shows up on the page as text."""
    import re

    root = Path(settings.BASE_DIR)
    bad = []
    for path in root.rglob("*.html"):
        if any(part in {"pvenv", "staticfiles", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\{#.*?#\}|\{#", text, re.S):
            if "\n" in m.group(0) or m.group(0) == "{#":
                bad.append(f"{path.relative_to(root)}:{text[:m.start()].count(chr(10)) + 1}")
    assert not bad, "Use {% comment %} for multi-line comments: " + ", ".join(bad)


def test_row_locks_only_lock_their_own_table():
    """PostgreSQL refuses FOR UPDATE across a LEFT JOIN (nullable foreign keys like a bracket
    match's empty side). SQLite ignores locks, so tests can't catch it. Always pass of=("self",)."""
    import subprocess

    root = Path(settings.BASE_DIR)
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=root, capture_output=True, text=True).stdout.split()
    code = [f for f in files if "test" not in Path(f).name and f != "conftest.py"]
    bad = [f for f in code if ".select_for_update()" in (root / f).read_text(encoding="utf-8")]
    assert not bad, f"Use select_for_update(of=(\"self\",)) in: {bad}"


def test_score_lock_sql_is_valid_for_postgresql():
    from django.db.backends.postgresql.base import DatabaseWrapper

    from scheduling.models import Match

    pg = DatabaseWrapper({
        "ENGINE": "django.db.backends.postgresql", "NAME": "x", "USER": "", "PASSWORD": "", "HOST": "", "PORT": "",
        "OPTIONS": {}, "TIME_ZONE": None, "CONN_MAX_AGE": 0, "CONN_HEALTH_CHECKS": False, "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False, "TEST": {},
    })
    pg.get_autocommit = lambda: False  # Pretend we're inside a transaction; nothing connects.
    qs = Match.objects.select_for_update(of=("self",)).select_related("event", "side_a", "side_b", "round")
    sql = qs.filter(pk=1).query.get_compiler(connection=pg).as_sql()[0]
    assert sql.endswith('FOR UPDATE OF "scheduling_match"')
