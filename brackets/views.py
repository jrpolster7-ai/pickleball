from dataclasses import dataclass
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.decorators import admin_required
from events.models import Event
from standings import services as standings_services

from . import services
from .brackets import BracketError, Feed, feed_label
from .forms import AdvanceForm


@dataclass
class PreviewMatch:
    """A bracket match before it exists, for the preview."""

    label_a: str
    label_b: str
    seed_a: int | None = None
    seed_b: int | None = None


def _bracket_url(pk, count=None) -> str:
    url = reverse("brackets:bracket", args=[pk])
    return f"{url}?{urlencode({'count': count})}" if count else url


def _event(pk):
    return get_object_or_404(Event.objects.select_related("level", "division"), pk=pk)


def _preview(event, count, seeding):
    """The bracket this count would make, with team names in the seeded spots."""
    plan = services.plan_for(event, count)
    names = {i + 1: row.extra["label"] for i, row in enumerate(seeding.order[:count])}

    def label(feed: Feed):
        return names[feed.value] if feed.kind == "seed" else feed_label(feed, plan)

    def seed(feed: Feed):
        return feed.value if feed.kind == "seed" else None

    return [(section, [(name, [PreviewMatch(label(m.a), label(m.b), seed(m.a), seed(m.b)) for m in ms])
                       for name, ms in rounds])
            for section, rounds in plan.sections()]


@admin_required
def bracket(request, pk):
    event = _event(pk)
    if event.is_scramble:
        return render(request, "brackets/bracket.html", {"event": event, "scramble": True})

    sections = services.bracket_sections(event)
    if sections:
        matches = [m for _, rounds in sections for _, ms in rounds for m in ms]
        return render(request, "brackets/bracket.html", {
            "event": event,
            "sections": sections,
            "champion": services.champion(event),
            "third": services.third_place(event),
            "can_delete": not any(m.status != "SCHEDULED" for m in matches),
        })

    table = standings_services.table(event)
    seeding = table.seeding()
    team_count = len(table.rows)
    default = event.advancing_count or min(8, team_count)
    form = AdvanceForm(request.GET or None, team_count=team_count, initial={"count": default})
    count = form.cleaned_data["count"] if form.is_valid() else default
    problem = services.build_problem(event, count, table)
    try:
        preview = _preview(event, count, seeding) if count >= 2 else []
    except BracketError:
        preview = []
    position = {row.key: i for i, row in enumerate(seeding.order)}
    return render(request, "brackets/bracket.html", {
        "event": event,
        "seeding": seeding,
        "count": count,
        "form": form,
        "problem": problem,
        "preview": preview,
        "remaining": table.remaining,
        "ties": [(g, g in seeding.unresolved, min(position[r.key] for r in g) < count) for g in seeding.ties],
    })


@admin_required
@require_POST
def build(request, pk):
    event = _event(pk)
    table = standings_services.table(event)
    form = AdvanceForm(request.POST, team_count=len(table.rows))
    if not form.is_valid():
        messages.error(request, "Enter how many teams advance, from 2 up to the number of teams.")
        return redirect("brackets:bracket", pk=pk)
    data = form.cleaned_data
    try:
        services.build(event, data["count"], request.user, date=data["date"], start=data["start_time"])
    except BracketError as exc:
        messages.error(request, str(exc))
        return redirect(_bracket_url(pk, data["count"]))
    messages.success(request, "Bracket built. Good luck to everyone!")
    return redirect("brackets:bracket", pk=pk)


@admin_required
@require_POST
def tiebreak(request, pk):
    """The admin orders a group of tied teams. Inputs are named order_<side id>."""
    event = _event(pk)
    picks = {}
    for name, value in request.POST.items():
        if name.startswith("order_"):
            try:
                picks[int(name[6:])] = int(value)
            except ValueError:
                pass
    ordered = [side_id for side_id, _ in sorted(picks.items(), key=lambda kv: kv[1])]
    if len(set(picks.values())) != len(picks) or len(picks) < 2:
        messages.error(request, "Give each tied team a different place.")
    else:
        try:
            services.set_tiebreak(event, ordered, request.user)
        except BracketError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Tie decided.")
    return redirect(_bracket_url(pk, request.POST.get("count")))


@admin_required
@require_POST
def delete(request, pk):
    event = _event(pk)
    try:
        services.delete(event, request.user)
    except BracketError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Bracket removed. You can build a new one.")
    return redirect("brackets:bracket", pk=pk)
