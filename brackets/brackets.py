"""Single elimination brackets (CLAUDE.md section 9). Pure Python, no database.

Seeds are numbered 1..n, best first. The main bracket is the largest power
of 2 that fits (P). When n isn't a power of 2, the k = n - P extra teams
play opening matches for the last spots, cutoff pair first (DECIDED with
Joe): seed P plays P+1, then P-1 plays P+2, and so on. The winner takes the
higher seed's spot.

The two sizing options give the same matchups:
  - Play-in matches: the opening matches are a "Play-in" round before Round 1.
  - Top seed byes: the same matches are "Round 1" of a bracket twice as big,
    and the top seeds skip it (a bye).
Only the round names differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field

A, B = "A", "B"


class BracketError(ValueError):
    """A friendly message explaining why the bracket can't be built."""


@dataclass(frozen=True)
class Feed:
    """Where a side of a bracket match comes from."""

    kind: str  # "seed", "winner", or "loser"
    value: int  # the seed number, or the key of the earlier match

    @classmethod
    def seed(cls, n: int) -> "Feed":
        return cls("seed", n)

    @classmethod
    def winner(cls, key: int) -> "Feed":
        return cls("winner", key)

    @classmethod
    def loser(cls, key: int) -> "Feed":
        return cls("loser", key)


@dataclass
class BracketMatch:
    key: int            # unique within the bracket, in play order
    round: int          # 0 is the opening (play-in) round; 1 and up is the main bracket
    position: int       # 1-based, top to bottom within the round
    a: Feed
    b: Feed
    label: str          # round name, like "Semifinals"
    third_place: bool = False
    winner_to: tuple[int, str] | None = None  # (match key, "A" or "B")
    loser_to: tuple[int, str] | None = None


@dataclass
class Bracket:
    team_count: int
    size: int  # main bracket size, a power of 2
    play_in: bool
    matches: list[BracketMatch] = field(default_factory=list)

    def by_key(self) -> dict[int, BracketMatch]:
        return {m.key: m for m in self.matches}

    def rounds(self) -> list[tuple[str, list[BracketMatch]]]:
        """(name, matches) in play order. Third place comes last."""
        out: dict[tuple, list] = {}
        for m in self.matches:
            out.setdefault((m.round, m.third_place, m.label), []).append(m)
        return [(label, ms) for (_, _, label), ms in sorted(out.items(), key=lambda kv: (kv[0][0], kv[0][1]))]


def is_power_of_two(n: int) -> bool:
    return n >= 1 and n & (n - 1) == 0


def main_size(n: int) -> int:
    """Largest power of 2 that is at most n."""
    return 1 << (n.bit_length() - 1)


def seed_positions(size: int) -> list[int]:
    """Standard bracket order, so 1 and 2 can only meet in the final.

    For 8: [1, 8, 4, 5, 2, 7, 3, 6], read in pairs: 1v8, 4v5, 2v7, 3v6.
    """
    order = [1]
    while len(order) < size:
        span = len(order) * 2 + 1
        order = [s for x in order for s in (x, span - x)]
    return order


def opening_pairs(n: int) -> list[tuple[int, int]]:
    """The extra teams' matches, cutoff pair first: (P, P+1), (P-1, P+2), ..."""
    size = main_size(n)
    return [(size - i, size + 1 + i) for i in range(n - size)]


def round_name(teams_left: int, number: int) -> str:
    return {2: "Final", 4: "Semifinals", 8: "Quarterfinals"}.get(teams_left, f"Round {number}")


def single_elimination(n: int, *, play_in: bool, third_place: bool) -> Bracket:
    if n < 2:
        raise BracketError("A bracket needs at least 2 teams.")
    size = main_size(n)
    bracket = Bracket(team_count=n, size=size, play_in=play_in)
    keys = iter(range(1, 10**6))
    opening = opening_pairs(n)
    # Round numbers people see: with byes, the opening matches are Round 1.
    shift = 1 if opening and not play_in else 0

    feed_for_seed: dict[int, Feed] = {}
    opening_matches = {}
    for position, (high, low) in enumerate(sorted(opening, key=lambda p: seed_positions(size).index(p[0])), start=1):
        m = BracketMatch(key=next(keys), round=0, position=position, a=Feed.seed(high), b=Feed.seed(low),
                         label="Play-in" if play_in else "Round 1")
        bracket.matches.append(m)
        opening_matches[high] = m
        feed_for_seed[high] = Feed.winner(m.key)

    # Main bracket, round by round.
    order = seed_positions(size)
    current: list[Feed] = [feed_for_seed.get(s, Feed.seed(s)) for s in order]
    round_number = 1
    semis: list[BracketMatch] = []
    while len(current) > 1:
        teams_left = len(current)
        label = round_name(teams_left, round_number + shift)
        next_feeds = []
        made = []
        for position in range(teams_left // 2):
            a, b = current[2 * position], current[2 * position + 1]
            m = BracketMatch(key=next(keys), round=round_number, position=position + 1, a=a, b=b, label=label)
            bracket.matches.append(m)
            made.append(m)
            next_feeds.append(Feed.winner(m.key))
        if teams_left == 4:
            semis = made
        current = next_feeds
        round_number += 1

    final = bracket.matches[-1]
    if third_place and len(semis) == 2:
        third = BracketMatch(key=next(keys), round=final.round, position=2, a=Feed.loser(semis[0].key),
                             b=Feed.loser(semis[1].key), label="Third place", third_place=True)
        bracket.matches.append(third)

    # Link each match to where its winner (and, for semis, loser) goes.
    by_key = bracket.by_key()
    for m in bracket.matches:
        for side, feed in ((A, m.a), (B, m.b)):
            if feed.kind == "winner":
                by_key[feed.value].winner_to = (m.key, side)
            elif feed.kind == "loser":
                by_key[feed.value].loser_to = (m.key, side)
    return bracket


def feed_label(feed: Feed, bracket: Bracket) -> str:
    """What to show before a side is known, like 'Winner of Semifinal 1'."""
    if feed.kind == "seed":
        return f"Seed {feed.value}"
    m = bracket.by_key()[feed.value]
    name = {"Semifinals": "Semifinal", "Quarterfinals": "Quarterfinal"}.get(m.label, m.label)
    word = "Winner" if feed.kind == "winner" else "Loser"
    if name.startswith("Round"):
        return f"{word} of {name}, match {m.position}"
    return f"{word} of {name} {m.position}"
