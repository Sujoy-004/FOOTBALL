"""Tests for the group stage simulation engine.

Covers expected_goals formula, Poisson sampling, match simulation,
fair play card distribution, and group iteration integrity.
"""

import random

import pytest

from src.groups import (
    _poisson_sample,
    _simulate_single_match,
    expected_goals,
    simulate_group_matches,
)


# ─── expected_goals tests ──────────────────────────────────────────────


class TestExpectedGoals:
    """Tests for the Elo-to-goals formula."""

    def test_expected_goals_home_advantage(self):
        """At equal Elo, team_a gets home advantage multiplier (1.05x)."""
        val = expected_goals(1500, 1500)
        assert abs(val - 1.3125) < 0.001, f"Expected ~1.3125, got {val}"

    def test_expected_goals_stronger_team(self):
        """A stronger team (higher Elo) gets a higher expected goals lambda."""
        strong = expected_goals(2000, 1500)
        neutral = expected_goals(1500, 1500)
        assert strong > neutral, (
            f"Stronger team should get higher lambda: {strong} <= {neutral}"
        )

    def test_expected_goals_weaker_team(self):
        """A weaker team (lower Elo) gets a lower expected goals lambda."""
        weak = expected_goals(1500, 2000)
        neutral = expected_goals(1500, 1500)
        assert weak < neutral, (
            f"Weaker team should get lower lambda: {weak} >= {neutral}"
        )

    def test_expected_goals_custom_base_rate(self):
        """Custom base_rate scales the result proportionally."""
        val = expected_goals(1500, 1500, base_rate=2.0)
        assert abs(val - 2.1) < 0.001, f"Expected ~2.1, got {val}"

    def test_expected_goals_very_strong_dominates(self):
        """Huge Elo gap produces a very high lambda."""
        val = expected_goals(2500, 1000)
        assert val > 10.0, f"Expected large lambda for big Elo gap, got {val}"

    def test_expected_goals_very_weak_minimal(self):
        """Very weak team against very strong team gets near-zero lambda."""
        val = expected_goals(1000, 2500)
        assert val < 0.1, f"Expected tiny lambda for huge disadvantage, got {val}"


# ─── _poisson_sample tests ─────────────────────────────────────────────


class TestPoissonSample:
    """Tests for the Knuth Poisson sampler."""

    def test_poisson_sample_valid_range(self):
        """For lambda=5.0 with seed 42, sample is a plausible integer."""
        s = _poisson_sample(5.0, random.Random(42))
        assert isinstance(s, int)
        assert 0 <= s <= 15, f"Implausible sample for lam=5.0: {s}"

    def test_poisson_sample_reproducible(self):
        """Same seed produces same sample."""
        r1 = random.Random(42)
        r2 = random.Random(42)
        s1 = _poisson_sample(5.0, r1)
        s2 = _poisson_sample(5.0, r2)
        assert s1 == s2, f"Reproducibility failed: {s1} != {s2}"

    def test_poisson_sample_zero_lambda(self):
        """Lambda = 0 always returns 0."""
        rng = random.Random(42)
        assert _poisson_sample(0.0, rng) == 0

    def test_poisson_sample_negative_lambda(self):
        """Negative lambda is treated as 0."""
        rng = random.Random(42)
        assert _poisson_sample(-1.0, rng) == 0

    def test_poisson_sample_tiny_lambda(self):
        """Very small lambda (e.g., 0.01) returns 0 in nearly all cases."""
        rng = random.Random(42)
        s = _poisson_sample(0.01, rng)
        assert s == 0, f"Expected 0 for tiny lambda, got {s}"

    def test_poisson_sample_large_lambda(self):
        """Large lambda produces larger samples."""
        rng = random.Random(42)
        s = _poisson_sample(100.0, rng)
        assert 70 <= s <= 130, f"Implausible sample for lam=100.0: {s}"


# ─── _simulate_single_match tests ──────────────────────────────────────


