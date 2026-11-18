from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.codes import normalize
from core.decorators import admin_required

from . import services
from .forms import (
    AdminSetPasswordForm,
    ClaimCodeForm,
    ClaimForm,
    LoginForm,
    MergeForm,
    PlayerForm,
    ProfileForm,
    SignupForm,
    UsernameForm,
)
from .models import Player

User = get_user_model()


def _safe_next(request) -> str:
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return reverse("core:home")


# --- Signing in and up ----------------------------------------------------

class SignInView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get("remember_me"):
            # Sign out when the browser closes.
            self.request.session.set_expiry(0)
        return response


def signup(request):
    nxt = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(nxt)
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        services.player_for(user)
        login(request, user)
        messages.success(request, f"Welcome, {user.first_name}!")
        return redirect(nxt)
    return render(request, "accounts/signup.html", {"form": form, "next": nxt})


def claim_start(request):
    form = ClaimCodeForm(request.GET or None)
    if form.is_valid():
        return redirect("accounts:claim", code=normalize(form.cleaned_data["code"]))
    return render(request, "accounts/claim_start.html", {"form": form})


def claim(request, code):
    player = Player.objects.filter(claim_code=normalize(code), user__isnull=True).first()
    if not player:
        messages.error(request, "That claim code didn't work. Check it with the organizer.")
        return redirect("accounts:claim_start")
    if request.user.is_authenticated:
        # Already has an account: link the admin-added profile to it.
        if request.method == "POST":
            try:
                services.merge_players(keep=services.player_for(request.user), remove=player)
            except services.MergeError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Done! That profile is now part of your account.")
                return redirect("core:home")
        return render(request, "accounts/claim_link.html", {"player": player})

    form = ClaimForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = services.claim_player(
            player, username=form.cleaned_data["username"], password=form.cleaned_data["password1"]
        )
        login(request, user)
        messages.success(request, f"You're all set, {user.first_name}!")
        return redirect("core:home")
    return render(request, "accounts/claim.html", {"form": form, "player": player})


def profile(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?next={request.path}")
    user = request.user
    form = ProfileForm(
        request.POST or None,
        initial={"first_name": user.first_name, "last_name": user.last_name, "gender": user.gender},
    )
    if request.method == "POST" and form.is_valid():
        services.update_profile(user, **form.cleaned_data)
        messages.success(request, "Profile saved.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


# --- Admin: players -------------------------------------------------------

@admin_required
def manage_players(request):
    form = PlayerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        player = services.add_player(**form.cleaned_data, created_by=request.user)
        messages.success(request, f"Added {player.full_name}. Share the claim code below with them.")
        return redirect("accounts:manage_player", pk=player.pk)
    players = Player.objects.select_related("user")
    query = request.GET.get("q", "").strip()
    if query:
        players = players.filter(first_name__icontains=query) | players.filter(last_name__icontains=query)
    return render(request, "accounts/manage_players.html", {"form": form, "players": players, "q": query})


@admin_required
def manage_player(request, pk):
    player = get_object_or_404(Player.objects.select_related("user"), pk=pk)
    is_merge = request.method == "POST" and "merge" in request.POST
    password_post = request.POST if request.method == "POST" and not is_merge else None
    password_form = AdminSetPasswordForm(player.user, password_post) if player.user else None
    merge_form = MergeForm(request.POST if is_merge else None, player=player)

    if is_merge and merge_form.is_valid():
        duplicate = merge_form.cleaned_data["duplicate"]
        name = duplicate.full_name
        try:
            services.merge_players(keep=player, remove=duplicate)
        except services.MergeError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Merged {name} into this profile.")
        return redirect("accounts:manage_player", pk=player.pk)
    if password_post and password_form and password_form.is_valid():
        services.set_password(player.user, password_form.cleaned_data["new_password1"])
        messages.success(request, f"Password changed. Tell {player.first_name} their new password.")
        return redirect("accounts:manage_player", pk=player.pk)
    claim_url = (
        request.build_absolute_uri(reverse("accounts:claim", args=[player.claim_code]))
        if player.claim_code else None
    )
    registrations = player.registrations.select_related("event__level", "event__division")
    return render(request, "accounts/manage_player.html", {
        "player": player, "password_form": password_form, "claim_url": claim_url,
        "registrations": registrations, "merge_form": merge_form,
    })


# --- Admin: admins --------------------------------------------------------

@admin_required
def manage_admins(request):
    promote_form = UsernameForm(prefix="promote")
    create_form = SignupForm(prefix="create")
    if request.method == "POST":
        if "promote" in request.POST:
            promote_form = UsernameForm(request.POST, prefix="promote")
            if promote_form.is_valid():
                services.make_admin(promote_form.user)
                messages.success(request, f"{promote_form.user.username} is now an admin.")
                return redirect("accounts:manage_admins")
        elif "create" in request.POST:
            create_form = SignupForm(request.POST, prefix="create")
            if create_form.is_valid():
                user = create_form.save()
                services.make_admin(user)
                messages.success(request, f"Created admin {user.username}.")
                return redirect("accounts:manage_admins")
    return render(request, "accounts/manage_admins.html", {
        "admins": services.admins(), "promote_form": promote_form, "create_form": create_form,
    })


@admin_required
@require_POST
def remove_admin(request, pk):
    user = get_object_or_404(User, pk=pk)
    try:
        services.remove_admin(user)
    except services.LastAdminError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{user.username} is no longer an admin.")
    if user.pk == request.user.pk and not user.is_staff:
        return redirect("core:home")
    return redirect("accounts:manage_admins")
