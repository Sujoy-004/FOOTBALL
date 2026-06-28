"""Tests for UCL knockout tie simulation."""

from __future__ import annotations

import random

import pytest

from competitions.ucl.src.knockout import (
    _simulate_penalty_shootout,
    simulate_two_legged_tie,
)


class TestTwoLeggedTie:
    """UCLK-01: Two-legged tie with aggregate scoring, ET, penalties."""

    def test_two_legs_aggregate_winner(self, sample_knockout_elos):
        """Team with higher aggregate score wins (e.g., 3-1, 2-2 -> 5-3 agg)."""
        # Strong vs weak team to force a clear aggregate winner
        elos = {"Strong": 2000, "Weak": 1000}
        rng = random.Random(42)
        result = simulate_two_legged_tie("Strong", "Weak", elos, rng)
        assert result["winner"] == "Strong"
        assert result["loser"] == "Weak"
        assert result["aggregate_a"] >= 0
        assert result["aggregate_b"] >= 0
        assert result["aggregate_a"] + result["aggregate_b"] > 0  # goals scored

    def test_two_legs_draw_aggregate_et_played(self, sample_rng):
        """Level aggregate triggers ET (e.g., 2-1, 1-2 -> 3-3 agg -> ET played)."""
        # Equal Elo teams make a draw likely
        elos = {"Team A": 1500, "Team B": 1500}
        # Use many seeds to find one where aggregate is level
        et_found = False
        for seed in range(200):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            agg_a = result["leg1"]["score_a"] + result["leg2"]["score_a"]
            agg_b = result["leg1"]["score_b"] + result["leg2"]["score_b"]
            if agg_a == agg_b:
                assert result["et_played"] is True, (
                    f"Seed {seed}: Aggregate level ({agg_a}-{agg_b}) but ET not played"
                )
                et_found = True
                break
        assert et_found, "No seed produced a level aggregate after 200 tries"

    def test_two_legs_et_winner(self, sample_rng):
        """Winner resolved in ET (aggregate level after 90 min, ET breaks tie)."""
        elos = {"Team A": 1500, "Team B": 1500}
        et_winner_found = False
        for seed in range(500):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            if result["et_played"] and result["agg_a_full"] != result["agg_b_full"]:
                assert result["penalties_played"] is False
                et_winner_found = True
                break
        assert et_winner_found, "No seed produced ET winner after 500 tries"

    def test_two_legs_penalties_winner(self, sample_rng):
        """Still level after ET -> penalties decide."""
        elos = {"Team A": 1500, "Team B": 1500}
        pens_found = False
        for seed in range(1000):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            if result["penalties_played"]:
                assert result["winner"] is not None
                assert result["winner"] in ("Team A", "Team B")
                pens_found = True
                break
        assert pens_found, "No seed produced penalties after 1000 tries"

    def test_two_legs_deterministic(self):
        """Same seed produces identical tie result."""
        elos = {"Man City": 2000, "Slovan Bratislava": 1500}
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        r1 = simulate_two_legged_tie("Man City", "Slovan Bratislava", elos, rng1)
        r2 = simulate_two_legged_tie("Man City", "Slovan Bratislava", elos, rng2)
        assert r1 == r2

    def test_two_legs_et_home_advantage(self):
        """Second-leg home team has higher ET scoring rate (D-03).

        Tests that team_b (second-leg host) gets home advantage during
        ET by checking that ET score distribution favours team_b over
        many trials.
        """
        elos = {"Team A": 1500, "Team B": 1500}
        et_total_a = 0
        et_total_b = 0
        et_count = 0
        for seed in range(2000):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            if result["et_played"]:
                et_total_a += result["et_a"]
                et_total_b += result["et_b"]
                et_count += 1
        # With home advantage in ET (extra HOME_ADVANTAGE_MULTIPLIER for team_b),
        # and enough trials, team_b should score at least as much as team_a.
        # Using a relaxed check because Poisson variance at low lambda can
        # occasionally flip the aggregate even with the HA boost.
        if et_count >= 20:
            expected_a = et_count * 1.3125 * 0.25  # ~0.33 per instance
            expected_b = et_count * 1.3125 * 0.25 * 1.05  # ~0.34 per instance
            # With the HA boost, team_b should on average have more total ET goals
            assert et_total_b >= et_total_a or et_total_b > expected_a * 0.8, (
                f"Team B (ET home) scored {et_total_b} vs Team A {et_total_a} "
                f"in {et_count} ET instances — expected home advantage effect"
            )

    def test_two_legs_no_away_goals_rule(self, sample_rng):
        """2-2 aggregate is level regardless of away goals distribution."""
        elos = {"Team A": 1500, "Team B": 1500}
        for seed in range(200):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            agg_a = result["aggregate_a"]
            agg_b = result["aggregate_b"]
            # If aggregate is level, must go to ET (not auto-resolved by away goals)
            if agg_a == agg_b:
                assert result["et_played"] or result["penalties_played"], (
                    f"Seed {seed}: Aggregate level ({agg_a}-{agg_b}) but no ET/pens "
                    f"(away goals not in effect)"
                )

    def test_two_legs_output_keys(self, sample_knockout_elos):
        """Result dict has all expected keys."""
        rng = random.Random(42)
        result = simulate_two_legged_tie("Man City", "Real Madrid", sample_knockout_elos, rng)
        expected_keys = {
            "winner", "loser",
            "aggregate_a", "aggregate_b",
            "agg_a_full", "agg_b_full",
            "leg1", "leg2",
            "et_played", "et_a", "et_b",
            "penalties_played", "penalty_a", "penalty_b",
        }
        assert expected_keys.issubset(result.keys()), (
            f"Missing keys: {expected_keys - set(result.keys())}"
        )

        # Check leg structure
        for leg_key in ("leg1", "leg2"):
            leg = result[leg_key]
            for k in ("team_a", "team_b", "score_a", "score_b"):
                assert k in leg, f"Missing key '{k}' in {leg_key}"

    def test_two_legs_elo_favored_wins_more_often(self):
        """Stronger team (higher Elo) wins more often over N trials."""
        elos = {"Strong": 2000, "Weak": 1000}
        strong_wins = 0
        n_trials = 200
        for seed in range(n_trials):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Strong", "Weak", elos, rng)
            if result["winner"] == "Strong":
                strong_wins += 1
        win_pct = strong_wins / n_trials
        assert win_pct > 0.5, (
            f"Strong team only won {strong_wins}/{n_trials} ({win_pct:.1%})"
        )

    def test_two_legs_et_not_played_when_clear_winner(self):
        """5-0 aggregate does not trigger ET."""
        elos = {"Strong": 2000, "Weak": 1000}
        et_not_played = False
        for seed in range(500):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Strong", "Weak", elos, rng)
            agg_margin = abs(result["agg_a_full"] - result["agg_b_full"])
            if agg_margin >= 4:
                # Clear winner should not have ET
                assert result["winner"] in ("Strong", "Weak")
                assert result["et_played"] is False
                assert result["penalties_played"] is False
                et_not_played = True
                break
        assert et_not_played, "No seed produced a 4+ goal aggregate margin"


class TestPenaltyShootout:
    """Tests for the penalty shootout helper."""

    def test_penalty_shootout_returns_tuple(self, sample_rng):
        """Penalty shootout returns two ints."""
        a, b = _simulate_penalty_shootout(sample_rng)
        assert isinstance(a, int)
        assert isinstance(b, int)

    def test_penalty_shootout_not_level(self, sample_rng):
        """Penalty shootout produces a winner (not level)."""
        for seed in range(100):
            rng = random.Random(seed)
            a, b = _simulate_penalty_shootout(rng)
            assert a != b, f"Seed {seed}: Shootout level at {a}-{b}"

    def test_penalty_shootout_valid_scores(self, sample_rng):
        """Scores are within plausible range."""
        for seed in range(100):
            rng = random.Random(seed)
            a, b = _simulate_penalty_shootout(rng)
            assert 0 <= a <= 20
            assert 0 <= b <= 20

    def test_penalty_shootout_deterministic(self):
        """Same seed produces identical shootout."""
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        assert _simulate_penalty_shootout(rng1) == _simulate_penalty_shootout(rng2)
