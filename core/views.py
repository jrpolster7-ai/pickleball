from django.shortcuts import render


def home(request):
    """Placeholder landing page. Real screens arrive in later phases."""
    return render(request, "core/home.html")