class TestSimulateSingleMatch:
    """Tests for single match simulation."""

    def test_simulate_single_match_winner_determined(self):
        """For elo_a >> elo_b, team_a should win in > 95% of cases."""
        wins = 0
        n = 100
        for seed in range(n):
            rng = random.Random(seed)
            result = _simulate_single_match(
                "Brazil", "Curaçao", 2090, 1300, rng
            )
            if result["winner"] == "Brazil":
                wins += 1
        assert wins >= 95, (
            f"Brazil (2090) should beat Curaçao (1300) in > 95% of cases, "
            f"won {wins}/{n}"
        )

    def test_simulate_single_match_scores_non_negative(self):
        """Both score_a and score_b are always >= 0."""
        n = 100
        for seed in range(n):
            rng = random.Random(seed)
            result = _simulate_single_match(
                "Argentina", "France", 2115, 2063, rng
            )
            assert result["score_a"] >= 0
            assert result["score_b"] >= 0

    def test_simulate_single_match_winner_better(self):
        """The winner's score is always >= the loser's score."""
        n = 50
        for seed in range(n):
            rng = random.Random(seed)
            result = _simulate_single_match(
                "Argentina", "France", 2115, 2063, rng
            )
            if result["winner"] == "Argentina":
                assert result["score_a"] >= result["score_b"]
            elif result["winner"] == "France":
                assert result["score_b"] >= result["score_a"]
            # else draw — no winner

    def test_simulate_single_match_draw_possible(self):
        """Draw (winner=None) occurs for some seeds."""
        draws = 0
        n = 200
        for seed in range(n):
            rng = random.Random(seed)
            result = _simulate_single_match(
                "Argentina", "France", 2115, 2063, rng
            )
            if result["winner"] is None:
                draws += 1
        assert draws > 0, (
            "Expected at least 1 draw in 200 equal-rated matches"
        )

    def test_simulate_single_match_card_fields_present(self):
        """The result dict contains all expected card fields."""
        rng = random.Random(42)
        result = _simulate_single_match("Mexico", "Canada", 1850, 1800, rng)
        assert "yellow_cards_a" in result
        assert "red_cards_a" in result
        assert "yellow_cards_b" in result
        assert "red_cards_b" in result

    def test_simulate_single_match_cards_non_negative(self):
        """Card counts are always non-negative."""
        n = 50
        for seed in range(n):
            rng = random.Random(seed)
            result = _simulate_single_match(
                "Argentina", "France", 2115, 2063, rng
            )
            assert result["yellow_cards_a"] >= 0
            assert result["red_cards_a"] >= 0
            assert result["yellow_cards_b"] >= 0
            assert result["red_cards_b"] >= 0


# ─── simulate_group_matches tests ──────────────────────────────────────


