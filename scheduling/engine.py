"""The scheduling engine (CLAUDE.md section 6). Pure Python, no database.

Teams are numbered 0..n-1 ("slots"). Scramble players are numbered the same way.
Everything that uses randomness takes a seed, so the same inputs and the same
seed always give the same schedule.

How a fixed-partner round robin is built:
1. Pick which matchups happen (`choose_pairs`). Full cycles of everyone-plays-
   everyone first, then a partial cycle ordered so every prefix keeps each
   team's match count within one of every other team's.
2. Pack the matchups into rounds (`pack_rounds`). A round holds at most one
   match per court and never has a team twice.
"""

from __future__ import annotations

import datetime
import math
import random
from dataclasses import dataclass, field
from itertools import zip_longest

Pair = tuple[int, int]


class ScheduleError(ValueError):
    """A friendly message explaining why a schedule can't be made."""


# --- Picking matchups ------------------------------------------------------

def circle_rounds(n: int) -> list[list[Pair]]:
    """One full round robin by the circle method.

    Returns n-1 rounds for even n, n rounds for odd n. With an odd count one
    team has a bye each round, and the bye moves to a new team every round.
    """
    if n < 2:
        return []
    slots: list[int | None] = list(range(n))
    if n % 2:
        slots.append(None)  # the bye
    m = len(slots)
    rounds = []
    for _ in range(m - 1):
        pairs = []
        for i in range(m // 2):
            a, b = slots[i], slots[m - 1 - i]
            if a is not None and b is not None:
                pairs.append((min(a, b), max(a, b)))
        rounds.append(pairs)
        # Keep the first slot fixed, rotate the rest one step.
        slots = [slots[0], slots[-1], *slots[1:-1]]
    return rounds


def _walecki_cycles(n: int) -> list[list[int]]:
    """For odd n, split everyone-plays-everyone into (n-1)/2 loops through all teams."""
    m = (n - 1) // 2
    hub = n - 1
    size = 2 * m
    cycles = []
    for i in range(m):
        order = [i]
        for k in range(1, m + 1):
            order.append((i + k) % size)
            if len(order) < size:
                order.append((i - k) % size)
        cycles.append([hub, *order])
    return cycles


def partial_cycle_order(n: int) -> list[Pair]:
    """Every matchup once, ordered so any prefix is balanced.

    Taking the first r pairs leaves no team more than one match ahead of any
    other, and never repeats a pair. This is what fills a partial cycle.
    """
    if n < 2:
        return []
    if n % 2 == 0:
        # Each circle round is a perfect matching, so prefixes stay balanced.
        return [p for rnd in circle_rounds(n) for p in rnd]
    ordered = []
    for cycle in _walecki_cycles(n):
        edges = [(cycle[i], cycle[(i + 1) % n]) for i in range(n)]
        # Every other edge first (a matching that misses one team), then the
        # edge that reaches the missed team, then the rest.
        picks = edges[0:n - 1:2] + [edges[n - 1]] + edges[1:n - 1:2]
        ordered.extend((min(a, b), max(a, b)) for a, b in picks)
    return ordered


def choose_pairs(n: int, total: int) -> list[list[Pair]]:
    """Which matchups happen, as groups the packer keeps in order.

    Full round robins repeat as many times as fit. Any leftover matches come
    from one more partial cycle, spread so match counts differ by at most one
    and repeat opponents stay as even as possible.
    """
    if n < 2:
        raise ScheduleError("A round robin needs at least 2 teams.")
    if total < 1:
        return []
    cycle = n * (n - 1) // 2
    full, extra = divmod(total, cycle)
    groups: list[list[Pair]] = []
    for _ in range(full):
        groups.extend(circle_rounds(n))
    if extra:
        partial = partial_cycle_order(n)[:extra]
        groups.append(partial)
    return groups


# --- Packing into rounds ---------------------------------------------------

def pack_rounds(pairs: list[Pair], courts: int) -> list[list[Pair]]:
    """Put matchups into rounds, in order, one per court, no team twice per round.

    A round takes the earliest matchups that still fit. When there are more
    matches than courts, the rest move to the next round.
    """
    if courts < 1:
        raise ScheduleError("Use at least 1 court.")
    remaining = list(pairs)
    rounds: list[list[Pair]] = []
    while remaining:
        busy: set[int] = set()
        taken: list[int] = []
        for i, (a, b) in enumerate(remaining):
            if a in busy or b in busy:
                continue
            busy.update((a, b))
            taken.append(i)
            if len(taken) == courts:
                break
        rounds.append([remaining[i] for i in taken])
        skip = set(taken)
        last = taken[-1]
        remaining = [p for i, p in enumerate(remaining[:last + 1]) if i not in skip] + remaining[last + 1:]
    return rounds


# --- Pools -----------------------------------------------------------------

def pool_count(n: int, pool_size: int | None) -> int:
    """How many pools. ASSUMED: enough pools that none is bigger than pool_size."""
    if not pool_size or pool_size >= n:
        return 1
    return math.ceil(n / pool_size)


def snake_pools(n: int, pools: int) -> list[list[int]]:
    """Snake-seed slots 0..n-1 into pools: A B C, C B A, A B C, ..."""
    result: list[list[int]] = [[] for _ in range(pools)]
    for seed in range(n):
        lap, pos = divmod(seed, pools)
        index = pos if lap % 2 == 0 else pools - 1 - pos
        result[index].append(seed)
    return result


# --- Round robin plan ------------------------------------------------------

@dataclass(frozen=True)
class PlannedMatch:
    court: int  # 1-based
    a: int      # team slot
    b: int
    pool: int   # 0-based


@dataclass
class RoundRobinPlan:
    team_count: int
    pools: list[list[int]]
    rounds: list[list[PlannedMatch]]
    matches_per_team: dict[int, int] = field(default_factory=dict)

    @property
    def total_matches(self) -> int:
        return sum(len(r) for r in self.rounds)

    def byes_per_team(self) -> dict[int, int]:
        """Rounds each team sits out."""
        played = {t: 0 for t in range(self.team_count)}
        for rnd in self.rounds:
            for m in rnd:
                played[m.a] += 1
                played[m.b] += 1
        return {t: len(self.rounds) - c for t, c in played.items()}


def round_robin(
    n: int,
    *,
    courts: int,
    total: int | None = None,
    per_team: int | None = None,
    pool_size: int | None = None,
    seed: int = 1,
) -> RoundRobinPlan:
    """Build the round robin for n teams.

    Without pools, `total` sets the match count (or `per_team` if total is not
    given). With pools, each pool plays `per_team` matches per team, and the
    pool's total is rounded up the same way as section 4 (ASSUMED).
    """
    if n < 2:
        raise ScheduleError("A round robin needs at least 2 teams.")
    if total is None and per_team is None:
        raise ScheduleError("Set matches per team or total matches.")
    rng = random.Random(seed)
    pools = snake_pools(n, pool_count(n, pool_size))
    if len(pools) > 1 and per_team is None:
        per_team = (2 * total) // n

    pool_groups: list[list[list[Pair]]] = []
    for members in pools:
        size = len(members)
        if size < 2:
            raise ScheduleError("Every pool needs at least 2 teams. Try a bigger pool size.")
        if len(pools) == 1 and total is not None:
            pool_total = total
        else:
            pool_total = math.ceil(size * per_team / 2)
        # Shuffle who sits where on the circle, so a new seed gives new matchups.
        positions = members[:]
        rng.shuffle(positions)
        groups = choose_pairs(size, pool_total)
        pool_groups.append([[(positions[a], positions[b]) for a, b in g] for g in groups])

    # Interleave pools a round at a time so every pool gets courts early on.
    flat: list[tuple[Pair, int]] = []
    for layer in zip_longest(*pool_groups):
        for pool_index, group in enumerate(layer):
            for pair in group or []:
                flat.append((pair, pool_index))
    pool_of = {}
    for index, members in enumerate(pools):
        for t in members:
            pool_of[t] = index

    packed = pack_rounds([p for p, _ in flat], courts)
    rounds = [
        [PlannedMatch(court=i + 1, a=a, b=b, pool=pool_of[a]) for i, (a, b) in enumerate(rnd)]
        for rnd in packed
    ]
    counts = {t: 0 for t in range(n)}
    for rnd in rounds:
        for m in rnd:
            counts[m.a] += 1
            counts[m.b] += 1
    return RoundRobinPlan(team_count=n, pools=pools, rounds=rounds, matches_per_team=counts)


def full_round_robin_rounds(n: int) -> int:
    """Rounds in one full round robin with enough courts. For reference only."""
    return 0 if n < 2 else (n - 1 if n % 2 == 0 else n)


# --- Multi-week ------------------------------------------------------------

def week_round_orders(round_count: int, weeks: int, seed: int = 1) -> list[list[int]]:
    """Round order for each week. Week 1 is as generated; later weeks shuffle it.

    Every week has the same matchups (section 6). Only the order changes.
    """
    rng = random.Random(f"weeks-{seed}")
    orders = [list(range(round_count))]
    for _ in range(1, weeks):
        order = list(range(round_count))
        rng.shuffle(order)
        orders.append(order)
    return orders


# --- Scramble --------------------------------------------------------------

Foursome = tuple[Pair, Pair]  # (side A players, side B players)


@dataclass
class ScramblePlan:
    player_count: int
    rounds: list[list[Foursome]]

    def games_per_player(self) -> dict[int, int]:
        counts = {p: 0 for p in range(self.player_count)}
        for rnd in self.rounds:
            for side_a, side_b in rnd:
                for p in (*side_a, *side_b):
                    counts[p] += 1
        return counts

    def sit_outs_per_player(self) -> dict[int, int]:
        played = self.games_per_player()
        return {p: len(self.rounds) - c for p, c in played.items()}


_SPLITS = (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2)))
_PARTNER_WEIGHT = 3  # a repeat partner is worse than a repeat opponent
_TRIES = 24


