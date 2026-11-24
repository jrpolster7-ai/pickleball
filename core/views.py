import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from events.forms import CodeForm


def home(request):
    context = {"code_form": CodeForm()}
    if request.user.is_authenticated:
        from events.views import my_events_context

        context.update(my_events_context(request.user))
    return render(request, "core/home.html", context)


logger = logging.getLogger("django.security.csrf")


def csrf_failure(request, reason=""):
    """A friendly page when a form's security code is out of date (CSRF_FAILURE_VIEW).

    The usual cause: signing in gives the browser a new code, so a page opened
    before that (another tab, or the Back button) carries the old one.
    Nothing is saved. We never redo the action, only point the person onward.
    """
    logger.warning("Form rejected (%s): %s %s", reason, request.method, request.path)
    signing_in = request.path in (reverse("accounts:login"), reverse("accounts:signup"))
    if signing_in and request.user.is_authenticated:
        messages.info(request, f"You're already signed in as {request.user.username}.")
        return redirect("core:home")

    back = request.META.get("HTTP_REFERER", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        back = request.path if signing_in else reverse("core:home")
    return render(request, "core/form_expired.html", {"back": back}, status=403)
