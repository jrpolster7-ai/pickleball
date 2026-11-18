from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signin/", views.SignInView.as_view(), name="login"),
    path("signout/", LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("profile/", views.profile, name="profile"),
    path("claim/", views.claim_start, name="claim_start"),
    path("claim/<str:code>/", views.claim, name="claim"),
    path("manage/players/", views.manage_players, name="manage_players"),
    path("manage/players/<int:pk>/", views.manage_player, name="manage_player"),
    path("manage/admins/", views.manage_admins, name="manage_admins"),
    path("manage/admins/<int:pk>/remove/", views.remove_admin, name="remove_admin"),
]
