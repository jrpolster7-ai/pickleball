"""Player, spectator, and team codes share one namespace.

One join box on the site accepts any of them. The kind of code decides
whether the person sees the player view, the spectator view, or joins a team.
"""

from dataclasses import dataclass

from core.codes import generate_unique, normalize

CODE_LENGTH = 6

PLAYER = "player"
SPECTATOR = "spectator"
TEAM = "team"


@dataclass
class CodeMatch:
    kind: str
    event: "Event"  # noqa: F821
    enabled: bool
    side: "Side | None" = None  # noqa: F821


def code_in_use(code: str) -> bool:
    from .models import Event, Side

    return (
        Event.objects.filter(player_code=code).exists()
        or Event.objects.filter(spectator_code=code).exists()
        or Side.objects.filter(team_code=code).exists()
    )


def new_code() -> str:
    return generate_unique(CODE_LENGTH, code_in_use)


def find_code(raw: str) -> CodeMatch | None:
    from .models import Event, Side

    code = normalize(raw)
    if not code:
        return None

    event = Event.objects.select_related("level", "division").filter(player_code=code).first()
    if event:
        return CodeMatch(PLAYER, event, event.player_code_enabled)

    event = Event.objects.select_related("level", "division").filter(spectator_code=code).first()
    if event:
        return CodeMatch(SPECTATOR, event, event.spectator_code_enabled)

    side = Side.objects.select_related("event__level", "event__division").filter(team_code=code).first()
    if side:
        # A team code only works while the event's player code is on.
        return CodeMatch(TEAM, side.event, side.event.player_code_enabled, side=side)

    return None


def rotate_code(event, kind: str) -> str:
    """Give the event a fresh code. The old one stops working right away."""
    if kind == PLAYER:
        event.player_code = new_code()
        event.save(update_fields=["player_code", "updated_at"])
        return event.player_code
    if kind == SPECTATOR:
        event.spectator_code = new_code()
        event.save(update_fields=["spectator_code", "updated_at"])
        return event.spectator_code
    raise ValueError(f"Unknown code kind: {kind}")


def set_code_enabled(event, kind: str, enabled: bool) -> None:
    field = {PLAYER: "player_code_enabled", SPECTATOR: "spectator_code_enabled"}.get(kind)
    if not field:
        raise ValueError(f"Unknown code kind: {kind}")
    setattr(event, field, enabled)
    event.save(update_fields=[field, "updated_at"])
