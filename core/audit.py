"""Write audit log rows. Every admin change to a schedule or score goes through here."""

from .models import AuditLog


def log(actor, action: str, obj=None, *, old="", new="", event=None) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        event=event,
        action=action,
        object_type=obj._meta.label if obj is not None else "",
        object_id=obj.pk if obj is not None else None,
        object_repr=str(obj)[:200] if obj is not None else "",
        old_value=str(old),
        new_value=str(new),
    )
