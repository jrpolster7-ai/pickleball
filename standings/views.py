from django.shortcuts import get_object_or_404, render

from core.decorators import admin_required
from events.models import Event

from . import services


@admin_required
def standings(request, pk):
    """The two ranking screens (section 8): win and loss, or total points."""
    event = get_object_or_404(Event.objects.select_related("level", "division"), pk=pk)
    view = "points" if request.GET.get("view") == "points" else "wins"
    table = services.table(event)
    rows = table.total_points if view == "points" else table.win_loss
    return render(request, "standings/standings.html", {
        "event": event,
        "view": view,
        "rows": rows,
        "pools": table.pool_rankings(view) if table.pools else [],
        "remaining": table.remaining,
        "who": "Player" if event.is_scramble else "Team",
    })