class TestSimulateGroupMatches:
    """Tests for full group match simulation."""

    def test_simulate_group_matches_structure(self, sample_teams, sample_groups):
        """Returns dict with 12 group keys (A-L), each with 6 matches."""
        elo_ratings = {n: d["elo"] for n, d in sample_teams.items()}
        # Extend elo_ratings with Group A teams that may not be in sample_teams
        elo_ratings["Mexico"] = 1850
        elo_ratings["South Africa"] = 1700
        elo_ratings["South Korea"] = 1650
        elo_ratings["Czech Republic"] = 1468
        rng = random.Random(42)
        results = simulate_group_matches(sample_groups, sample_teams, elo_ratings, rng)
        assert len(results) == 1, f"Expected 1 group, got {len(results)}"
        assert "A" in results, "Missing group A"
        assert len(results["A"]) == 6, (
            f"Expected 6 matches, got {len(results['A'])}"
        )

    def test_simulate_group_matches_full_12_groups(self):
        """All 12 groups exist with correct match counts."""
        import json
        from pathlib import Path
        data_dir = Path(__file__).resolve().parent.parent / "data"
        groups = json.load(open(data_dir / "groups.json"))
        teams = json.load(open(data_dir / "teams.json"))
        elo = {n: v["elo"] for n, v in teams.items()}
        rng = random.Random(42)
        results = simulate_group_matches(groups, teams, elo, rng)
        assert len(results) == 12
        for g in "ABCDEFGHIJKL":
            assert g in results, f"Missing group {g}"
            assert len(results[g]) == 6, (
                f"Group {g} expected 6 matches, got {len(results[g])}"
            )

    def test_simulate_group_matches_all_teams_appear(self, sample_groups):
        """Every team in every group appears in at least one match result."""
        elo_ratings = {
            "Mexico": 1850,
            "South Africa": 1700,
            "South Korea": 1650,
            "Czech Republic": 1468,
        }
        sample_teams_dict = {n: {"elo": e} for n, e in elo_ratings.items()}
        rng = random.Random(42)
        results = simulate_group_matches(
            sample_groups, sample_teams_dict, elo_ratings, rng
        )
        teams_seen = set()
        for mid, match in results["A"].items():
            teams_seen.add(match["team_a"])
            teams_seen.add(match["team_b"])
        assert teams_seen == set(elo_ratings.keys()), (
            f"Missing teams in results: {set(elo_ratings.keys()) - teams_seen}"
        )

    def test_simulate_group_matches_no_mutation(self, sample_groups):
        """The input groups dict is not modified."""
        elo_ratings = {
            "Mexico": 1850,
            "South Africa": 1700,
            "South Korea": 1650,
            "Czech Republic": 1468,
        }
        sample_teams_dict = {n: {"elo": e} for n, e in elo_ratings.items()}
        # Capture original state
        original_winners = {}
        for g, gdata in sample_groups["groups"].items():
            for match in gdata["matches"]:
                original_winners[match["match_id"]] = match.get("winner")

        rng = random.Random(42)
        _ = simulate_group_matches(sample_groups, sample_teams_dict, elo_ratings, rng)

        # Verify no mutation
        for g, gdata in sample_groups["groups"].items():
            for match in gdata["matches"]:
                assert match.get("winner") == original_winners[match["match_id"]], (
                    f"Input groups dict was mutated for {match['match_id']}"
                )

    def test_simulate_group_matches_reproducible(self):
        """Same seeds produce identical results for full dataset."""
        import json
        from pathlib import Path
        data_dir = Path(__file__).resolve().parent.parent / "data"
        groups = json.load(open(data_dir / "groups.json"))
        teams = json.load(open(data_dir / "teams.json"))
        elo = {n: v["elo"] for n, v in teams.items()}
        r1 = simulate_group_matches(groups, teams, elo, random.Random(42))
        r2 = simulate_group_matches(groups, teams, elo, random.Random(42))
        assert r1 == r2, "Same seed should produce identical results"


# ─── Fair play card distribution tests ─────────────────────────────────


class TestFairPlayCards:
    """Tests for statistical correctness of card distribution."""

    def test_fair_play_card_counts(self):
        """Average YC per team per match is ~2.0 (±0.5), RC is ~0.05 (±0.03)."""
        import json
        from pathlib import Path
        data_dir = Path(__file__).resolve().parent.parent / "data"
        groups = json.load(open(data_dir / "groups.json"))
        teams = json.load(open(data_dir / "teams.json"))
        elo = {n: v["elo"] for n, v in teams.items()}

        total_yc = 0
        total_rc = 0
        total_matches = 0

        for iteration in range(1000):
            rng = random.Random(iteration)
            results = simulate_group_matches(groups, teams, elo, rng)
            for g, matches in results.items():
                for mid, m in matches.items():
                    total_yc += m["yellow_cards_a"] + m["yellow_cards_b"]
                    total_rc += m["red_cards_a"] + m["red_cards_b"]
                    total_matches += 1

        avg_yc = total_yc / (2 * total_matches)
        avg_rc = total_rc / (2 * total_matches)

        assert 1.5 <= avg_yc <= 2.5, (
            f"Average YC per team per match outside expected range: {avg_yc}"
        )
        assert 0.02 <= avg_rc <= 0.08, (
            f"Average RC per team per match outside expected range: {avg_rc}"
        )
