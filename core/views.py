from django.shortcuts import render

from events.forms import CodeForm


def home(request):
    context = {"code_form": CodeForm()}
    if request.user.is_authenticated:
        from events.views import my_events_context

        context.update(my_events_context(request.user))
    return render(request, "core/home.html", context)
