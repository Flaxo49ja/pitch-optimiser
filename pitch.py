#!/usr/bin/env python3
"""pitch -- pick the best XI under a budget and draw it on the terminal.

Players are scored as  rating*10 + role_fit*2, where role_fit is the
position-weighted mean of the six attributes. The rating therefore dominates and
the attributes break ties between similarly rated players.

Selection is an exact 0/1 knapsack: pick exactly the number of defenders,
midfielders and forwards the formation demands, plus one keeper, for the highest
total score without exceeding the budget. No greedy shortcuts.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import unicodedata
from dataclasses import dataclass, field

import numpy as np

# True -inf, not -1e18: adding a score to a large negative sentinel can
# compare greater than the sentinel itself and poison the knapsack.
NEG = float("-inf")

# --- scoring model ---------------------------------------------------------

ATTRS = ("pace", "shooting", "passing", "dribbling", "defending", "physical")

# Weight per attribute, in the order of ATTRS.
POS_WEIGHTS: dict[str, tuple[float, ...]] = {
    "GK":  (0.02, 0.01, 0.10, 0.02, 0.55, 0.30),
    "CB":  (0.14, 0.02, 0.10, 0.05, 0.50, 0.19),
    "LB":  (0.28, 0.04, 0.20, 0.12, 0.26, 0.10),
    "RB":  (0.28, 0.04, 0.20, 0.12, 0.26, 0.10),
    "LWB": (0.30, 0.05, 0.22, 0.15, 0.20, 0.08),
    "RWB": (0.30, 0.05, 0.22, 0.15, 0.20, 0.08),
    "CDM": (0.06, 0.04, 0.28, 0.10, 0.36, 0.16),
    "CM":  (0.10, 0.12, 0.38, 0.18, 0.12, 0.10),
    "CAM": (0.10, 0.22, 0.32, 0.28, 0.03, 0.05),
    "LM":  (0.28, 0.12, 0.25, 0.22, 0.08, 0.05),
    "RM":  (0.28, 0.12, 0.25, 0.22, 0.08, 0.05),
    "LW":  (0.30, 0.20, 0.15, 0.28, 0.02, 0.05),
    "RW":  (0.30, 0.20, 0.15, 0.28, 0.02, 0.05),
    "ST":  (0.15, 0.40, 0.10, 0.20, 0.02, 0.13),
    "CF":  (0.12, 0.35, 0.18, 0.20, 0.03, 0.12),
}

GROUP_OF = {
    "GK": "GK",
    "CB": "DEF", "LB": "DEF", "RB": "DEF", "LWB": "DEF", "RWB": "DEF",
    "CDM": "MID", "CM": "MID", "CAM": "MID", "LM": "MID", "RM": "MID",
    "LW": "FWD", "RW": "FWD", "ST": "FWD", "CF": "FWD",
}

# name -> (defenders, midfielders, forwards); keeper is implicit.
FORMATIONS: dict[str, tuple[int, int, int]] = {
    "4-3-3": (4, 3, 3),
    "4-4-2": (4, 4, 2),
    "4-5-1": (4, 5, 1),
    "4-2-3-1": (4, 5, 1),
    "4-1-4-1": (4, 5, 1),
    "3-5-2": (3, 5, 2),
    "3-4-3": (3, 4, 3),
    "3-6-1": (3, 6, 1),
    "5-3-2": (5, 3, 2),
    "5-2-3": (5, 2, 3),
    "5-4-1": (5, 4, 1),
}


class InputError(Exception):
    """A problem with the caller's data or arguments."""


@dataclass
class Player:
    name: str
    pos: str
    club: str
    rating: int
    attrs: tuple[float, ...]
    price: float
    group: str = field(init=False)
    score: float = field(init=False)
    units: int = field(init=False)

    def __post_init__(self) -> None:
        self.group = GROUP_OF[self.pos]
        weights = POS_WEIGHTS[self.pos]
        total = sum(weights)
        self.score = self.rating * 10.0 + (sum(w * a for w, a in zip(weights, self.attrs)) / total) * 2.0
        self.units = int(round(self.price * 10))


# --- input -----------------------------------------------------------------

REQUIRED = ("name", "pos", "rating", "price")


