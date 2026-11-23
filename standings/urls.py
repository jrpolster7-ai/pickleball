from django.urls import path

from . import views

app_name = "standings"

urlpatterns = [
    path("manage/events/<int:pk>/standings/", views.standings, name="standings"),
]
