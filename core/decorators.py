from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def admin_required(view):
    """Signed-in admins only. Everyone else sees a friendly 'not allowed' page."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return render(request, "core/forbidden.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper
