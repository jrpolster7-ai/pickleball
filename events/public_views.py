"""Player and spectator screens (section 10): round viewer, standings, bracket.

Players sign in and must be in the event (admins can look too). Spectators
use the spectator code, no account needed, and see the read-only version.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.services import player_for
from brackets import display as bracket_display
from scheduling import display
from scheduling.models import Match
from standings import services as standings_services

from . import codes, registration
from .models import Event


def _events():
    return Event.objects.select_related("level", "division")


def has_bracket(event) -> bool:
    return not event.is_scramble and event.matches.filter(stage=Match.Stage.BRACKET).exists()


def nav(event, audience: str, active: str, code: str | None = None) -> list[dict]:
    """The tab row at the top of every player and spectator page."""
    if audience == display.SPECTATOR:
        items = [("rounds", "Rounds", reverse("events:watch", args=[code])),
                 ("standings", "Standings", reverse("events:watch_standings", args=[code]))]
        if has_bracket(event):
            items.append(("bracket", "Bracket", reverse("events:watch_bracket", args=[code])))
    else:
        items = [("mine", "My matches", reverse("events:event_detail", args=[event.pk]))]
        if event.has_schedule:
            items += [("rounds", "Rounds", reverse("events:event_rounds", args=[event.pk])),
                      ("standings", "Standings", reverse("events:event_standings", args=[event.pk]))]
        if has_bracket(event):
            items.append(("bracket", "Bracket", reverse("events:event_bracket", args=[event.pk])))
        items.append(("chat", "Chat", reverse("chat:room", args=[event.pk])))  # Never for spectators.
    return [{"key": k, "label": label, "url": url, "active": k == active} for k, label, url in items]


def _player_context(request, pk):
    """(event, player) for a signed-in player in the event, or a redirect."""
    event = get_object_or_404(_events(), pk=pk)
    player = player_for(request.user)
    if not registration.is_registered(event, player) and not request.user.is_staff:
        messages.info(request, "Enter the event's code to join it.")
        return None, None, redirect("events:join_enter")
    return event, player, None


def _spectator_event(code):
    match = codes.find_code(code)
    if not match or match.kind != codes.SPECTATOR or not match.enabled:
        return None
    return Event.objects.select_related("level", "division").get(pk=match.event.pk)


def _missing(request):
    return render(request, "events/watch_missing.html", status=404)


# --- Round viewer ----------------------------------------------------------

def _rounds(request, event, audience, *, player=None, code=None):
    panels = display.round_viewer(event, audience, player=player)
    return render(request, "events/viewer/rounds.html", {
        "event": event, "audience": audience, "code": code,
        "nav": nav(event, audience, "rounds", code),
        "panels": panels, "current": display.current_index(panels, request.GET.get("round")),
    })


@login_required
def event_rounds(request, pk):
    event, player, bounce = _player_context(request, pk)
    return bounce or _rounds(request, event, display.PLAYER, player=player)


def watch(request, code):
    event = _spectator_event(code)
    if event is None:
        return _missing(request)
    return _rounds(request, event, display.SPECTATOR, code=event.spectator_code)


# --- Standings -------------------------------------------------------------

def _standings(request, event, audience, *, code=None):
    view = "points" if request.GET.get("view") == "points" else "wins"
    table = standings_services.table(event, spectator=audience == display.SPECTATOR)
    return render(request, "events/viewer/standings.html", {
        "event": event, "audience": audience, "code": code,
        "nav": nav(event, audience, "standings", code),
        "view": view,
        "rows": table.total_points if view == "points" else table.win_loss,
        "pools": table.pool_rankings(view) if table.pools else [],
        "who": "Player" if event.is_scramble else "Team",
    })


@login_required
def event_standings(request, pk):
    event, _, bounce = _player_context(request, pk)
    return bounce or _standings(request, event, display.PLAYER)


def watch_standings(request, code):
    event = _spectator_event(code)
    if event is None:
        return _missing(request)
    return _standings(request, event, display.SPECTATOR, code=event.spectator_code)


# --- Bracket ---------------------------------------------------------------

def _bracket(request, event, audience, *, player=None, code=None):
    sections, champion, third = bracket_display.sections(event, audience, player=player)
    return render(request, "events/viewer/bracket.html", {
        "event": event, "audience": audience, "code": code,
        "nav": nav(event, audience, "bracket", code),
        "sections": sections, "champion": champion, "third": third,
    })


@login_required
def event_bracket(request, pk):
    event, player, bounce = _player_context(request, pk)
    return bounce or _bracket(request, event, display.PLAYER, player=player)


def watch_bracket(request, code):
    event = _spectator_event(code)
    if event is None:
        return _missing(request)
    return _bracket(request, event, display.SPECTATOR, code=event.spectator_code)
