"""Event chat (section 11)."""

from django.conf import settings
from django.db import models

MAX_LENGTH = 500


class ChatMessage(models.Model):
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="chat_messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    body = models.TextField(max_length=MAX_LENGTH)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    # Bumped whenever the message changes (removed, reported, kept), so polling can tell.
    updated = models.DateTimeField(auto_now=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created", "id"]
        indexes = [models.Index(fields=["event", "created"])]

    def __str__(self):
        return f"{self.author} in {self.event}: {self.body[:40]}"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class ChatReport(models.Model):
    """Someone flagged a message for the organizers. Cleared when an admin keeps or removes it."""

    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["message", "reporter"], name="one_report_per_person")
        ]
