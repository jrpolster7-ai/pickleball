from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model, in place from day one so it can grow safely.

    Profile fields (gender, etc.) are added in Phase 1.
    """
