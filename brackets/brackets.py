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
WINNERS, LOSERS, FINAL = "WINNERS", "LOSERS", "FINAL"
SIDE_ORDER = {WINNERS: 0, LOSERS: 1, FINAL: 2}


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
    side: str = WINNERS  # WINNERS, LOSERS, or FINAL (double elimination's grand final)
    wave: int = 0        # time order: a match can start once its feeding matches are done


@dataclass
class Bracket:
    team_count: int
    size: int  # main bracket size, a power of 2
    play_in: bool
    matches: list[BracketMatch] = field(default_factory=list)
    double: bool = False

    def by_key(self) -> dict[int, BracketMatch]:
        return {m.key: m for m in self.matches}

    def rounds(self) -> list[tuple[str, list[BracketMatch]]]:
        """(name, matches) in play order: winners, then losers, then the grand final. Third place last."""
        out: dict[tuple, list] = {}
        for m in self.matches:
            out.setdefault((SIDE_ORDER[m.side], m.round, m.third_place, m.label), []).append(m)
        return [(key[3], ms) for key, ms in sorted(out.items(), key=lambda kv: kv[0][:3])]

    def sections(self) -> list[tuple[str, list[tuple[str, list[BracketMatch]]]]]:
        """[(section name, rounds)]. Single elimination is one unnamed section."""
        if not self.double:
            return [("", self.rounds())]
        names = {WINNERS: "Winners bracket", LOSERS: "Losers bracket", FINAL: "Grand final"}
        out = []
        for side in (WINNERS, LOSERS, FINAL):
            rounds = [(label, ms) for label, ms in self.rounds() if ms[0].side == side]
            if rounds:
                out.append((names[side], rounds))
        return out


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

    _link(bracket)
    _assign_waves(bracket)
    return bracket


def _link(bracket: Bracket) -> None:
    """Point each match at where its winner (and loser, if they play on) goes next."""
    by_key = bracket.by_key()
    for m in bracket.matches:
        for side, feed in ((A, m.a), (B, m.b)):
            if feed.kind == "winner":
                by_key[feed.value].winner_to = (m.key, side)
            elif feed.kind == "loser":
                by_key[feed.value].loser_to = (m.key, side)


def _assign_waves(bracket: Bracket) -> None:
    """Time order for scheduling. Rounds in the same wave can share a time slot.

    A whole round plays together: it comes after every match feeding it, and
    after the round before it on the same side of the bracket.
    """
    by_key = bracket.by_key()
    groups: dict[tuple, list[BracketMatch]] = {}
    for m in bracket.matches:  # matches are listed after everything that feeds them
        groups.setdefault((m.side, m.round), []).append(m)
    last_on_side: dict[str, int] = {}
    for (side, _), ms in groups.items():
        wave = last_on_side.get(side, 0) + 1
        for m in ms:
            feeders = [by_key[f.value].wave for f in (m.a, m.b) if f.kind in ("winner", "loser")]
            wave = max(wave, 1 + max(feeders, default=0))
        for m in ms:
            m.wave = wave
        last_on_side[side] = wave


# --- Double elimination -----------------------------------------------------

BYE = Feed("bye", 0)


