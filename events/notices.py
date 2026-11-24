"""In-app notices about schedule changes (section 10). No email or texts in version 1."""

from django.utils import timezone

from .models import Notice, Registration


def post(event, message: str) -> Notice:
    return Notice.objects.create(event=event, message=message[:300])


def for_player(event, player, limit: int = 10):
    """Recent notices, each marked new if the player hasn't seen it. Marks them seen."""
    reg = Registration.objects.filter(event=event, player=player).first()
    seen = reg.notices_seen_at if reg else None
    notices = list(event.notices.all()[:limit])
    for notice in notices:
        notice.is_new = seen is None or notice.created > seen
    if reg and notices:
        Registration.objects.filter(pk=reg.pk).update(notices_seen_at=timezone.now())
    return notices


def unseen_count(registration) -> int:
    qs = registration.event.notices.all()
    if registration.notices_seen_at:
        qs = qs.filter(created__gt=registration.notices_seen_at)
    return qs.count()
