from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class Gender(models.TextChoices):
    MALE = "M", "Male"
    FEMALE = "F", "Female"


class User(AbstractUser):
    """Login account. Username and password only, no email (CLAUDE.md section 3).

    Admins are users with is_staff=True.
    """

    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)


class Player(models.Model):
    """A person who plays. May exist before they have an account.

    Admin-added players get a claim code. The person uses it to create a
    username and password and take over this profile.
    """

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="player",
    )
    claim_code = models.CharField(max_length=12, unique=True, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name", "id"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def public_name(self) -> str:
        """First name and last initial, as spectators see it (section 10)."""
        initial = f" {self.last_name[:1]}." if self.last_name else ""
        return f"{self.first_name}{initial}"

    @property
    def is_claimed(self) -> bool:
        return self.user_id is not None