def load_players(path: str) -> list[Player]:
    if not os.path.isfile(path):
        raise InputError(f"no such file: {path}")
    players: list[Player] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise InputError(f"{path}: empty file, expected a header row")
        header = {name.strip().lower(): name for name in reader.fieldnames}
        missing = [key for key in REQUIRED if key not in header]
        if missing:
            raise InputError(f"{path}: missing column(s): {', '.join(missing)}")
        for line_no, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            name = (row[header["name"]] or "").strip()
            pos = (row[header["pos"]] or "").strip().upper()
            if pos not in GROUP_OF:
                raise InputError(
                    f"{path}:{line_no}: unknown position {pos!r}. "
                    f"Valid: {', '.join(sorted(GROUP_OF))}"
                )
            if not name:
                raise InputError(f"{path}:{line_no}: empty name")
            try:
                rating = int(float(row[header["rating"]]))
                price = float(row[header["price"]])
            except (TypeError, ValueError):
                raise InputError(f"{path}:{line_no}: rating and price must be numbers") from None
            if not 0 < rating <= 100:
                raise InputError(f"{path}:{line_no}: rating {rating} outside 1..100")
            if price < 0:
                raise InputError(f"{path}:{line_no}: negative price")
            attrs = []
            for attr in ATTRS:
                raw = row.get(header.get(attr, "")) if attr in header else None
                if raw is None or not str(raw).strip():
                    attrs.append(60.0)  # neutral default keeps optional columns optional
                    continue
                try:
                    attrs.append(float(raw))
                except ValueError:
                    raise InputError(f"{path}:{line_no}: {attr} must be a number") from None
            club = (row.get(header.get("club", ""), "") or "").strip()
            players.append(Player(name, pos, club, rating, tuple(attrs), price))
    if not players:
        raise InputError(f"{path}: no players found")
    return players


# --- exact selection -------------------------------------------------------


def group_table(cands: list[Player], k_max: int, cap: int):
    """Best score for exactly k players at exactly cost c, plus take-decisions.

    Classic 0/1 knapsack over stages: take[i] records whether player i-1 was
    included in the best state at each (k, c), which makes reconstruction exact.
    """
    n = len(cands)
    dp = np.full((k_max + 1, cap + 1), NEG)
    dp[0, 0] = 0.0
    take = np.zeros((n + 1, k_max + 1, cap + 1), dtype=np.uint8)
    for i in range(1, n + 1):
        # Flags are NOT copied forward: a 1 means "player i-1 was added at this
        # stage", a 0 means "this state was inherited from the previous stage".
        player = cands[i - 1]
        w = player.units
        if w > cap:
            continue
        new = dp.copy()
        for k in range(k_max, 0, -1):
            prev = dp[k - 1]  # still the pre-player state: count descends
            cand = prev[: cap + 1 - w] + player.score
            target = new[k, w:]
            better = cand > target
            if better.any():
                target[better] = cand[better]
                take[i, k, w:][better] = 1
        dp = new
    return dp, take


def reconstruct(take, cands: list[Player], k: int, cost: int) -> tuple[list[Player], int]:
    chosen: list[Player] = []
    i = len(cands)
    while k > 0 and i > 0:
        if take[i, k, cost]:
            player = cands[i - 1]
            chosen.append(player)
            cost -= player.units
            k -= 1
        i -= 1
    return chosen, cost


@dataclass
class Lineup:
    players: list[Player]
    cost: float
    score: float
    omitted: list[Player]


