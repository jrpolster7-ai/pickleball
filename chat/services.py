"""Event chat rules (section 11).

Only players registered for the event, and admins, can read or post.
Spectators never see chat. Admins remove messages; anyone in the chat can
report one. Removed messages stay as a placeholder so replies still make sense.
"""

from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone

from core import audit
from events.models import Registration

from .models import MAX_LENGTH, ChatMessage, ChatReport

SHOW_LATEST = 100


class ChatError(Exception):
    """A friendly message to show the person."""


def can_chat(user, event) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    return Registration.objects.filter(
        event=event, player__user=user, status=Registration.Status.ACTIVE
    ).exists()


def post(event, user, body: str) -> ChatMessage:
    if not can_chat(user, event):
        raise ChatError("Only players in this event can post here.")
    body = (body or "").strip()
    if not body:
        raise ChatError("Type a message first.")
    if len(body) > MAX_LENGTH:
        raise ChatError(f"Keep messages under {MAX_LENGTH} characters.")
    return ChatMessage.objects.create(event=event, author=user, body=body)


def delete(message: ChatMessage, admin) -> None:
    if message.is_deleted:
        return
    message.deleted_by = admin
    message.deleted_at = timezone.now()
    message.save(update_fields=["deleted_by", "deleted_at", "updated"])
    message.reports.filter(resolved=False).update(resolved=True)
    audit.log(admin, "chat.delete", message, old=message.body, event=message.event)


def report(message: ChatMessage, user) -> None:
    if not can_chat(user, message.event):
        raise ChatError("Only players in this event can report messages.")
    if message.author_id == user.pk:
        raise ChatError("You can't report your own message.")
    if message.is_deleted:
        return
    ChatReport.objects.get_or_create(message=message, reporter=user, defaults={"resolved": False})
    message.save(update_fields=["updated"])


def keep(message: ChatMessage, admin) -> None:
    """The admin looked at the reports and decided the message is fine."""
    if message.reports.filter(resolved=False).update(resolved=True):
        message.save(update_fields=["updated"])
        audit.log(admin, "chat.keep", message, event=message.event)


def version(event) -> str:
    """Changes whenever anything in the chat changes. Polling sends it back to skip unchanged refreshes."""
    agg = ChatMessage.objects.filter(event=event).aggregate(last=Max("id"), changed=Max("updated"))
    if agg["last"] is None:
        return "0"
    return f"{agg['last']}-{agg['changed'].timestamp():.6f}"


def latest(event, user, limit: int = SHOW_LATEST) -> tuple[list[ChatMessage], bool]:
    """The newest messages, oldest first, with what this user needs to draw each one.

    Returns (messages, has_older).
    """
    qs = (
        ChatMessage.objects.filter(event=event)
        .select_related("author")
        .annotate(open_reports=Count("reports", filter=Q(reports__resolved=False)))
        .prefetch_related(Prefetch("reports", queryset=ChatReport.objects.filter(reporter=user),
                                   to_attr="my_reports"))
        .order_by("-created", "-id")
    )
    rows = list(qs[: limit + 1])
    has_older = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    for m in rows:
        m.mine = m.author_id == user.pk
        m.i_reported = bool(m.my_reports)
    return rows, has_older


def open_report_count(event) -> int:
    return ChatMessage.objects.filter(
        event=event, deleted_at__isnull=True, reports__resolved=False
    ).distinct().count()
