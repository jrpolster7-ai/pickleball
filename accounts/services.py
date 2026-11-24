"""Account logic: players, claim codes, admins (section 3)."""

from django.contrib.auth import get_user_model
from django.db import transaction

from core.codes import generate_unique

from .models import Player

CLAIM_CODE_LENGTH = 8


class LastAdminError(Exception):
    pass


def player_for(user) -> Player:
    """The Player profile linked to this user, created if missing."""
    try:
        return user.player
    except Player.DoesNotExist:
        return Player.objects.create(
            user=user,
            first_name=user.first_name or user.username,
            last_name=user.last_name,
            gender=user.gender,
        )


def new_claim_code() -> str:
    return generate_unique(
        CLAIM_CODE_LENGTH, lambda c: Player.objects.filter(claim_code=c).exists()
    )


def add_player(*, first_name: str, last_name: str, gender: str, created_by) -> Player:
    """An admin adds someone who has no account yet. They get a claim code."""
    return Player.objects.create(
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        claim_code=new_claim_code(),
        created_by=created_by,
    )


@transaction.atomic
def claim_player(player: Player, *, username: str, password: str):
    """Turn an admin-added Player into a real account."""
    player = Player.objects.select_for_update(of=("self",)).get(pk=player.pk)
    if player.is_claimed:
        raise ValueError("This profile has already been claimed.")
    user = get_user_model().objects.create_user(
        username=username,
        password=password,
        first_name=player.first_name,
        last_name=player.last_name,
        gender=player.gender,
    )
    player.user = user
    player.claim_code = None
    player.save(update_fields=["user", "claim_code"])
    return user


class MergeError(Exception):
    """A friendly message explaining why two profiles can't be merged."""


@transaction.atomic
def merge_players(*, keep: Player, remove: Player) -> Player:
    """Fold a duplicate profile into `keep`, then delete the duplicate.

    Typical case: an admin added someone, and that person later signed up on
    their own. Event spots, teams, and invites all move to `keep`.
    """
    from events.models import Registration, Side, TeamInvite

    if keep.pk == remove.pk:
        raise MergeError("Pick two different profiles.")
    keep = Player.objects.select_for_update(of=("self",)).get(pk=keep.pk)
    remove = Player.objects.select_for_update(of=("self",)).get(pk=remove.pk)
    if keep.user_id and remove.user_id:
        raise MergeError("Both profiles have their own login, so they can't be merged.")

    # Check for team conflicts before changing anything.
    for side in Side.objects.filter(players=remove).select_related("event"):
        other = Side.objects.filter(event=side.event, players=keep).exclude(pk=side.pk).first()
        if other:
            raise MergeError(
                f"Both profiles are on different teams in {side.event.title}. "
                "Split one of those teams first."
            )

    for side in Side.objects.filter(players=remove):
        side.players.remove(remove)
        side.players.add(keep)  # no-op if keep was already on this team
    Side.objects.filter(created_by=remove).update(created_by=keep)

    keep_events = set(Registration.objects.filter(player=keep).values_list("event_id", flat=True))
    Registration.objects.filter(player=remove, event_id__in=keep_events).delete()
    Registration.objects.filter(player=remove).update(player=keep)

    TeamInvite.objects.filter(player=remove).update(player=keep)
    TeamInvite.objects.filter(invited_by=remove).update(invited_by=keep)
    # An invite to join your own team makes no sense after a merge.
    for invite in TeamInvite.objects.filter(player=keep, side__players=keep):
        invite.delete()

    # Keep the login, wherever it was. Fill in anything missing on `keep`.
    user = remove.user
    if not keep.gender:
        keep.gender = remove.gender
    remove.delete()
    if user and not keep.user_id:
        keep.user = user
        keep.claim_code = None
    keep.save()
    return keep


def update_profile(user, *, first_name: str, last_name: str, gender: str) -> None:
    """Keep the user and their Player profile in step."""
    user.first_name, user.last_name, user.gender = first_name, last_name, gender
    user.save(update_fields=["first_name", "last_name", "gender"])
    player = player_for(user)
    player.first_name, player.last_name, player.gender = first_name, last_name, gender
    player.save(update_fields=["first_name", "last_name", "gender"])


def admins():
    return get_user_model().objects.filter(is_staff=True, is_active=True).order_by("username")


def make_admin(user) -> None:
    user.is_staff = True
    user.save(update_fields=["is_staff"])


@transaction.atomic
def remove_admin(user) -> None:
    """Any admin can remove another. The last admin can never be removed."""
    current = list(admins().select_for_update(of=("self",)))
    if user.pk in {u.pk for u in current} and len(current) <= 1:
        raise LastAdminError("You can't remove the last admin.")
    user.is_staff = False
    user.is_superuser = False
    user.save(update_fields=["is_staff", "is_superuser"])


def set_password(user, password: str) -> None:
    """Admins reset passwords by hand, since there's no email."""
    user.set_password(password)
    user.save(update_fields=["password"])
