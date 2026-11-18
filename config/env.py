"""Small helpers for reading configuration from environment variables.

Kept dependency-free on purpose (see CLAUDE.md section 15).
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ.

    Real environment variables always win over the file, so a host's
    settings are never overridden by a stray local .env.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_str(name: str, default: str = "") -> str:
    """Read a string. A blank value (e.g. `DATABASE_URL=`) counts as unset."""
    value = os.environ.get(name, "").strip()
    return value or default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_database_url(url: str, base_dir: Path) -> dict:
    """Turn a DATABASE_URL into a Django DATABASES entry.

    Supports postgres://, postgresql://, and sqlite:///path.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme == "sqlite":
        # sqlite:///db.sqlite3 -> relative to the project root
        # sqlite:////abs/path.sqlite3 -> absolute path
        name = unquote(parsed.path)
        if name.startswith("/") and not name.startswith("//"):
            name = name[1:]
        path = Path(name)
        if not path.is_absolute():
            path = base_dir / path
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(path)}

    if scheme in {"postgres", "postgresql", "pgsql"}:
        config = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
        }
        options = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        if options:
            config["OPTIONS"] = options
        return config

    raise ValueError(f"Unsupported DATABASE_URL scheme: {scheme!r}")
