"""Make the first admin from environment variables, for hosts without a shell.

    DJANGO_ADMIN_USERNAME=rachel DJANGO_ADMIN_PASSWORD=... python manage.py ensure_admin

Does nothing if the variables are blank or an admin already exists, so it is
safe to run on every deploy. After the first sign-in, change the password in
the app and you can remove the variables.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.services import player_for


class Command(BaseCommand):
    help = "Create the first admin from DJANGO_ADMIN_USERNAME and DJANGO_ADMIN_PASSWORD if there is no admin yet."

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get("DJANGO_ADMIN_USERNAME", "").strip()
        password = os.environ.get("DJANGO_ADMIN_PASSWORD", "")
        if User.objects.filter(is_staff=True, is_active=True).exists():
            self.stdout.write("An admin already exists. Nothing to do.")
            return
        if not username or not password:
            self.stdout.write("No admin yet. Set DJANGO_ADMIN_USERNAME and DJANGO_ADMIN_PASSWORD to make one.")
            return
        user = User.objects.filter(username__iexact=username).first() or User(username=username)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("DJANGO_ADMIN_PASSWORD is too weak: " + " ".join(exc.messages)) from exc
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save()
        player_for(user)
        self.stdout.write(self.style.SUCCESS(f"Admin '{user.username}' is ready."))
