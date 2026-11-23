from django import forms

from scheduling.models import Match

from . import rules
from .rules import GameRules

POINTS = {"inputmode": "numeric", "min": 0, "class": "text-center text-lg font-semibold"}


class ScoreForm(forms.Form):
    """Game-by-game score entry. One row per game, side A and side B points.

    Best of 3 shows three rows. Leave game 3 empty if it wasn't needed.
    """

    def __init__(self, *args, match: Match, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match
        self.rules = GameRules.from_event(match.event)
        for number in range(1, self.rules.games_per_match + 1):
            for side in ("a", "b"):
                self.fields[f"g{number}_{side}"] = forms.IntegerField(
                    min_value=0, max_value=99, required=False,
                    label=f"Game {number}, {'side A' if side == 'a' else 'side B'}",
                    widget=forms.NumberInput(attrs={**POINTS, "aria-label": f"Game {number} points for "
                                                    f"{match.side_a.name if side == 'a' else match.side_b.name}"}),
                )

    def rows(self):
        """(number, side A field, side B field, optional) for the template."""
        return [
            (n, self[f"g{n}_a"], self[f"g{n}_b"], n > self.rules.games_to_win)
            for n in range(1, self.rules.games_per_match + 1)
        ]

    def clean(self):
        data = super().clean()
        games = []
        gap = False
        for number in range(1, self.rules.games_per_match + 1):
            a, b = data.get(f"g{number}_a"), data.get(f"g{number}_b")
            if a is None and b is None:
                gap = True
                continue
            if a is None or b is None:
                raise forms.ValidationError(f"Game {number}: enter points for both sides.")
            if gap:
                raise forms.ValidationError(f"Game {number - 1} is empty. Enter the games in order.")
            games.append((a, b))
        problem = rules.match_problem(games, self.rules)
        if problem:
            raise forms.ValidationError(problem)
        data["games"] = games
        return data

    @staticmethod
    def initial_for(games) -> dict:
        initial = {}
        for number, (a, b) in enumerate(games, start=1):
            initial[f"g{number}_a"] = a
            initial[f"g{number}_b"] = b
        return initial


class ForfeitForm(forms.Form):
    side = forms.ChoiceField(choices=[("A", "Side A"), ("B", "Side B")], label="Who forfeits?",
                             widget=forms.RadioSelect)

    def __init__(self, *args, match: Match, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["side"].choices = [("A", match.side_a.name), ("B", match.side_b.name)]
