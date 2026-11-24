"""Event chat pages (section 11). HTMX polls the message list every few seconds.

Every action also works as a plain form post, so chat still works without JavaScript.
"""

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import admin_required
from events.models import Event
from events.public_views import nav

from . import services
from .models import MAX_LENGTH, ChatMessage


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _event_for(request, pk):
    """(event, redirect). Redirects people who aren't in the event."""
    event = get_object_or_404(Event.objects.select_related("level", "division"), pk=pk)
    if not services.can_chat(request.user, event):
        flash.info(request, "Chat is for players in this event. Enter the event's code to join.")
        return event, redirect("events:join_enter")
    return event, None


def _list_context(request, event):
    rows, has_older = services.latest(event, request.user)
    return {
        "event": event,
        "chat_messages": rows,
        "has_older": has_older,
        "version": services.version(event),
        "today": timezone.localdate().strftime("%Y%m%d"),
        "show_latest": services.SHOW_LATEST,
    }


def _list(request, event, status=200):
    return render(request, "chat/_messages.html", _list_context(request, event), status=status)


@login_required
def room(request, pk):
    event, bounce = _event_for(request, pk)
    if bounce:
        return bounce
    return render(request, "chat/room.html", {
        **_list_context(request, event),
        "audience": "player",
        "nav": nav(event, "player", "chat"),
        "max_length": MAX_LENGTH,
        "report_count": services.open_report_count(event) if request.user.is_staff else 0,
    })


@login_required
def poll(request, pk):
    event, bounce = _event_for(request, pk)
    if bounce:
        return HttpResponse(status=403)
    if request.GET.get("v") == services.version(event):
        return HttpResponse(status=204)  # Nothing new. HTMX leaves the page alone.
    return _list(request, event)


@login_required
@require_POST
def post(request, pk):
    event, bounce = _event_for(request, pk)
    if bounce:
        return bounce
    body = request.POST.get("body", "")
    error = ""
    try:
        services.post(event, request.user, body)
        body = ""
    except services.ChatError as exc:
        error = str(exc)
    if _is_htmx(request):
        return render(request, "chat/_box.html", {
            **_list_context(request, event), "error": error, "body": body, "max_length": MAX_LENGTH,
        })
    if error:
        flash.error(request, error)
    return redirect("chat:room", pk=event.pk)


def _message_action(request, message_id, action):
    message = get_object_or_404(ChatMessage.objects.select_related("event"), pk=message_id)
    event = message.event
    try:
        action(message)
    except services.ChatError as exc:
        if not _is_htmx(request):
            flash.error(request, str(exc))
    if _is_htmx(request):
        return _list(request, event)
    return redirect("chat:room", pk=event.pk)


@login_required
@require_POST
def report(request, message_id):
    def act(message):
        services.report(message, request.user)
        if not _is_htmx(request):
            flash.success(request, "Thanks. An organizer will take a look.")
    return _message_action(request, message_id, act)


@admin_required
@require_POST
def delete(request, message_id):
    return _message_action(request, message_id, lambda m: services.delete(m, request.user))


@admin_required
@require_POST
def keep(request, message_id):
    return _message_action(request, message_id, lambda m: services.keep(m, request.user))
