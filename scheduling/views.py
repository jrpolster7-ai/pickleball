from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import admin_required
from events.models import Event

from . import services
from .engine import ScheduleError
from .forms import MatchEditForm, RoundTimeForm
from .models import Match, Round


def _event(pk):
    return get_object_or_404(Event.objects.select_related("level", "division"), pk=pk)


def _round_anchor(pk, round_pk) -> str:
    return f"{reverse('scheduling:schedule', args=[pk])}#round-{round_pk}"


def _seed(value, fallback=1) -> int:
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return fallback
    return seed if 0 < seed < 10**9 else fallback


@admin_required
def schedule(request, pk):
    """Preview before publishing, or the saved schedule with edit controls."""
    event = _event(pk)
    if event.has_schedule:
        sessions = list(services.saved_rounds(event))
        for session in sessions:
            for rnd in session.rounds.all():
                rnd.time_form = RoundTimeForm(initial={"start_time": timezone.localtime(rnd.start_time).time()},
                                              auto_id=f"r{rnd.pk}_%s")
                for match in rnd.matches.all():
                    match.edit_form = MatchEditForm(
                        initial={"start_time": timezone.localtime(match.start_time).time(), "court": match.court},
                        auto_id=f"m{match.pk}_%s",
                    )
        counts = services.saved_counts(event)
        disputed = [m for s in sessions for r in s.rounds.all() for m in r.matches.all()
                    if m.status == Match.Status.DISPUTED]
        return render(request, "scheduling/schedule_saved.html", {
            "event": event,
            "sessions": sessions,
            "disputed": disputed,
            "counts": counts,
            "multi_pool": any(c.pool for c in counts),
        })

    seed = _seed(request.GET.get("seed"))
    try:
        preview = services.build_preview(event, seed)
    except ScheduleError as exc:
        return render(request, "scheduling/schedule_preview.html", {"event": event, "problem": str(exc)})
    return render(request, "scheduling/schedule_preview.html", {
        "event": event,
        "preview": preview,
        "multi_pool": preview.pool_count > 1,
        "next_seed": seed + 1,
    })


@admin_required
@require_POST
def publish(request, pk):
    event = _event(pk)
    seed = _seed(request.POST.get("seed"))
    try:
        preview = services.publish(event, seed, actor=request.user)
    except ScheduleError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Schedule published: {preview.total_matches} matches.")
    return redirect("scheduling:schedule", pk=pk)


@admin_required
@require_POST
def clear(request, pk):
    event = _event(pk)
    try:
        services.clear(event, actor=request.user)
    except ScheduleError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Schedule cleared. Make a new one whenever you're ready.")
    return redirect("scheduling:schedule", pk=pk)


@admin_required
@require_POST
def start_play(request, pk):
    event = _event(pk)
    try:
        services.start_play(event, actor=request.user)
    except ScheduleError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Play has started. The round robin is on!")
    return redirect("scheduling:schedule", pk=pk)


@admin_required
@require_POST
def retime(request, pk):
    event = _event(pk)
    services.retime(event, actor=request.user)
    messages.success(request, "Start times recalculated from the event settings.")
    return redirect("scheduling:schedule", pk=pk)


@admin_required
@require_POST
def round_time(request, pk, round_pk):
    rnd = get_object_or_404(Round.objects.select_related("session", "event"), pk=round_pk, event_id=pk)
    form = RoundTimeForm(request.POST)
    if form.is_valid():
        services.set_round_time(rnd, form.cleaned_data["start_time"], actor=request.user)
        messages.success(request, f"Round {rnd.number} moved. Its matches moved with it.")
    else:
        messages.error(request, "Enter a start time.")
    return redirect(_round_anchor(pk, rnd.pk))


@admin_required
@require_POST
def match_edit(request, pk, match_pk):
    match = get_object_or_404(Match.objects.select_related("round__session", "event"), pk=match_pk, event_id=pk)
    form = MatchEditForm(request.POST)
    if form.is_valid():
        try:
            services.edit_match(match, actor=request.user, **form.cleaned_data)
        except ScheduleError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Match updated.")
    else:
        messages.error(request, "Enter a start time and a court from 1 to 8.")
    return redirect(_round_anchor(pk, match.round_id))