def scramble(player_count: int, *, rounds: int, courts: int, seed: int = 1) -> ScramblePlan:
    """Group players into foursomes, two against two, one game per court each round.

    Players who sit out rotate fairly: whoever has played least plays next, so
    games played never differ by more than one. Within a round, groupings try
    to give everyone new partners first, then new opponents.
    """
    if player_count < 4:
        raise ScheduleError("Scramble needs at least 4 players.")
    if rounds < 1:
        raise ScheduleError("Set at least 1 round.")
    if courts < 1:
        raise ScheduleError("Use at least 1 court.")
    rng = random.Random(seed)
    games = min(courts, player_count // 4)
    partner = [[0] * player_count for _ in range(player_count)]
    opponent = [[0] * player_count for _ in range(player_count)]
    played = [0] * player_count
    plan: list[list[Foursome]] = []

    for _ in range(rounds):
        # Fewest games first. Random tie-break so sit-outs move around.
        order = list(range(player_count))
        rng.shuffle(order)
        order.sort(key=lambda p: played[p])
        playing = order[: games * 4]

        best: list[Foursome] | None = None
        best_cost = None
        for _try in range(_TRIES):
            pool = playing[:]
            rng.shuffle(pool)
            round_games: list[Foursome] = []
            cost = 0
            while pool:
                group = [pool.pop(0)]
                while len(group) < 4:
                    pick = min(
                        range(len(pool)),
                        key=lambda i: sum(
                            _PARTNER_WEIGHT * partner[pool[i]][g] + opponent[pool[i]][g] for g in group
                        ),
                    )
                    group.append(pool.pop(pick))
                split_cost, split = min(
                    (_split_cost(group, s, partner, opponent), s) for s in _SPLITS
                )
                (i1, i2), (j1, j2) = split
                round_games.append(((group[i1], group[i2]), (group[j1], group[j2])))
                cost += split_cost
            if best_cost is None or cost < best_cost:
                best, best_cost = round_games, cost
                if cost == 0:
                    break

        for (a1, a2), (b1, b2) in best:
            partner[a1][a2] += 1
            partner[a2][a1] += 1
            partner[b1][b2] += 1
            partner[b2][b1] += 1
            for x in (a1, a2):
                for y in (b1, b2):
                    opponent[x][y] += 1
                    opponent[y][x] += 1
            for p in (a1, a2, b1, b2):
                played[p] += 1
        plan.append(best)
    return ScramblePlan(player_count=player_count, rounds=plan)


def _split_cost(group, split, partner, opponent) -> int:
    (i1, i2), (j1, j2) = split
    a1, a2, b1, b2 = group[i1], group[i2], group[j1], group[j2]
    cost = _PARTNER_WEIGHT * (partner[a1][a2] + partner[b1][b2])
    cost += opponent[a1][b1] + opponent[a1][b2] + opponent[a2][b1] + opponent[a2][b2]
    return cost


# --- Times -----------------------------------------------------------------

def round_start_times(
    first: datetime.datetime, count: int, *, minutes_per_match: int, break_minutes: int
) -> list[datetime.datetime]:
    """Start time of each round: each round takes a match plus the break after it."""
    step = datetime.timedelta(minutes=minutes_per_match + break_minutes)
    return [first + step * i for i in range(count)]


def session_dates(start: datetime.date, weeks: int, weekly_day: int | None) -> list[datetime.date]:
    """Play dates. Week 1 is the first `weekly_day` on or after the start date."""
    first = start
    if weekly_day is not None and weeks > 1:
        first = start + datetime.timedelta(days=(weekly_day - start.weekday()) % 7)
    return [first + datetime.timedelta(weeks=w) for w in range(weeks)]
