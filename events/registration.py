"""Joining, removing, and moving players between events (section 5)."""

from django.db import transaction

from .eligibility import registration_problem
from .models import Event, Registration, RegistrationMode, Side, TeamInvite


class RegistrationError(Exception):
    """A friendly message explaining why the player can't join."""


def is_registered(event, player) -> bool:
    return Registration.objects.filter(event=event, player=player).exists()


def active_count(event) -> int:
    return event.registrations.filter(status=Registration.Status.ACTIVE).count()


def self_join_problem(event, player) -> str | None:
    """Why a player can't join this event themselves, or None if they can."""
    if event.status == Event.Status.DRAFT:
        return "This event isn't open yet. Check back soon."
    if event.status != Event.Status.OPEN:
        return "Sign-ups for this event are closed."
    if event.registration_mode == RegistrationMode.ADMIN:
        return "The organizer adds players to this event. Ask them to add you."
    if active_count(event) >= event.player_capacity:
        return "This event is full."
    return registration_problem(event.division, player)


@transaction.atomic
def join(event, player) -> Registration:
    """A player joins on their own, using a code."""
    existing = Registration.objects.filter(event=event, player=player).first()
    if existing:
        return existing
    # Lock the event row so two people can't take the last spot at once (PostgreSQL).
    event = Event.objects.select_for_update(of=("self",)).select_related("division").get(pk=event.pk)
    problem = self_join_problem(event, player)
    if problem:
        raise RegistrationError(problem)
    return Registration.objects.create(event=event, player=player)


@transaction.atomic
def admin_add(event, player, *, override: bool = False) -> Registration:
    """An admin places a player. Override skips capacity and eligibility checks."""
    existing = Registration.objects.filter(event=event, player=player).first()
    if existing:
        return existing
    event = Event.objects.select_for_update(of=("self",)).select_related("division").get(pk=event.pk)
    if not override:
        if active_count(event) >= event.player_capacity:
            raise RegistrationError("This event is full. Tick 'override' to add them anyway.")
        problem = registration_problem(event.division, player)
        if problem:
            raise RegistrationError(f"{problem} Tick 'override' to add them anyway.")
    return Registration.objects.create(event=event, player=player)


@transaction.atomic
def remove(event, player) -> None:
    """Take a player out of an event, along with their team spot and invites."""
    from .teams import empty_out

    # Scramble's per-round sides stay as played; swapping in a substitute is an admin edit.
    sides = [] if event.is_scramble else Side.objects.filter(event=event, players=player)
    for side in sides:
        side.players.remove(player)
        if not side.players.exists():
            empty_out(side)
    TeamInvite.objects.filter(side__event=event, player=player).delete()
    TeamInvite.objects.filter(side__event=event, invited_by=player).delete()
    Registration.objects.filter(event=event, player=player).delete()


@transaction.atomic
def move(player, from_event, to_event, *, override: bool = False) -> Registration:
    """Admin moves a player from one event to another."""
    if from_event.pk == to_event.pk:
        raise RegistrationError("Pick a different event.")
    registration = admin_add(to_event, player, override=override)
    remove(from_event, player)
    return registration
