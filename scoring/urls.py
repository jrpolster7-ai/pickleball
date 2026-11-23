from django.urls import path

from . import views

app_name = "scoring"

urlpatterns = [
    path("matches/<int:match_pk>/score/", views.match_score, name="match_score"),
    path("manage/events/<int:pk>/matches/<int:match_pk>/", views.admin_match, name="admin_match"),
    path("manage/events/<int:pk>/log/", views.audit_log, name="audit_log"),
    path("manage/events/<int:pk>/teams/<int:side_pk>/withdraw/", views.withdraw_team, name="withdraw_team"),
]
