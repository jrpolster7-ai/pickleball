from django.urls import path

from . import views

app_name = "brackets"

urlpatterns = [
    path("manage/events/<int:pk>/bracket/", views.bracket, name="bracket"),
    path("manage/events/<int:pk>/bracket/build/", views.build, name="build"),
    path("manage/events/<int:pk>/bracket/tiebreak/", views.tiebreak, name="tiebreak"),
    path("manage/events/<int:pk>/bracket/delete/", views.delete, name="delete"),
]
