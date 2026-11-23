"""Doubles teams: create, invite by username or team code, admin-built teams (section 5)."""

from django.contrib.auth import get_user_model
from django.db import transaction

from . import registration
from .codes import new_code
from .eligibility import partner_problem, team_problem
from .models import Side, TeamInvite


class TeamError(Exception):
    """A friendly message explaining what went wrong."""


def side_for(event, player) -> Side | None:
    return Side.objects.filter(event=event, players=player).first()


def open_spot(event) -> Side | None:
    """After the schedule is published, new teams fill its empty team spots."""
    return Side.objects.filter(event=event, slot__isnull=False, players=None).order_by("slot").first()


def _team_slots_full(event) -> bool:
    if event.has_schedule:
        return open_spot(event) is None
    return bool(event.team_count) and event.sides.count() >= event.team_count


def _new_side(event, created_by=None) -> Side:
    """A new team, or the next open spot once the schedule is published."""
    spot = open_spot(event) if event.has_schedule else None
    if spot:
        spot.team_code = spot.team_code or new_code()
        spot.created_by = created_by
        spot.save(update_fields=["team_code", "created_by"])
        return spot
    return Side.objects.create(event=event, team_code=new_code(), created_by=created_by)


def empty_out(side) -> None:
    """Remove everyone from a team. A scheduled team keeps its spot; others are deleted."""
    if side.is_scheduled:
        side.players.clear()
        side.invites.filter(status=TeamInvite.Status.PENDING).update(status=TeamInvite.Status.CANCELLED)
        side.team_code = new_code()  # the old code stops working
        side.created_by = None
        side.save(update_fields=["team_code", "created_by"])
    else:
        side.delete()


def _check_doubles(event) -> None:
    if event.is_scramble:
        raise TeamError("Scramble events don't use fixed teams.")


@transaction.atomic
def create_team(event, player) -> Side:
    """A registered player starts a team and gets a team code to share."""
    _check_doubles(event)
    if not registration.is_registered(event, player):
        raise TeamError("Join the event before making a team.")
    if side_for(event, player):
        raise TeamError("You're already on a team in this event.")
    if _team_slots_full(event):
        raise TeamError("All the team spots in this event are taken.")
    side = _new_side(event, created_by=player)
    side.players.add(player)
    return side


def _check_can_add(side, player) -> None:
    if side.players.count() >= side.event.players_per_side:
        raise TeamError("That team is already full.")
    if side.players.filter(pk=player.pk).exists():
        raise TeamError("You're already on this team.")
    if side_for(side.event, player):
        raise TeamError("You're already on a team in this event.")
    for teammate in side.players.all():
        problem = partner_problem(side.event.division, teammate, player)
        if problem:
            raise TeamError(problem)


def join_team_problem(side, player) -> str | None:
    """Why this player can't join this team, or None if they can."""
    try:
        _check_can_add(side, player)
    except TeamError as exc:
        return str(exc)
    return None


def _add_and_register(side, player) -> None:
    """Add a player to a team, signing them up for the event first if needed."""
    if not registration.is_registered(side.event, player):
        try:
            registration.join(side.event, player)
        except registration.RegistrationError as exc:
            raise TeamError(str(exc)) from exc
    side.players.add(player)
    # Any other invites this player had in this event no longer apply.
    TeamInvite.objects.filter(
        side__event=side.event, player=player, status=TeamInvite.Status.PENDING
    ).exclude(side=side).update(status=TeamInvite.Status.CANCELLED)
    if side.players.count() >= side.event.players_per_side:
        TeamInvite.objects.filter(side=side, status=TeamInvite.Status.PENDING).exclude(
            player=player
        ).update(status=TeamInvite.Status.CANCELLED)


@transaction.atomic
def invite_by_username(side, invited_by, username: str) -> TeamInvite:
    from accounts.services import player_for

    _check_doubles(side.event)
    if not side.players.filter(pk=invited_by.pk).exists():
        raise TeamError("Only someone on the team can invite a partner.")
    user = get_user_model().objects.filter(username__iexact=username.strip()).first()
    if not user:
        raise TeamError("We couldn't find anyone with that username.")
    invitee = player_for(user)
    if invitee.pk == invited_by.pk:
        raise TeamError("You can't invite yourself.")
    _check_can_add(side, invitee)
    invite, _ = TeamInvite.objects.get_or_create(
        side=side,
        player=invitee,
        status=TeamInvite.Status.PENDING,
        defaults={"invited_by": invited_by},
    )
    return invite


@transaction.atomic
def accept_invite(invite, player) -> Side:
    if invite.player_id != player.pk:
        raise TeamError("This invite is for someone else.")
    if invite.status != TeamInvite.Status.PENDING:
        raise TeamError("This invite isn't active anymore.")
    side = invite.side
    _check_can_add(side, player)
    _add_and_register(side, player)
    invite.status = TeamInvite.Status.ACCEPTED
    invite.save(update_fields=["status"])
    return side


def decline_invite(invite, player) -> None:
    if invite.player_id != player.pk:
        raise TeamError("This invite is for someone else.")
    invite.status = TeamInvite.Status.DECLINED
    invite.save(update_fields=["status"])


@transaction.atomic
def join_by_team_code(side, player) -> Side:
    _check_doubles(side.event)
    _check_can_add(side, player)
    _add_and_register(side, player)
    return side


@transaction.atomic
def leave_team(side, player) -> None:
    side.players.remove(player)
    if not side.players.exists():
        empty_out(side)


@transaction.atomic
def admin_build_team(event, players, *, override: bool = False) -> Side:
    """An admin pairs two registered players. Override skips gender rules and team limits."""
    _check_doubles(event)
    players = list(players)
    if len(players) != 2 or players[0].pk == players[1].pk:
        raise TeamError("Pick two different players.")
    for p in players:
        if not registration.is_registered(event, p):
            raise TeamError(f"{p.full_name} isn't in this event yet.")
        if side_for(event, p):
            raise TeamError(f"{p.full_name} is already on a team.")
    if not override:
        problem = team_problem(event.division, players)
        if problem:
            raise TeamError(f"{problem} Tick 'override' to pair them anyway.")
        if _team_slots_full(event) and not event.has_schedule:
            raise TeamError("All the team spots are taken. Tick 'override' to add one anyway.")
    if event.has_schedule and open_spot(event) is None:
        raise TeamError("The schedule is set and every team spot is filled. Split up a team first.")
    side = _new_side(event)
    side.players.add(*players)
    return side


def delete_team(side) -> None:
    """Break up a team. The players stay registered. A scheduled team keeps its spot."""
    empty_out(side)
