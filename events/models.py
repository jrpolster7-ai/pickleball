import datetime

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

MAX_COURTS = 8
MAX_PARTICIPANTS = 500


class Level(models.Model):
    """Beginner, Intermediate, Advanced. Seeded by migration."""

    name = models.CharField(max_length=50, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Division(models.Model):
    """Men's, Women's, Mixed, Scramble. Seeded by migration."""

    class Kind(models.TextChoices):
        MENS = "MENS", "Men's"
        WOMENS = "WOMENS", "Women's"
        MIXED = "MIXED", "Mixed"
        SCRAMBLE = "SCRAMBLE", "Scramble"

    name = models.CharField(max_length=50, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def is_scramble(self) -> bool:
        return self.kind == self.Kind.SCRAMBLE


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Monday"
    TUESDAY = 1, "Tuesday"
    WEDNESDAY = 2, "Wednesday"
    THURSDAY = 3, "Thursday"
    FRIDAY = 4, "Friday"
    SATURDAY = 5, "Saturday"
    SUNDAY = 6, "Sunday"


class RegistrationMode(models.TextChoices):
    ADMIN = "ADMIN", "Admin adds everyone"
    CODE = "CODE", "Players join with a code"
    BOTH = "BOTH", "Both"


class BracketType(models.TextChoices):
    SINGLE = "SINGLE", "Single elimination"
    DOUBLE = "DOUBLE", "Double elimination"


class BracketSizing(models.TextChoices):
    BYES = "BYES", "Top seeds get byes"
    PLAY_IN = "PLAY_IN", "Play-in matches"


class GamesPerMatch(models.IntegerChoices):
    ONE = 1, "1 game"
    THREE = 3, "Best of 3"


class EventSettings(models.Model):
    """Settings shared by Event and OrganizationDefaults (section 12)."""

    court_count = models.PositiveSmallIntegerField(
        "courts", default=4, validators=[MinValueValidator(1), MaxValueValidator(MAX_COURTS)]
    )
    games_per_match = models.PositiveSmallIntegerField(
        choices=GamesPerMatch.choices, default=GamesPerMatch.THREE
    )
    points_to_win = models.PositiveSmallIntegerField(default=11, validators=[MinValueValidator(1)])
    win_by_two = models.BooleanField(default=True)
    point_cap = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Optional. Leave blank for no cap."
    )
    minutes_per_match = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1)]
    )
    break_minutes = models.PositiveSmallIntegerField("minutes between rounds", default=5)
    start_time = models.TimeField(default=datetime.time(18, 0))
    players_enter_scores = models.BooleanField(default=True)
    registration_mode = models.CharField(
        max_length=10, choices=RegistrationMode.choices, default=RegistrationMode.BOTH
    )
    max_participants = models.PositiveSmallIntegerField(
        default=64, validators=[MinValueValidator(2), MaxValueValidator(MAX_PARTICIPANTS)]
    )
    pool_size = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(2)],
        help_text="Optional. Teams per pool for large events.",
    )
    bracket_type = models.CharField(
        max_length=10, choices=BracketType.choices, default=BracketType.SINGLE
    )
    bracket_sizing = models.CharField(
        max_length=10, choices=BracketSizing.choices, default=BracketSizing.BYES
    )
    third_place_match = models.BooleanField(default=True)

    class Meta:
        abstract = True


# Field names copied between an Event and OrganizationDefaults.
SETTING_FIELDS = [
    "court_count",
    "games_per_match",
    "points_to_win",
    "win_by_two",
    "point_cap",
    "minutes_per_match",
    "break_minutes",
    "start_time",
    "players_enter_scores",
    "registration_mode",
    "max_participants",
    "pool_size",
    "bracket_type",
    "bracket_sizing",
    "third_place_match",
]


