import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import Player
from accounts.services import player_for
from core.codes import normalize
from core.decorators import admin_required

from . import codes, defaults, notices, public_views, registration, rules, teams
from .forms import (
    AdminAddPlayerForm,
    BuildTeamForm,
    CodeForm,
    DefaultsForm,
    EventForm,
    InviteForm,
    MovePlayerForm,
    QuickCreateForm,
)
from .models import Event, Registration, Side, TeamInvite


def _events():
    return Event.objects.select_related("level", "division")


def _sides(event):
    return event.sides.prefetch_related("players")


# --- Admin: events --------------------------------------------------------

@admin_required
def manage_home(request):
    events = _events().annotate(player_total=Count("registrations"))
    return render(request, "events/manage_home.html", {
        "events": events,
        "quick_form": QuickCreateForm(),
        "has_events": events.exists(),
    })


@admin_required
@require_POST
def quick_create(request):
    form = QuickCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please pick a level, division, and start date.")
        return redirect("events:manage_home")
    event = defaults.quick_create(**form.cleaned_data, created_by=request.user)
    messages.success(request, "Event created from your saved settings. Check it over, then open sign-ups.")
    return redirect("events:manage_event", pk=event.pk)


@admin_required
def event_create(request):
    if request.GET.get("copy") == "last":
        last = _events().order_by("-created_at").first()
        initial = defaults.initial_from_event(last) if last else defaults.initial_from_defaults()
    else:
        initial = defaults.initial_from_defaults()
    form = EventForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.created_by = request.user
        event.save()
        defaults.remember(event)
        messages.success(request, "Event created.")
        return redirect("events:manage_event", pk=event.pk)
    return render(request, "events/event_form.html", {"form": form, "creating": True})


@admin_required
def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Changes saved.")
        return redirect("events:manage_event", pk=event.pk)
    return render(request, "events/event_form.html", {"form": form, "event": event})


@admin_required
def manage_event(request, pk):
    event = get_object_or_404(_events(), pk=pk)
    regs = list(
        event.registrations.select_related("player__user")
    )
    sides = list(_sides(event))
    team_of = {p.pk: side for side in sides for p in side.players.all()}
    for reg in regs:
        reg.team = team_of.get(reg.player_id)

    per_team_low, per_team_high = (0, 0)
    if event.team_count and event.total_matches:
        per_team_low, per_team_high = rules.per_team_range(event.team_count, event.total_matches)

    return render(request, "events/manage_event.html", {
        "event": event,
        "registrations": regs,
        "sides": sides,
        "add_form": AdminAddPlayerForm(event=event),
        "move_form": MovePlayerForm(event=event),
        "team_form": BuildTeamForm(event=event),
        "player_url": request.build_absolute_uri(reverse("events:join_code", args=[event.player_code])),
        "spectator_url": request.build_absolute_uri(reverse("events:join_code", args=[event.spectator_code])),
        "full_rr": rules.full_round_robin(event.team_count or 0),
        "per_team_low": per_team_low,
        "per_team_high": per_team_high,
    })


@admin_required
@require_POST
def set_status(request, pk):
    event = get_object_or_404(Event, pk=pk)
    status = request.POST.get("status")
    # Phase 1 only moves between Draft and Open. Later phases handle play.
    if status in (Event.Status.DRAFT, Event.Status.OPEN):
        event.status = status
        event.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Event is now: {event.get_status_display()}.")
    return redirect("events:manage_event", pk=pk)


@admin_required
@require_POST
def code_action(request, pk, kind, action):
    event = get_object_or_404(Event, pk=pk)
    if kind not in (codes.PLAYER, codes.SPECTATOR):
        raise Http404
    label = "Player" if kind == codes.PLAYER else "Spectator"
    if action == "rotate":
        codes.rotate_code(event, kind)
        messages.success(request, f"{label} code changed. The old code no longer works.")
    elif action == "disable":
        codes.set_code_enabled(event, kind, False)
        messages.success(request, f"{label} code turned off.")
    elif action == "enable":
        codes.set_code_enabled(event, kind, True)
        messages.success(request, f"{label} code turned on.")
    else:
        raise Http404
    return redirect("events:manage_event", pk=pk)


@admin_required
def qr_code(request, pk, kind):
    event = get_object_or_404(Event, pk=pk)
    code = {codes.PLAYER: event.player_code, codes.SPECTATOR: event.spectator_code}.get(kind)
    if not code:
        raise Http404
    url = request.build_absolute_uri(reverse("events:join_code", args=[code]))
    svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=2).to_string(encoding="unicode")
    return HttpResponse(svg, content_type="image/svg+xml")


