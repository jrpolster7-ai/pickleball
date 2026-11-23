from django.urls import path

from . import views

app_name = "scheduling"

urlpatterns = [
    path("manage/events/<int:pk>/schedule/", views.schedule, name="schedule"),
    path("manage/events/<int:pk>/schedule/publish/", views.publish, name="publish"),
    path("manage/events/<int:pk>/schedule/clear/", views.clear, name="clear"),
    path("manage/events/<int:pk>/schedule/start/", views.start_play, name="start_play"),
    path("manage/events/<int:pk>/schedule/retime/", views.retime, name="retime"),
    path("manage/events/<int:pk>/schedule/rounds/<int:round_pk>/", views.round_time, name="round_time"),
    path("manage/events/<int:pk>/schedule/matches/<int:match_pk>/", views.match_edit, name="match_edit"),
]