def solve(
    players: list[Player],
    counts: dict[str, int],
    budget: float | None,
) -> Lineup:
    groups: dict[str, list[Player]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for player in players:
        groups[player.group].append(player)

    for group, need in counts.items():
        if need and len(groups[group]) < need:
            raise InputError(
                f"not enough {group} players: formation needs {need}, CSV has {len(groups[group])}"
            )

    if budget is None:
        chosen = [p for g, n in counts.items()
                  for p in sorted(groups[g], key=lambda p: p.score, reverse=True)[:n]]
        used = {id(p) for p in chosen}
        omitted = sorted((p for p in players if id(p) not in used),
                         key=lambda p: p.score, reverse=True)[:6]
        return Lineup(chosen, sum(p.price for p in chosen),
                      sum(p.score for p in chosen), omitted)

    cap = int(round(budget * 10))
    min_cost = 0
    for group, need in counts.items():
        if need:
            cheapest = sorted(groups[group], key=lambda p: p.units)[:need]
            min_cost += sum(p.units for p in cheapest)
    if min_cost > cap:
        raise InputError(
            f"budget {budget:g}m is too low: the cheapest legal XI costs {min_cost / 10:g}m"
        )

    tables = {}
    for group, need in counts.items():
        if need:
            tables[group] = group_table(groups[group], need, cap)

    # Combine groups: a max-plus convolution over exact costs, all groups in
    # formation order so the parent pointers can be walked back.
    order = [g for g in ("GK", "DEF", "MID", "FWD") if counts[g]]
    prev = np.full(cap + 1, NEG)
    prev[0] = 0.0
    parents = []
    for group in order:
        val = tables[group][0][counts[group]]
        new = np.full(cap + 1, NEG)
        parent = np.full(cap + 1, -1, dtype=np.int32)
        for cost in np.flatnonzero(np.isfinite(val)):
            cand = prev[: cap + 1 - cost] + val[cost]
            segment = new[cost:]
            better = cand > segment
            if better.any():
                segment[better] = cand[better]
                parent[cost:][better] = cost
        prev = new
        parents.append(parent)

    total = int(np.argmax(prev))
    chosen: list[Player] = []
    cursor = total
    for index in range(len(order) - 1, -1, -1):
        group = order[index]
        cost = int(parents[index][cursor])
        if cost < 0:
            raise InputError("no legal XI fits that budget")
        picked, _ = reconstruct(tables[group][1], groups[group], counts[group], cost)
        chosen.extend(picked)
        cursor -= cost

    if len(chosen) != sum(counts.values()):
        raise InputError("internal error: selection is short of a full XI")
    used = {id(p) for p in chosen}
    omitted = sorted((p for p in players if id(p) not in used),
                     key=lambda p: p.score, reverse=True)[:6]
    return Lineup(chosen, sum(p.price for p in chosen), sum(p.score for p in chosen), omitted)


# --- drawing ---------------------------------------------------------------

STRIPE_A = (26, 84, 38)
STRIPE_B = (22, 76, 34)
LINE = (206, 224, 206)
GOLD = (214, 178, 62)
SILVER = (176, 190, 202)
BRONZE = (186, 122, 74)
INK = (18, 20, 18)

CARD_W = 12
CARD_H = 5


def dwidth(text: str) -> int:
    total = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def compact_name(name: str, width: int) -> str:
    """Fit a name into a card: "Zakaria Fofana" -> "Z. Fofana" before truncating."""
    if dwidth(name) <= width:
        return name
    parts = name.split()
    if len(parts) > 1:
        short = parts[0][0] + ". " + " ".join(parts[1:])
        if dwidth(short) <= width:
            return short
        short = parts[0][0] + ". " + parts[-1]
        if dwidth(short) <= width:
            return short
        return short[: width - 2] + "\u2026" if width > 3 else short[:width]
    return name[: width - 1] + "\u2026" if width > 1 else name[:width]


def fit(text: str, width: int) -> str:
    """Truncate to a display width and pad to it."""
    out, used = [], 0
    for char in text:
        w = dwidth(char)
        if used + w > width:
            break
        out.append(char)
        used += w
    return "".join(out) + " " * (width - used)


class Canvas:
    def __init__(self, width: int, height: int, bg: tuple[int, int, int]) -> None:
        self.w = width
        self.h = height
        self.ch = [[" "] * width for _ in range(height)]
        self.st = [[(None, bg)] * width for _ in range(height)]

    def paint(self, x: int, y: int, text: str, fg=None, bg=None) -> None:
        for char in text:
            w = dwidth(char)
            if 0 <= y < self.h and 0 <= x < self.w:
                self.ch[y][x] = char
                self.st[y][x] = (fg, bg)
                for extra in range(1, max(1, w)):
                    if x + extra < self.w:
                        self.ch[y][x + extra] = ""
            x += max(1, w)

    def centre(self, cx: int, y: int, text: str, fg=None, bg=None) -> None:
        self.paint(cx - dwidth(text) // 2, y, text, fg, bg)

    def render(self, color: bool) -> str:
        lines = []
        for y in range(self.h):
            parts, current = [], None
            for x in range(self.w):
                style = self.st[y][x]
                if color and style != current:
                    fg, bg = style
                    codes = ["0"]
                    if fg:
                        codes.append(f"38;2;{fg[0]};{fg[1]};{fg[2]}")
                    if bg:
                        codes.append(f"48;2;{bg[0]};{bg[1]};{bg[2]}")
                    parts.append("\x1b[" + ";".join(codes) + "m")
                    current = style
                parts.append(self.ch[y][x])
            if color:
                parts.append("\x1b[0m")
            lines.append("".join(parts))
        return "\n".join(lines)


PITCH_W, PITCH_H = 78, 31
LINE_Y = {"FWD": 2, "MID": 9, "DEF": 18, "GK": 24}


def draw_pitch(canvas: Canvas) -> None:
    for y in range(canvas.h):
        band = STRIPE_A if (y // 2) % 2 == 0 else STRIPE_B
        for x in range(canvas.w):
            canvas.st[y][x] = (None, band)
    top, bottom, left, right = 1, canvas.h - 2, 1, canvas.w - 2
    for x in range(left, right + 1):
        canvas.paint(x, top, "─", LINE)
        canvas.paint(x, bottom, "─", LINE)
    for y in range(top, bottom + 1):
        canvas.paint(left, y, "│", LINE)
        canvas.paint(right, y, "│", LINE)
    for x, y, glyph in ((left, top, "╭"), (right, top, "╮"),
                        (left, bottom, "╰"), (right, bottom, "╯")):
        canvas.paint(x, y, glyph, LINE)
    mid_y = (top + bottom) // 2
    for x in range(left + 1, right):
        canvas.paint(x, mid_y, "·", LINE)
    cx, cy = canvas.w // 2, mid_y
    for step in range(34):
        angle = step * 2 * 3.141592653589793 / 34
        x = int(round(cx + 8.5 * np.cos(angle)))
        y = int(round(cy + 1.3 * np.sin(angle)))
        canvas.paint(x, y, "\u00b7", LINE)


def tier_colour(rating: int) -> tuple[int, int, int]:
    if rating >= 87:
        return GOLD
    if rating >= 81:
        return SILVER
    return BRONZE


def draw_card(canvas: Canvas, player: Player, centre: int) -> None:
    bg = tier_colour(player.rating)
    inner = CARD_W - 2
    left = centre - CARD_W // 2
    top = LINE_Y[player.group]
    canvas.paint(left, top, "╭" + "─" * inner + "╮", INK, bg)
    canvas.paint(left, top + 1, "│" + fit(f"{player.rating} {player.pos}", inner).center(inner) + "│",
                 INK, bg)
    canvas.paint(left, top + 2, "│" + fit(compact_name(player.name, inner), inner).center(inner)
                 + "│", INK, bg)
    canvas.paint(left, top + 3, "│" + fit(f"\u00a3{player.price:g}m", inner).center(inner) + "│",
                 INK, bg)
    canvas.paint(left, top + 4, "╰" + "─" * inner + "╯", INK, bg)


def render_lineup(lineup: Lineup, formation: str, budget: float | None,
                  color: bool) -> str:
    canvas = Canvas(PITCH_W, PITCH_H, STRIPE_A)
    draw_pitch(canvas)

    by_group: dict[str, list[Player]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for player in lineup.players:
        by_group[player.group].append(player)
    for players in by_group.values():
        players.sort(key=lambda p: (p.pos, -p.score))

    # Slots are computed per group so each line spreads evenly across the pitch.
    for group, players in by_group.items():
        n = len(players)
        if not n:
            continue
        margin = 2
        slot = (PITCH_W - 2 * margin) / n
        for index, player in enumerate(players):
            centre = int(round(margin + slot * (index + 0.5)))
            draw_card(canvas, player, centre)

    out = [canvas.render(color), ""]
    budget_text = "no limit" if budget is None else f"{budget:g}m"
    head = (f"  {formation}   score {lineup.score:,.0f}   "
            f"spend {lineup.cost:g}m of {budget_text}")
    if budget:
        share = max(0.0, min(1.0, lineup.cost / budget))
        filled = int(round(share * 28))
        bar = "\u2588" * filled + "\u2591" * (28 - filled)
        if color:
            tone = PALETTE["good"] if share < 0.95 else PALETTE["warn"]
            head += f"   \x1b[38;2;{tone[0]};{tone[1]};{tone[2]}m{bar}\x1b[0m"
        else:
            head += f"   {bar}"
    out.append(head)
    out.append("")
    out.append(f"  {'POS':<4}{'PLAYER':<20}{'CLUB':<16}{'RATING':>7}{'PRICE':>8}{'SCORE':>8}")
    for player in sorted(lineup.players, key=lambda p: -p.score):
        name = compact_name(player.name, 19)
        out.append(f"  {player.pos:<4}{name:<20}{player.club[:15]:<16}"
                   f"{player.rating:>7}{player.price:>7g}m{player.score:>8.0f}")
    if lineup.omitted:
        out.append("")
        out.append("  Best left out:")
        for player in lineup.omitted[:4]:
            out.append(f"    {player.pos:<4}{player.name[:17]:<18}"
                       f"rating {player.rating:>3}   {player.price:>6g}m   score {player.score:>6.0f}")
    return "\n".join(out)


# --- cli -------------------------------------------------------------------

PALETTE = {"good": (126, 200, 120), "warn": (226, 178, 84), "bad": (232, 110, 96)}


def parse_formation(text: str) -> tuple[tuple[int, int, int], str]:
    key = text.strip()
    if key in FORMATIONS:
        return FORMATIONS[key], key
    parts = key.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise InputError(
            f"unrecognised formation {text!r}. Try one of: {', '.join(FORMATIONS)}"
        )
    counts = tuple(int(p) for p in parts)
    if sum(counts) != 10:
        raise InputError(
            f"formation {key} has {sum(counts)} outfield players; needs exactly 10 "
            f"(plus a keeper)"
        )
    return counts, key


def main(argv: list[str] | None = None) -> int:
    default_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data", "sample-squad.csv")
    parser = argparse.ArgumentParser(
        prog="pitch",
        description="Pick the best XI under a budget and draw it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  pitch.py
  pitch.py --formation 3-5-2 --budget 120
  pitch.py --csv my-squad.csv --budget 60 --no-color
  pitch.py --list-formations
""",
    )
    parser.add_argument("--csv", default=default_csv, help="player CSV (default: bundled sample)")
    parser.add_argument("--formation", default="4-3-3", help="formation, e.g. 4-3-3 (default)")
    parser.add_argument("--budget", type=float, default=500.0,
                        help="transfer budget in millions; 0 means no limit (default: 500)")
    parser.add_argument("--no-color", action="store_true", help="plain text output")
    parser.add_argument("--color", action="store_true", help="force colour even when piped")
    parser.add_argument("--list-formations", action="store_true", help="print formations and exit")
    parser.add_argument("--version", action="version", version="pitch 0.1.0")
    args = parser.parse_args(argv)

    if args.list_formations:
        seen = {}
        for name, counts in FORMATIONS.items():
            seen.setdefault(counts, name)
        for name, counts in FORMATIONS.items():
            note = "" if seen[counts] == name else "  (same shape as %s)" % seen[counts]
            print(f"  {name:<9} {counts[0]} def, {counts[1]} mid, {counts[2]} fwd{note}")
        return 0

    if args.budget < 0:
        parser.error("--budget cannot be negative")
    color = not args.no_color and (args.color or sys.stdout.isatty())
    if os.environ.get("NO_COLOR") and not args.color:
        color = False

    try:
        players = load_players(args.csv)
        counts, formation = parse_formation(args.formation)
        budget = None if args.budget == 0 else args.budget
        lineup = solve(players, {"GK": 1, "DEF": counts[0], "MID": counts[1], "FWD": counts[2]},
                       budget)
    except InputError as error:
        print(f"pitch: {error}", file=sys.stderr)
        return 1

    print(render_lineup(lineup, formation, budget, color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