@admin_required
def edit_defaults(request):
    obj = defaults.OrganizationDefaults.get_solo()
    form = DefaultsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved defaults updated.")
        return redirect("events:manage_home")
    return render(request, "events/defaults_form.html", {"form": form})


# --- Admin: registrations and teams --------------------------------------

@admin_required
@require_POST
def admin_add_player(request, pk):
    event = get_object_or_404(_events(), pk=pk)
    form = AdminAddPlayerForm(request.POST, event=event)
    if form.is_valid():
        player = form.cleaned_data["player"]
        try:
            registration.admin_add(event, player, override=form.cleaned_data["override"])
        except registration.RegistrationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Added {player.full_name}.")
    else:
        messages.error(request, "Pick a player to add.")
    return redirect("events:manage_event", pk=pk)


@admin_required
@require_POST
def admin_remove_player(request, pk, player_pk):
    event = get_object_or_404(Event, pk=pk)
    player = get_object_or_404(Player, pk=player_pk)
    registration.remove(event, player)
    messages.success(request, f"Removed {player.full_name}.")
    return redirect("events:manage_event", pk=pk)


@admin_required
@require_POST
def admin_move_player(request, pk, player_pk):
    event = get_object_or_404(Event, pk=pk)
    player = get_object_or_404(Player, pk=player_pk)
    form = MovePlayerForm(request.POST, event=event)
    if form.is_valid():
        to_event = form.cleaned_data["to_event"]
        try:
            registration.move(player, event, to_event, override=form.cleaned_data["override"])
        except registration.RegistrationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Moved {player.full_name} to {to_event.title}.")
    else:
        messages.error(request, "Pick an event to move them to.")
    return redirect("events:manage_event", pk=pk)


@admin_required
@require_POST
def admin_build_team(request, pk):
    event = get_object_or_404(_events(), pk=pk)
    form = BuildTeamForm(request.POST, event=event)
    if form.is_valid():
        try:
            side = teams.admin_build_team(
                event,
                [form.cleaned_data["player_a"], form.cleaned_data["player_b"]],
                override=form.cleaned_data["override"],
            )
        except teams.TeamError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Team made: {side.name}.")
    else:
        messages.error(request, "Pick two players.")
    return redirect("events:manage_event", pk=pk)


@admin_required
@require_POST
def admin_delete_team(request, pk, side_pk):
    side = get_object_or_404(Side, pk=side_pk, event_id=pk)
    teams.delete_team(side)
    messages.success(request, "Team split up. Both players are still in the event.")
    return redirect("events:manage_event", pk=pk)


# --- Joining with a code --------------------------------------------------

def join_enter(request):
    form = CodeForm(request.GET or None)
    if form.is_valid():
        return redirect("events:join_code", code=normalize(form.cleaned_data["code"]))
    return render(request, "events/join_enter.html", {"form": form})


def join_code(request, code):
    match = codes.find_code(code)
    if not match:
        messages.error(request, "We couldn't find that code. Check it and try again.")
        return redirect("events:join_enter")
    if not match.enabled:
        messages.error(request, "That code is turned off right now. Ask the organizer.")
        return redirect("events:join_enter")
    if match.kind == codes.SPECTATOR:
        return redirect("events:watch", code=match.event.spectator_code)

    if not request.user.is_authenticated:
        messages.info(request, "Create an account (or sign in) and we'll bring you right back.")
        return redirect(f"{reverse('accounts:signup')}?next={request.path}")

    event = match.event
    player = player_for(request.user)
    already = registration.is_registered(event, player)

    if match.kind == codes.PLAYER and already:
        return redirect("events:event_detail", pk=event.pk)

    if request.method == "POST":
        try:
            if match.kind == codes.TEAM:
                teams.join_by_team_code(match.side, player)
                messages.success(request, f"You're on the team: {match.side.name}.")
            else:
                registration.join(event, player)
                messages.success(request, f"You're in! Welcome to {event.title}.")
        except (registration.RegistrationError, teams.TeamError) as exc:
            messages.error(request, str(exc))
        else:
            return redirect("events:event_detail", pk=event.pk)

    problem = teams.join_team_problem(match.side, player) if match.kind == codes.TEAM else None
    if not problem and not already:
        problem = registration.self_join_problem(event, player)

    return render(request, "events/join_confirm.html", {
        "event": event, "match": match, "problem": problem,
    })


# --- Player views ---------------------------------------------------------

