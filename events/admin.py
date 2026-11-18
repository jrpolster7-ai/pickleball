from django.contrib import admin

from .models import Division, Event, Level, OrganizationDefaults, Registration, Side, TeamInvite

admin.site.register(Level)
admin.site.register(Division)
admin.site.register(OrganizationDefaults)
admin.site.register(TeamInvite)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "level", "division", "start_date", "status", "player_code", "spectator_code")
    list_filter = ("status", "level", "division")


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("player", "event", "status")
    list_filter = ("event",)


@admin.register(Side)
class SideAdmin(admin.ModelAdmin):
    list_display = ("__str__", "event", "team_code")
    list_filter = ("event",)
