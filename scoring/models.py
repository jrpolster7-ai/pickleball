from django.db import models


class Game(models.Model):
    """One game of an official match result. Written only when a score is final."""

    match = models.ForeignKey("scheduling.Match", on_delete=models.CASCADE, related_name="games")
    number = models.PositiveSmallIntegerField()
    side_a_points = models.PositiveSmallIntegerField()
    side_b_points = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["match", "number"], name="one_game_number_per_match")]

    def __str__(self):
        return f"Game {self.number}: {self.side_a_points}-{self.side_b_points}"


class ScoreSubmission(models.Model):
    """A score typed in by a player. The other side confirms it, or disagrees."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting for the other side"
        CONFIRMED = "CONFIRMED", "Confirmed"
        DISPUTED = "DISPUTED", "Sides disagree"
        SUPERSEDED = "SUPERSEDED", "Replaced by a newer entry"
        RESOLVED = "RESOLVED", "Settled by an organizer"

    class Side(models.TextChoices):
        A = "A", "Side A"
        B = "B", "Side B"

    match = models.ForeignKey("scheduling.Match", on_delete=models.CASCADE, related_name="submissions")
    side = models.CharField(max_length=1, choices=Side.choices)
    games = models.JSONField(help_text="List of [side A points, side B points], one per game.")
    submitted_by = models.ForeignKey("accounts.Player", on_delete=models.PROTECT, related_name="+")
    confirmed_by = models.ForeignKey(
        "accounts.Player", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_side_display()}: {self.score}"

    @property
    def game_list(self) -> list[tuple[int, int]]:
        return [(int(a), int(b)) for a, b in self.games]

    @property
    def score(self) -> str:
        from .rules import score_text

        return score_text(self.game_list)
