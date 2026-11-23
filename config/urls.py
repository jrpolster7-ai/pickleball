from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("events.urls")),
    path("", include("scheduling.urls")),
    path("", include("scoring.urls")),
    path("", include("core.urls")),
]