class OrganizationDefaults(EventSettings):
    """One row. Remembers the default location and last-used settings."""

    default_location = models.CharField(
        max_length=200, default="Waco Regional Tennis and Fitness Center"
    )
    team_count = models.PositiveSmallIntegerField(default=8, validators=[MinValueValidator(2)])
    matches_per_team = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1)]
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "organization defaults"
        verbose_name_plural = "organization defaults"

    def __str__(self):
        return "Organization defaults"

    @classmethod
    def get_solo(cls) -> "OrganizationDefaults":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Event(EventSettings):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        OPEN = "OPEN", "Open for registration"
        ROUND_ROBIN = "ROUND_ROBIN", "Round robin"
        BRACKET = "BRACKET", "Bracket"
        COMPLETE = "COMPLETE", "Complete"

    title = models.CharField(max_length=200)
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="events")
    division = models.ForeignKey(Division, on_delete=models.PROTECT, related_name="events")
    location = models.CharField(max_length=200)

    start_date = models.DateField()
    end_date = models.DateField()
    weeks = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    weekly_day = models.PositiveSmallIntegerField(choices=Weekday.choices, null=True, blank=True)

    team_count = models.PositiveSmallIntegerField(
        "number of teams", null=True, blank=True, validators=[MinValueValidator(2)]
    )
    matches_per_team = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )
    total_matches = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )
    advancing_count = models.PositiveSmallIntegerField(null=True, blank=True)
    scramble_rounds = models.PositiveSmallIntegerField(
        "rounds", null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Scramble only. How many rounds to play.",
    )
    schedule_seed = models.PositiveIntegerField(
        null=True, blank=True, help_text="Set when the schedule is published. Same seed, same schedule."
    )

    status =models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    player_code = models.CharField(max_length=12, unique=True)
    player_code_enabled = models.BooleanField(default=True)
    spectator_code = models.CharField(max_length=12, unique=True)
    spectator_code_enabled = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        from .codes import new_code

        if not self.player_code:
            self.player_code = new_code()
        if not self.spectator_code:
            self.spectator_code = new_code()
        super().save(*args, **kwargs)

    @property
    def is_scramble(self) -> bool:
        return self.division.is_scramble

    @property
    def players_per_side(self) -> int:
        return 1 if self.is_scramble else 2

    @property
    def player_capacity(self) -> int:
        """Most players who can register. Doubles events stop at two per team slot."""
        cap = self.max_participants
        if not self.is_scramble and self.team_count:
            cap = min(cap, self.team_count * 2)
        return cap

    @property
    def is_multi_week(self) -> bool:
        return self.weeks > 1

    @property
    def has_schedule(self) -> bool:
        return self.rounds.exists()

    @property
    def schedule_locked(self) -> bool:
        """Once play starts the schedule is never regenerated (section 6)."""
        return self.status not in (self.Status.DRAFT, self.Status.OPEN)


class Registration(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="registrations")
    player = models.ForeignKey(
        "accounts.Player", on_delete=models.CASCADE, related_name="registrations"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    pool = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["player__last_name", "player__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["event", "player"], name="one_registration_per_event")
        ]

    def __str__(self):
        return f"{self.player} in {self.event}"


class Side(models.Model):
    """One or two players on one end of a match. A persistent team for doubles."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="sides")
    players = models.ManyToManyField("accounts.Player", related_name="sides")
    team_code = models.CharField(max_length=12, unique=True, null=True, blank=True)
    # Team number in the schedule, 1 and up. Set when the schedule is published.
    # Blank for unscheduled teams and for Scramble's per-round sides.
    slot = models.PositiveSmallIntegerField(null=True, blank=True)
    pool = models.PositiveSmallIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.Player", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slot", "id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "slot"], name="one_side_per_slot"),
        ]

    def __str__(self):
        return self.name

    @property
    def name(self) -> str:
        names = [p.full_name for p in self.players.all()]
        if names:
            return " & ".join(names)
        return f"Team {self.slot} (open spot)" if self.slot else "Empty team"

    @property
    def is_scheduled(self) -> bool:
        return self.slot is not None


class TeamInvite(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        CANCELLED = "CANCELLED", "Cancelled"

    side = models.ForeignKey(Side, on_delete=models.CASCADE, related_name="invites")
    player = models.ForeignKey(
        "accounts.Player", on_delete=models.CASCADE, related_name="team_invites"
    )
    invited_by = models.ForeignKey(
        "accounts.Player", on_delete=models.CASCADE, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
