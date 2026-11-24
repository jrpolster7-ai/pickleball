"""What each audience sees of the bracket (section 10). See scheduling/display.py for audiences.

Spectators see a result only once its time slot (round) is fully final. That
includes the team names that moved on from it, so nothing leaks early.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from django.urls import reverse

from scheduling.display import ADMIN, PLAYER, SPECTATOR, has_player, revealed_round_ids, side_name
from scheduling.models import Match

from . import services
from .brackets import FINAL


@dataclass
class Cell:
    """One match box in the bracket picture."""

    label_a: str
    label_b: str
    seed_a: int | None = None
    seed_b: int | None = None
    winner: str = ""
    footer: str = ""
    link: str = ""
    mine: bool = False
    alert: bool = False


def _matches(event):
    return list(
        event.matches.filter(stage=Match.Stage.BRACKET)
        .select_related("side_a", "side_b", "round")
        .prefetch_related("side_a__players", "side_b__players", "games")
    )


def sections(event, audience: str, *, player=None):
    """[(section name, [(round name, [Cell])])], plus the champion and third place to show."""
    matches = _matches(event)
    if not matches:
        return [], None, None
    revealed = revealed_round_ids(event) if audience == SPECTATOR else None
    by_id = {m.pk: m for m in matches}

    def shown(match) -> bool:
        return revealed is None or match.round_id in revealed

    # Where each side came from, so a spectator doesn't see who won before the round is final.
    source: dict[tuple[int, str], Match] = {}
    grand_final = None
    for m in matches:
        if m.winner_to_id:
            source[(m.winner_to_id, m.winner_to_side)] = m
        if m.loser_to_id:
            source[(m.loser_to_id, m.loser_to_side)] = m
        if m.bracket_side == FINAL and m.bracket_round == 1:
            grand_final = m
    for m in matches:
        if m.bracket_side == FINAL and m.bracket_round == 2 and grand_final:
            source[(m.pk, "A")] = source[(m.pk, "B")] = grand_final

    def label(match, letter):
        side = match.side_a if letter == "A" else match.side_b
        feed = (match.feed_a if letter == "A" else match.feed_b) or "To be decided"
        origin = source.get((match.pk, letter))
        if side is None or (origin is not None and not shown(origin)):
            return feed
        return side_name(side, audience)

    def cell(match) -> Cell:
        visible = shown(match)
        c = Cell(label_a=label(match, "A"), label_b=label(match, "B"),
                 mine=has_player(match.side_a, player) or has_player(match.side_b, player))
        if match.is_final and visible:
            c.winner = match.winner
            c.footer = match.score + (" (forfeit)" if match.forfeit else "")
        elif audience == ADMIN and match.status == Match.Status.DISPUTED:
            c.footer, c.alert = "Disputed", True
        elif audience == SPECTATOR and match.status != Match.Status.SCHEDULED:
            c.footer = "Result soon"  # played, but its round isn't final yet
        elif match.is_ready:
            c.footer = f"Court {match.court} · {_clock(match.start_time)}"
        if audience == ADMIN:
            c.link = reverse("scoring:admin_match", args=[event.pk, match.pk])
        elif audience == PLAYER and c.mine:
            c.link = reverse("scoring:match_score", args=[match.pk])
        return c

    order = {"WINNERS": 0, "LOSERS": 1, FINAL: 2}
    names = {"WINNERS": "Winners bracket", "LOSERS": "Losers bracket", FINAL: "Grand final"}
    double = any(m.bracket_side in ("LOSERS", FINAL) for m in matches)
    matches.sort(key=lambda m: (order.get(m.bracket_side, 0), m.bracket_round, m.third_place, m.bracket_slot))
    out = []
    for side, side_matches in groupby(matches, key=lambda m: m.bracket_side):
        rounds = [(round_label, [cell(m) for m in ms]) for (_, _, round_label), ms in
                  groupby(side_matches, key=lambda m: (m.bracket_round, m.third_place, m.bracket_label))]
        out.append((names.get(side, "") if double else "", rounds))

    deciding = services.deciding_match(event)
    champion = services.champion(event)
    third = services.third_place(event)
    if audience == SPECTATOR:
        if champion and not (deciding and shown(by_id[deciding.pk])):
            champion = None
        if third and not _third_shown(event, shown, by_id):
            third = None
    names_for = (lambda s: s.public_name) if audience == SPECTATOR else (lambda s: s.name)
    return out, (names_for(champion) if champion else None), (names_for(third) if third else None)


def _third_shown(event, shown, by_id) -> bool:
    deciding = (event.matches.filter(stage=Match.Stage.BRACKET, third_place=True).first()
                or event.matches.filter(stage=Match.Stage.BRACKET, bracket_side="LOSERS")
                .order_by("-bracket_round").first())
    return bool(deciding and shown(by_id[deciding.pk]))


def _clock(dt) -> str:
    from django.utils import timezone

    return timezone.localtime(dt).strftime("%I:%M %p").lstrip("0")