def double_elimination(n: int, *, play_in: bool) -> Bracket:
    """Winners and losers brackets, then a grand final (section 9).

    Everyone is out after two losses. When n isn't a power of 2, the bracket
    is sized up to the next power of 2 and the top seeds get byes. Opening
    round losers drop into the losers bracket like anyone else (DECIDED with
    Joe). Matches against a bye are folded away, so only real matches remain.

    The grand final reset (ASSUMED) isn't listed here. It's only played if
    the losers bracket winner wins the grand final, so the database adds it
    when that happens.
    """
    if n < 2:
        raise BracketError("A bracket needs at least 2 teams.")
    size = n if is_power_of_two(n) else 2 * main_size(n)
    levels = size.bit_length() - 1
    raw: list[BracketMatch] = []
    keys = iter(range(1, 10**6))

    def new(side, rnd, a, b):
        m = BracketMatch(key=next(keys), round=rnd, position=0, a=a, b=b, label="", side=side)
        raw.append(m)
        return m

    def pair_up(side, rnd, feeds):
        made = [new(side, rnd, feeds[2 * i], feeds[2 * i + 1]) for i in range(len(feeds) // 2)]
        return made, [Feed.winner(m.key) for m in made]

    # Winners bracket: the usual seeded bracket, byes for seeds that don't exist.
    current = [Feed.seed(s) if s <= n else BYE for s in seed_positions(size)]
    winners_rounds = []
    for r in range(1, levels + 1):
        made, current = pair_up(WINNERS, r, current)
        winners_rounds.append(made)
    winners_champion = current[0]

    # Losers bracket: first-round losers play each other, then each later
    # winners round drops its losers in. Drops cross over every other round
    # so teams don't meet again right away.
    lb_round = 0
    drops = [Feed.loser(m.key) for m in winners_rounds[0]]
    if len(drops) >= 2:
        lb_round += 1
        _, survivors = pair_up(LOSERS, lb_round, drops)
    else:
        survivors = drops
    for r in range(2, levels + 1):
        drops = [Feed.loser(m.key) for m in winners_rounds[r - 1]]
        if r % 2 == 0:
            drops.reverse()
        lb_round += 1
        made = [new(LOSERS, lb_round, survivors[i], drops[i]) for i in range(len(drops))]
        survivors = [Feed.winner(m.key) for m in made]
        if len(survivors) > 1:
            lb_round += 1
            _, survivors = pair_up(LOSERS, lb_round, survivors)
    grand_final = new(FINAL, 1, winners_champion, survivors[0])

    # Fold away matches against a bye: the real team moves straight on.
    replace: dict[tuple[str, int], Feed] = {}

    def resolve(feed: Feed) -> Feed:
        while (feed.kind, feed.value) in replace:
            feed = replace[(feed.kind, feed.value)]
        return feed

    kept = []
    for m in raw:
        m.a, m.b = resolve(m.a), resolve(m.b)
        if BYE in (m.a, m.b):
            replace[("winner", m.key)] = m.b if m.a == BYE else m.a
            replace[("loser", m.key)] = BYE
            continue
        kept.append(m)

    bracket = Bracket(team_count=n, size=main_size(n), play_in=play_in, matches=kept, double=True)
    _name_double_rounds(bracket, opening=size != n)
    _link(bracket)
    _assign_waves(bracket)
    grand_final.label = "Grand final"
    return bracket


def _name_double_rounds(bracket: Bracket, *, opening: bool) -> None:
    """Renumber rounds and positions after byes are folded away, and name them."""
    for side in (WINNERS, LOSERS, FINAL):
        rounds = sorted({m.round for m in bracket.matches if m.side == side})
        for number, old in enumerate(rounds, start=1):
            ms = [m for m in bracket.matches if m.side == side and m.round == old]
            for position, m in enumerate(ms, start=1):
                m.round = number
                m.position = position
                if side == FINAL:
                    m.label = "Grand final"
                elif number == len(rounds):
                    m.label = "Winners final" if side == WINNERS else "Losers final"
                elif side == LOSERS:
                    m.label = f"Losers round {number}"
                elif opening and number == 1:
                    m.label = "Play-in" if bracket.play_in else "Winners round 1"
                else:
                    shown = number - 1 if opening and bracket.play_in else number
                    m.label = f"Winners round {shown}"


def feed_label(feed: Feed, bracket: Bracket) -> str:
    """What to show before a side is known, like 'Winner of Semifinal 1'."""
    if feed.kind == "seed":
        return f"Seed {feed.value}"
    m = bracket.by_key()[feed.value]
    name = {"Semifinals": "Semifinal", "Quarterfinals": "Quarterfinal"}.get(m.label, m.label)
    word = "Winner" if feed.kind == "winner" else "Loser"
    if "round" in name.lower():
        return f"{word} of {name}, match {m.position}"
    if name.endswith("final") and name != "Semifinal" and name != "Quarterfinal":
        return f"{word} of the {name.lower()}"
    return f"{word} of {name} {m.position}"
