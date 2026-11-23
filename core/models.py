from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Who changed what, and when (sections 6 and 7). Rows are never edited."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    event = models.ForeignKey(
        "events.Event", null=True, blank=True, on_delete=models.CASCADE, related_name="audit_logs"
    )
    action = models.CharField(max_length=60)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.action}: {self.object_repr}"
