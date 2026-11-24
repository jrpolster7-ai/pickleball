from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("events.urls")),
    path("", include("scheduling.urls")),
    path("", include("scoring.urls")),
    path("", include("standings.urls")),
    path("", include("brackets.urls")),
    path("", include("chat.urls")),
    path("", include("core.urls")),
]
