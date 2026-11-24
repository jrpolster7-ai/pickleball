from django.contrib import admin

from .models import ChatMessage, ChatReport


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("event", "author", "created", "deleted_at")
    list_filter = ("event",)
    search_fields = ("body", "author__username")


admin.site.register(ChatReport)
