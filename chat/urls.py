from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("events/<int:pk>/chat/", views.room, name="room"),
    path("events/<int:pk>/chat/messages/", views.poll, name="poll"),
    path("events/<int:pk>/chat/post/", views.post, name="post"),
    path("chat/<int:message_id>/report/", views.report, name="report"),
    path("chat/<int:message_id>/remove/", views.delete, name="delete"),
    path("chat/<int:message_id>/keep/", views.keep, name="keep"),
]
