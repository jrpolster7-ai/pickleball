from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm

from .models import Gender, Player

User = get_user_model()


class GenderField(forms.ChoiceField):
    def __init__(self, **kwargs):
        kwargs.setdefault("choices", Gender.choices)
        kwargs.setdefault("widget", forms.RadioSelect)
        kwargs.setdefault(
            "help_text", "Used only to check sign-ups for Men's, Women's, and Mixed events."
        )
        super().__init__(**kwargs)


class SignupForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    gender = GenderField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "first_name", "last_name", "gender"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Letters, numbers, and @ . + - _ only. You'll use this to sign in."
        self.fields["username"].widget.attrs.update(autocapitalize="none", autocomplete="username")


class LoginForm(AuthenticationForm):
    remember_me = forms.BooleanField(label="Stay signed in on this device", required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(autocapitalize="none")


class ClaimForm(UserCreationForm):
    """Pick a username and password for an admin-added profile."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "You'll use this to sign in."
        self.fields["username"].widget.attrs.update(autocapitalize="none", autocomplete="username")


class ClaimCodeForm(forms.Form):
    code = forms.CharField(label="Claim code", max_length=20)


class ProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    gender = GenderField()


class PlayerForm(forms.ModelForm):
    """Admin adds a player who has no account yet."""

    gender = GenderField(help_text="")

    class Meta:
        model = Player
        fields = ["first_name", "last_name", "gender"]


class UsernameForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocapitalize": "none"}))

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        user = User.objects.filter(username__iexact=username).first()
        if not user:
            raise forms.ValidationError("We couldn't find anyone with that username.")
        self.user = user
        return username


class AdminSetPasswordForm(SetPasswordForm):
    pass


class MergeForm(forms.Form):
    """Pick a duplicate profile to fold into this one."""

    duplicate = forms.ModelChoiceField(Player.objects.none(), label="Duplicate profile")

    def __init__(self, *args, player=None, **kwargs):
        super().__init__(*args, **kwargs)
        others = Player.objects.exclude(pk=player.pk).select_related("user")
        if player.user_id:
            others = others.filter(user__isnull=True)  # two logins can't merge
        self.fields["duplicate"].queryset = others
        self.fields["duplicate"].label_from_instance = (
            lambda p: f"{p.full_name} (@{p.user.username})" if p.user else f"{p.full_name} (no login)"
        )
