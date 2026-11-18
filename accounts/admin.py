from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Player, User


@admin.register(User)
class PickleballUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Pickleball", {"fields": ("gender",)}),)
    list_display = ("username", "first_name", "last_name", "gender", "is_staff")


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "gender", "user", "claim_code")
    search_fields = ("first_name", "last_name", "user__username")
