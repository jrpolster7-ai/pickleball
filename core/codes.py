"""Short, easy-to-type codes (CLAUDE.md section 5).

The alphabet leaves out characters people mix up: 0/O, 1/I/L.
"""

import secrets
from collections.abc import Callable

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def random_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize(raw: str) -> str:
    """Uppercase and drop spaces and dashes, so 'abc-123' matches 'ABC123'."""
    return "".join(ch for ch in (raw or "").upper() if ch not in " -\t")


def generate_unique(length: int, in_use: Callable[[str], bool], attempts: int = 100) -> str:
    for _ in range(attempts):
        code = random_code(length)
        if not in_use(code):
            return code
    raise RuntimeError("Could not generate a unique code. Try a longer length.")
