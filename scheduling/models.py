from django.db import models


class Session(models.Model):
    """One play date. A one-day event has one; a 4-week league has four."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="sessions")
    week = models.PositiveSmallIntegerField()
    date = models.DateField()

    class Meta:
        ordering = ["week"]
        constraints = [models.UniqueConstraint(fields=["event", "week"], name="one_session_per_week")]

    def __str__(self):
        return f"Week {self.week} ({self.date})"


class Round(models.Model):
    """One time slot. Numbered within its session."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="rounds")
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="rounds")
    number = models.PositiveSmallIntegerField()
    start_time = models.DateTimeField()

    class Meta:
        ordering = ["session__week", "number"]
        constraints = [models.UniqueConstraint(fields=["session", "number"], name="one_round_number_per_session")]

    def __str__(self):
        return f"Round {self.number}"


class Match(models.Model):
    class Stage(models.TextChoices):
        ROUND_ROBIN = "ROUND_ROBIN", "Round robin"
        BRACKET = "BRACKET", "Bracket"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="matches")
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="matches")
    court = models.PositiveSmallIntegerField()
    start_time = models.DateTimeField()
    side_a = models.ForeignKey("events.Side", on_delete=models.PROTECT, related_name="matches_as_a")
    side_b = models.ForeignKey("events.Side", on_delete=models.PROTECT, related_name="matches_as_b")
    stage = models.CharField(max_length=12, choices=Stage.choices, default=Stage.ROUND_ROBIN)
    pool = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)

    class Meta:
        ordering = ["round__session__week", "round__number", "court"]
        verbose_name_plural = "matches"

    def __str__(self):
        return f"{self.round}, court {self.court}"

    @property
    def pool_label(self) -> str:
        from .services import pool_name

        return pool_name(self.pool - 1) if self.pool else ""
