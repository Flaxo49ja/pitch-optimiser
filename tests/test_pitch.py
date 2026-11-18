#!/usr/bin/env python3
"""Tests for the pitch optimiser. Run: python3 -m unittest discover -s tests"""

import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pitch  # noqa: E402


def make(pos, rating, price, seed=0):
    rng = random.Random(seed)
    attrs = tuple(rng.uniform(30, 95) for _ in pitch.ATTRS)
    return pitch.Player(f"{pos}{rating}", pos, "Test", rating, attrs, price)


def brute_force(players, counts, budget):
    """Highest achievable score by trying every legal XI."""
    groups = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for player in players:
        groups[player.group].append(player)
    cap = int(round(budget * 10))
    best = None
    keys = list(counts)
    for combo in itertools.product(*(itertools.combinations(groups[k], counts[k]) for k in keys)):
        chosen = [p for part in combo for p in part]
        if sum(p.units for p in chosen) <= cap:
            score = sum(p.score for p in chosen)
            if best is None or score > best:
                best = score
    return best


class TestOptimality(unittest.TestCase):
    def test_matches_brute_force_on_random_instances(self):
        rng = random.Random(7)
        checked = 0
        for trial in range(12):
            players = []
            for group, positions, size in (("GK", ["GK"], 2), ("DEF", ["CB", "LB"], 5),
                                           ("MID", ["CM", "CAM"], 4), ("FWD", ["ST", "LW"], 3)):
                for _ in range(size):
                    pos = rng.choice(positions)
                    players.append(make(pos, rng.randint(55, 92),
                                        round(rng.uniform(0.5, 90), 1), seed=rng.random()))
            counts = {"GK": 1, "DEF": rng.randint(1, 2), "MID": rng.randint(1, 2),
                      "FWD": 1}
            # Budget just above the cheapest legal XI, so the instance is feasible
            # but still forces real trade-offs.
            groups = {}
            for player in players:
                groups.setdefault(player.group, []).append(player.price)
            floor = sum(sum(sorted(groups[g])[:counts[g]]) for g in counts)
            budget = round(floor + rng.uniform(1, 120), 1)
            expected = brute_force(players, counts, budget)
            if expected is None:
                continue
            with self.subTest(trial=trial, counts=counts, budget=budget):
                lineup = pitch.solve(players, counts, budget)
                self.assertAlmostEqual(lineup.score, expected, places=6)
                checked += 1
        self.assertGreater(checked, 8, "too few feasible random instances to be meaningful")

    def test_respects_budget_and_formation(self):
        players = pitch.load_players(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "sample-squad.csv"))
        for formation in ("4-3-3", "3-5-2", "5-2-3", "4-2-3-1"):
            counts, _ = pitch.parse_formation(formation)
            wanted = {"GK": 1, "DEF": counts[0], "MID": counts[1], "FWD": counts[2]}
            lineup = pitch.solve(players, wanted, 500.0)
            self.assertLessEqual(round(lineup.cost * 10), 5000)
            got = {}
            for player in lineup.players:
                got[player.group] = got.get(player.group, 0) + 1
            self.assertEqual(got, wanted)
            self.assertEqual(len({id(p) for p in lineup.players}), 11)

    def test_no_duplicate_players(self):
        players = pitch.load_players(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "sample-squad.csv"))
        lineup = pitch.solve(players, {"GK": 1, "DEF": 4, "MID": 5, "FWD": 1}, 700.0)
        self.assertEqual(len({id(p) for p in lineup.players}), len(lineup.players))

    def test_unlimited_budget_takes_the_best(self):
        players = pitch.load_players(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "sample-squad.csv"))
        counts = {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3}
        lineup = pitch.solve(players, counts, None)
        by_group = {}
        for player in players:
            by_group.setdefault(player.group, []).append(player.score)
        expected = sum(sum(sorted(scores, reverse=True)[:counts[group]])
                       for group, scores in by_group.items())
        self.assertAlmostEqual(lineup.score, expected, places=6)


class TestInput(unittest.TestCase):
    def test_budget_too_low(self):
        players = [make("GK", 70, 30), make("CB", 70, 30), make("CB", 70, 30),
                   make("CM", 70, 30), make("ST", 70, 30), make("ST", 70, 30)]
        with self.assertRaises(pitch.InputError):
            pitch.solve(players, {"GK": 1, "DEF": 1, "MID": 1, "FWD": 2}, 5.0)

    def test_not_enough_players_in_a_group(self):
        players = [make("GK", 70, 5), make("CB", 70, 5)]
        with self.assertRaises(pitch.InputError):
            pitch.solve(players, {"GK": 1, "DEF": 4, "MID": 0, "FWD": 0}, 100.0)

    def test_bad_formation(self):
        with self.assertRaises(pitch.InputError):
            pitch.parse_formation("4-4-3")
        with self.assertRaises(pitch.InputError):
            pitch.parse_formation("nonsense")

    def test_unknown_position(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write("name,pos,rating,price\nSomeone,XX,80,10\n")
            path = handle.name
        try:
            with self.assertRaises(pitch.InputError) as ctx:
                pitch.load_players(path)
            self.assertIn("unknown position", str(ctx.exception))
        finally:
            os.unlink(path)


class TestPresentation(unittest.TestCase):
    def test_compact_name_keeps_surname(self):
        self.assertEqual(pitch.compact_name("Zakaria Fofana", 10), "Z. Fofana")
        self.assertEqual(pitch.compact_name("Viktor Halland", 10), "V. Halland")
        self.assertTrue(len(pitch.compact_name("Bartholomew Fitzgerald", 10)) <= 10)
        self.assertEqual(pitch.compact_name("Pelé", 10), "Pelé")

    def test_render_without_colour_has_no_escapes(self):
        players = pitch.load_players(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "sample-squad.csv"))
        lineup = pitch.solve(players, {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3}, 400.0)
        text = pitch.render_lineup(lineup, "4-3-3", 400.0, color=False)
        self.assertNotIn("\x1b[", text)
        self.assertIn("4-3-3", text)

    def test_colour_output_has_truecolour(self):
        players = pitch.load_players(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "sample-squad.csv"))
        lineup = pitch.solve(players, {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3}, 400.0)
        text = pitch.render_lineup(lineup, "4-3-3", 400.0, color=True)
        self.assertIn("\x1b[38;2;", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
