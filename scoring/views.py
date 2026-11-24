from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.services import player_for
from core.decorators import admin_required
from core.models import AuditLog
from events.models import Event, Side
from scheduling.models import Match

from . import services
from .forms import ForfeitForm, ScoreForm
from .models import ScoreSubmission
from .services import ScoreError


def _matches():
    return Match.objects.select_related(
        "event__division", "event__level", "round__session", "side_a", "side_b"
    ).prefetch_related("side_a__players", "side_b__players", "games", "submissions__submitted_by")


def _current_games(match):
    return [(g.side_a_points, g.side_b_points) for g in match.games.all()]


def _starting_games(match, view):
    """What the score boxes start with: the entry being checked, then your own, then the final score."""
    if view.waiting:
        return view.waiting.game_list
    if view.mine:
        return view.mine.game_list
    return _current_games(match)


# --- Players ---------------------------------------------------------------

@login_required
def match_score(request, match_pk):
    match = get_object_or_404(_matches(), pk=match_pk)
    player = player_for(request.user)
    view = services.player_view(match, player)
    if view.side is None and not request.user.is_staff:
        raise Http404

    # Confirming also offers the score boxes, so a player can correct a wrong entry.
    form = None
    is_entry = request.method == "POST" and request.POST.get("action") not in ("confirm", "ask")
    if view.action in ("enter", "change", "confirm"):
        form = ScoreForm(request.POST if is_entry else None, match=match,
                         initial=ScoreForm.initial_for(_starting_games(match, view)))

    if request.method == "POST":
        try:
            if request.POST.get("action") == "ask":
                services.ask_organizer(match, player)
                messages.success(request, "An organizer has been asked to decide this score.")
                return redirect("events:event_detail", pk=match.event_id)
            if request.POST.get("action") == "confirm":
                submission = get_object_or_404(ScoreSubmission, pk=request.POST.get("submission"), match=match)
                services.confirm(submission, player)
                messages.success(request, "Score confirmed. Thanks!")
                return redirect("events:event_detail", pk=match.event_id)
            if form is None:
                raise ScoreError(view.label)
            if form.is_valid():
                saved = services.submit(match, player, form.cleaned_data["games"])
                if saved.status == ScoreSubmission.Status.CONFIRMED:
                    messages.success(request, "Both sides agree. The score is final.")
                elif saved.status == ScoreSubmission.Status.DISPUTED:
                    messages.warning(request, "Score saved. An organizer is deciding this one.")
                else:
                    messages.success(request, "Score saved. Your opponent will be asked to confirm it.")
                return redirect("events:event_detail", pk=match.event_id)
        except ScoreError as exc:
            messages.error(request, str(exc))
            return redirect("scoring:match_score", match_pk=match.pk)

    return render(request, "scoring/match_score.html", {
        "match": match,
        "event": match.event,
        "view": view,
        "form": form,
        "match_day": services.match_day(match),
    })


# --- Admins ----------------------------------------------------------------

@admin_required
def admin_match(request, pk, match_pk):
    match = get_object_or_404(_matches(), pk=match_pk, event_id=pk)
    action = request.POST.get("action") if request.method == "POST" else None
    score_form = ScoreForm(request.POST if action == "set" else None, match=match,
                           initial=ScoreForm.initial_for(_current_games(match)))
    forfeit_form = ForfeitForm(request.POST if action == "forfeit" else None, match=match)

    if request.method == "POST":
        try:
            if action == "set" and score_form.is_valid():
                services.admin_set_score(match, score_form.cleaned_data["games"], request.user)
                messages.success(request, "Score saved and marked final.")
                return redirect("scoring:admin_match", pk=pk, match_pk=match.pk)
            if action == "forfeit" and forfeit_form.is_valid():
                services.forfeit(match, forfeit_form.cleaned_data["side"], request.user)
                messages.success(request, "Forfeit recorded.")
                return redirect("scoring:admin_match", pk=pk, match_pk=match.pk)
            if action == "clear":
                services.admin_clear_score(match, request.user)
                messages.success(request, "Score cleared. The match is back to not played.")
                return redirect("scoring:admin_match", pk=pk, match_pk=match.pk)
        except ScoreError as exc:
            messages.error(request, str(exc))
            return redirect("scoring:admin_match", pk=pk, match_pk=match.pk)

    history = AuditLog.objects.filter(object_type=Match._meta.label, object_id=match.pk).select_related("actor")
    return render(request, "scoring/admin_match.html", {
        "match": match,
        "event": match.event,
        "score_form": score_form,
        "forfeit_form": forfeit_form,
        "submissions": match.submissions.all(),
        "history": history,
        "match_day": services.match_day(match),
        "locked": services.is_locked(match),
    })


@admin_required
def audit_log(request, pk):
    event = get_object_or_404(Event, pk=pk)
    entries = AuditLog.objects.filter(event=event).select_related("actor")
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(request, "scoring/audit_log.html", {"event": event, "page": page})


@admin_required
@require_POST
def withdraw_team(request, pk, side_pk):
    side = get_object_or_404(Side.objects.select_related("event"), pk=side_pk, event_id=pk)
    try:
        count = services.withdraw(side, request.user)
    except ScoreError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{side.name} withdrew. {count} match{'es' if count != 1 else ''} marked as forfeits.")
    return redirect("events:manage_event", pk=pk)
