from django.urls import path

from . import public_views, views

app_name = "events"

urlpatterns = [
    # Codes: one join box for player, spectator, and team codes.
    path("join/", views.join_enter, name="join_enter"),
    path("join/<str:code>/", views.join_code, name="join_code"),
    path("watch/<str:code>/", public_views.watch, name="watch"),
    path("watch/<str:code>/standings/", public_views.watch_standings, name="watch_standings"),
    path("watch/<str:code>/bracket/", public_views.watch_bracket, name="watch_bracket"),

    # Players
    path("events/<int:pk>/", views.event_detail, name="event_detail"),
    path("events/<int:pk>/rounds/", public_views.event_rounds, name="event_rounds"),
    path("events/<int:pk>/standings/", public_views.event_standings, name="event_standings"),
    path("events/<int:pk>/bracket/", public_views.event_bracket, name="event_bracket"),
    path("events/<int:pk>/team/<str:action>/", views.team_action, name="team_action"),
    path("invites/<int:invite_pk>/<str:action>/", views.invite_action, name="invite_action"),

    # Admin
    path("manage/", views.manage_home, name="manage_home"),
    path("manage/defaults/", views.edit_defaults, name="edit_defaults"),
    path("manage/events/new/", views.event_create, name="event_create"),
    path("manage/events/quick/", views.quick_create, name="quick_create"),
    path("manage/events/<int:pk>/", views.manage_event, name="manage_event"),
    path("manage/events/<int:pk>/edit/", views.event_edit, name="event_edit"),
    path("manage/events/<int:pk>/status/", views.set_status, name="set_status"),
    path("manage/events/<int:pk>/codes/<str:kind>/<str:action>/", views.code_action, name="code_action"),
    path("manage/events/<int:pk>/qr/<str:kind>.svg", views.qr_code, name="qr_code"),
    path("manage/events/<int:pk>/players/add/", views.admin_add_player, name="admin_add_player"),
    path("manage/events/<int:pk>/players/<int:player_pk>/remove/", views.admin_remove_player, name="admin_remove_player"),
    path("manage/events/<int:pk>/players/<int:player_pk>/move/", views.admin_move_player, name="admin_move_player"),
    path("manage/events/<int:pk>/teams/add/", views.admin_build_team, name="admin_build_team"),
    path("manage/events/<int:pk>/teams/<int:side_pk>/delete/", views.admin_delete_team, name="admin_delete_team"),
]
