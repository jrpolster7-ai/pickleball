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
    label = models.CharField(max_length=40, blank=True, help_text="Bracket rounds, like 'Semifinals'.")

    class Meta:
        ordering = ["session__week", "number"]
        constraints = [models.UniqueConstraint(fields=["session", "number"], name="one_round_number_per_session")]

    def __str__(self):
        return self.label or f"Round {self.number}"


class Match(models.Model):
    class Stage(models.TextChoices):
        ROUND_ROBIN = "ROUND_ROBIN", "Round robin"
        BRACKET = "BRACKET", "Bracket"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Not played yet"
        PENDING = "PENDING", "Waiting for confirmation"
        DISPUTED = "DISPUTED", "Organizer asked"
        CONFIRMED = "CONFIRMED", "Final"

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="matches")
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="matches")
    court = models.PositiveSmallIntegerField()
    start_time = models.DateTimeField()
    # Bracket matches can wait for teams, so sides may be empty until earlier matches finish.
    side_a = models.ForeignKey("events.Side", null=True, blank=True, on_delete=models.PROTECT, related_name="matches_as_a")
    side_b = models.ForeignKey("events.Side", null=True, blank=True, on_delete=models.PROTECT, related_name="matches_as_b")
    stage = models.CharField(max_length=12, choices=Stage.choices, default=Stage.ROUND_ROBIN, db_index=True)
    pool = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    winner = models.CharField(max_length=1, blank=True, help_text="A or B once the score is final.")
    forfeit = models.BooleanField(default=False)

    # Bracket fields (section 16). Round 0 is the play-in or opening round.
    bracket_round = models.PositiveSmallIntegerField(null=True, blank=True)
    bracket_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    bracket_side = models.CharField(
        max_length=8, blank=True,
        choices=[("WINNERS", "Winners"), ("LOSERS", "Losers"), ("FINAL", "Grand final")],
    )
    bracket_label = models.CharField(max_length=40, blank=True)
    third_place = models.BooleanField(default=False)
    feed_a = models.CharField(max_length=60, blank=True, help_text="Shown until side A is known.")
    feed_b = models.CharField(max_length=60, blank=True, help_text="Shown until side B is known.")
    winner_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    winner_to_side = models.CharField(max_length=1, blank=True)
    loser_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    loser_to_side = models.CharField(max_length=1, blank=True)

    class Meta:
        ordering = ["round__session__week", "round__number", "court"]
        verbose_name_plural = "matches"

    def __str__(self):
        if self.bracket_label:
            return f"{self.bracket_label} {self.bracket_slot}" if not self.third_place else self.bracket_label
        return f"{self.round}, court {self.court}"

    @property
    def label_a(self) -> str:
        return self.side_a.name if self.side_a_id else (self.feed_a or "To be decided")

    @property
    def label_b(self) -> str:
        return self.side_b.name if self.side_b_id else (self.feed_b or "To be decided")

    @property
    def is_ready(self) -> bool:
        return bool(self.side_a_id and self.side_b_id)

    @property
    def winning_side(self):
        return {"A": self.side_a, "B": self.side_b}.get(self.winner)

    @property
    def losing_side(self):
        return {"A": self.side_b, "B": self.side_a}.get(self.winner)

    @property
    def is_final(self) -> bool:
        return self.status == self.Status.CONFIRMED

    @property
    def score(self) -> str:
        """'11-7, 9-11, 11-5', using prefetched games when there are any."""
        return ", ".join(f"{g.side_a_points}-{g.side_b_points}" for g in self.games.all())

    def side_letter(self, side) -> str | None:
        if side is None:
            return None
        if side.pk == self.side_a_id:
            return "A"
        if side.pk == self.side_b_id:
            return "B"
        return None

    @property
    def pool_label(self) -> str:
        from .services import pool_name

        return pool_name(self.pool - 1) if self.pool else ""