@login_required
def event_detail(request, pk):
    event = get_object_or_404(_events(), pk=pk)
    player = player_for(request.user)
    if not registration.is_registered(event, player) and not request.user.is_staff:
        messages.info(request, "Enter the event's code to join it.")
        return redirect("events:join_enter")
    side = teams.side_for(event, player)
    invites = TeamInvite.objects.filter(
        side__event=event, player=player, status=TeamInvite.Status.PENDING
    ).select_related("invited_by")
    sent = side.invites.filter(status=TeamInvite.Status.PENDING).select_related("player") if side else []
    my_matches = _my_matches(event, player)
    return render(request, "events/event_detail.html", {
        "event": event,
        "player": player,
        "my_matches": my_matches,
        "next_match": next((row for row in my_matches if not row[0].is_final), None),
        "notices": notices.for_player(event, player),
        "nav": public_views.nav(event, "player", "mine"),
        "side": side,
        "invites": invites,
        "sent_invites": sent,
        "invite_form": InviteForm(),
        "code_form": CodeForm(),
        "registered": registration.is_registered(event, player),
    })


def _my_matches(event, player):
    """(match, what the player can do, the other side) for each of the player's matches."""
    from scheduling.models import Match
    from scoring.services import player_view

    matches = (
        Match.objects.filter(event=event)
        .filter(Q(side_a__players=player) | Q(side_b__players=player))
        .select_related("event__division", "round__session", "side_a", "side_b")
        .prefetch_related("side_a__players", "side_b__players", "games", "submissions")
        .order_by("start_time", "court")
        .distinct()
    )
    rows = []
    for match in matches:
        state = player_view(match, player)
        own, other = (match.side_a, match.side_b) if state.side == "A" else (match.side_b, match.side_a)
        partner = " & ".join(p.full_name for p in own.players.all() if p.pk != player.pk) if own else ""
        rows.append((match, state, other, partner))
    return rows


@login_required
@require_POST
def team_action(request, pk, action):
    event = get_object_or_404(_events(), pk=pk)
    player = player_for(request.user)
    try:
        if action == "create":
            side = teams.create_team(event, player)
            messages.success(request, f"Team made! Share your team code {side.team_code} with your partner.")
        elif action == "invite":
            side = teams.side_for(event, player)
            if not side:
                raise teams.TeamError("Make a team first.")
            form = InviteForm(request.POST)
            if not form.is_valid():
                raise teams.TeamError("Type your partner's username.")
            invite = teams.invite_by_username(side, player, form.cleaned_data["username"])
            messages.success(request, f"Invite sent to {invite.player.full_name}.")
        elif action == "leave":
            side = teams.side_for(event, player)
            if side:
                teams.leave_team(side, player)
                messages.success(request, "You left the team.")
        elif action == "code":
            form = CodeForm(request.POST)
            match = codes.find_code(form.data.get("code", ""))
            if not match or match.kind != codes.TEAM or match.event.pk != event.pk:
                raise teams.TeamError("That isn't a team code for this event.")
            teams.join_by_team_code(match.side, player)
            messages.success(request, f"You're on the team: {match.side.name}.")
        else:
            raise Http404
    except teams.TeamError as exc:
        messages.error(request, str(exc))
    return redirect("events:event_detail", pk=pk)


@login_required
@require_POST
def invite_action(request, invite_pk, action):
    invite = get_object_or_404(TeamInvite.objects.select_related("side__event__division"), pk=invite_pk)
    player = player_for(request.user)
    try:
        if action == "accept":
            side = teams.accept_invite(invite, player)
            messages.success(request, f"You're on the team: {side.name}.")
        elif action == "decline":
            teams.decline_invite(invite, player)
            messages.success(request, "Invite declined.")
        else:
            raise Http404
    except teams.TeamError as exc:
        messages.error(request, str(exc))
    if registration.is_registered(invite.side.event, player):
        return redirect("events:event_detail", pk=invite.side.event_id)
    return redirect("core:home")


def my_events_context(user) -> dict:
    """Used by the home page for signed-in players."""
    player = player_for(user)
    regs = (
        Registration.objects.filter(player=player)
        .select_related("event__level", "event__division")
        .order_by("event__start_date")
    )
    invites = (
        TeamInvite.objects.filter(player=player, status=TeamInvite.Status.PENDING)
        .select_related("side__event", "invited_by")
    )
    regs = list(regs)
    for reg in regs:
        reg.new_notices = notices.unseen_count(reg)
    return {"registrations": regs, "invites": invites, "player": player}
