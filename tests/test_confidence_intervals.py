"""Tests for bootstrap confidence intervals on champion probabilities.

Tests cover:
    - compute_bootstrap_ci: basic CI computation, width properties
    - compute_bootstrap_ci_small_sample: Wilson score for low-count teams
    - aggregate_mc_results with compute_ci=True: field presence, backward compat
    - CI endpoint validity ([0, 1] bounds)
    - Deterministic output with same seed
"""

from __future__ import annotations

import math

import pytest

from competitions.ucl.src.simulation import (
    _wilson_score_interval,
    _z_score,
    aggregate_mc_results,
    compute_bootstrap_ci,
    compute_bootstrap_ci_small_sample,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ── _z_score Tests ──────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestZScore:
    def test_alpha_005(self):
        """z=1.96 for 95% CI."""
        z = _z_score(0.05)
        assert abs(z - 1.96) < 1e-4

    def test_alpha_010(self):
        """z=1.6449 for 90% CI."""
        z = _z_score(0.10)
        assert abs(z - 1.6449) < 1e-4

    def test_alpha_001(self):
        """z=2.5758 for 99% CI."""
        z = _z_score(0.01)
        assert abs(z - 2.5758) < 1e-4

    def test_unknown_alpha_fallback(self):
        """Fallback clamps to nearest known z-score."""
        # alpha=0.50 is above the largest key (0.10); clamped to 1.6449
        z = _z_score(0.50)
        assert abs(z - 1.6449) < 1e-4


# ═══════════════════════════════════════════════════════════════════════════════
# ── _wilson_score_interval Tests ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestWilsonScoreInterval:
    def test_zero_count(self):
        """Zero successes should give (0.0, upper > 0)."""
        lo, hi = _wilson_score_interval(0, 10000)
        assert lo == 0.0
        assert hi > 0.0

    def test_all_successes(self):
        """All successes should give (lower < 1.0, hi ~1.0)."""
        lo, hi = _wilson_score_interval(10000, 10000)
        assert lo < 1.0
        assert hi > 0.9999  # floating-point approximation of 1.0

    def test_small_count(self):
        """Count=1 should produce a tight but non-degenerate interval."""
        lo, hi = _wilson_score_interval(1, 10000)
        assert 0.0 < lo < 0.001
        assert 0.0 < hi < 0.002

    def test_endpoints_in_01(self):
        """Endpoints always in [0, 1]."""
        for k in [0, 1, 5, 50, 5000, 9950, 9995, 10000]:
            lo, hi = _wilson_score_interval(k, 10000)
            assert 0.0 <= lo <= 1.0, f"k={k}: lo={lo}"
            assert 0.0 <= hi <= 1.0, f"k={k}: hi={hi}"
            assert lo <= hi, f"k={k}: lo={lo} > hi={hi}"

    def test_narrower_with_more_samples(self):
        """CI for n=100000 is narrower than n=10000."""
        lo1, hi1 = _wilson_score_interval(500, 10000)
        lo2, hi2 = _wilson_score_interval(5000, 100000)
        assert (hi2 - lo2) < (hi1 - lo1)


# ═══════════════════════════════════════════════════════════════════════════════
# ── compute_bootstrap_ci Tests ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestBootstrapCI:
    def test_basic_ci(self):
        """Basic CI computation returns dict with same team keys."""
        counts = {"A": 5000, "B": 100, "C": 0}
        ci = compute_bootstrap_ci(counts, 10000)
        assert set(ci.keys()) == {"A", "B", "C"}

    def test_endpoints_in_01(self):
        """All endpoints in [0, 1]."""
        counts = {"A": 9000, "B": 5000, "C": 100, "D": 0}
        ci = compute_bootstrap_ci(counts, 10000)
        for team, (lo, hi) in ci.items():
            assert 0.0 <= lo <= 1.0, f"{team}: lo={lo}"
            assert 0.0 <= hi <= 1.0, f"{team}: hi={hi}"
            assert lo <= hi, f"{team}: lo={lo} > hi={hi}"

    def test_zero_count(self):
        """Teams with count=0 get (0.0, 0.0)."""
        ci = compute_bootstrap_ci({"Z": 0}, 10000)
        assert ci["Z"] == (0.0, 0.0)

    def test_all_count(self):
        """Teams with count=n_iterations get (1.0, 1.0)."""
        ci = compute_bootstrap_ci({"Z": 10000}, 10000)
        assert ci["Z"] == (1.0, 1.0)

    def test_deterministic_output(self):
        """Same seed produces identical CIs."""
        counts = {"A": 5000, "B": 100}
        ci1 = compute_bootstrap_ci(counts, 10000, seed=42)
        ci2 = compute_bootstrap_ci(counts, 10000, seed=42)
        assert ci1 == ci2

    def test_different_seed_different_output(self):
        """Different seeds may produce different CIs (not guaranteed but likely)."""
        counts = {"A": 5000}
        ci1 = compute_bootstrap_ci(counts, 10000, seed=42)
        ci2 = compute_bootstrap_ci(counts, 10000, seed=99)
        # At least one endpoint should differ (stochastic process)
        assert (ci1["A"][0] != ci2["A"][0]) or (ci1["A"][1] != ci2["A"][1])

    def test_wider_for_high_variance(self):
        """CI for p≈0.5 is wider than for extreme p values."""
        ci_mid = compute_bootstrap_ci({"A": 5000}, 10000)
        ci_low = compute_bootstrap_ci({"B": 100}, 10000)
        w_mid = ci_mid["A"][1] - ci_mid["A"][0]
        w_low = ci_low["B"][1] - ci_low["B"][0]
        # p=0.5 maximises binomial variance → wider CI
        assert w_mid > w_low, (
            f"CI at p=0.5 (width={w_mid:.4f}) should be wider than "
            f"at p=0.01 (width={w_low:.4f})"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ── compute_bootstrap_ci_small_sample Tests ─────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestSmallSampleCI:
    def test_only_small_counts(self):
        """Only returns results for 0 < count < 5."""
        counts = {"A": 1, "B": 2, "C": 4, "D": 5, "E": 0, "F": 100}
        result = compute_bootstrap_ci_small_sample(counts, 10000)
        assert "A" in result
        assert "B" in result
        assert "C" in result
        assert "D" not in result  # count=5, not small
        assert "E" not in result  # count=0, not positive
        assert "F" not in result  # count=100, not small

    def test_endpoints_in_01(self):
        """All endpoints in [0, 1]."""
        counts = {f"T{i}": i for i in range(1, 5)}
        result = compute_bootstrap_ci_small_sample(counts, 10000)
        for team, (lo, hi) in result.items():
            assert 0.0 <= lo <= 1.0, f"{team}: lo={lo}"
            assert 0.0 <= hi <= 1.0, f"{team}: hi={hi}"
            assert lo <= hi

    def test_narrower_with_higher_count_in_pct(self):
        """Relative width (width/p) decreases with higher count.

        Absolute Wilson CI width increases with p for small p (width ~ sqrt(p)),
        but the relative width (width/p) decreases with more data.
        """
        r1 = compute_bootstrap_ci_small_sample({"A": 1}, 10000)
        r4 = compute_bootstrap_ci_small_sample({"B": 4}, 10000)
        lo1, hi1 = r1["A"]
        lo4, hi4 = r4["B"]
        p1 = 1 / 10000
        p4 = 4 / 10000
        rel_w1 = (hi1 - lo1) / p1 if p1 > 0 else 0.0
        rel_w4 = (hi4 - lo4) / p4 if p4 > 0 else 0.0
        assert rel_w1 >= rel_w4, (
            f"Relative CI width for count=1 ({rel_w1:.2f}) should be >= "
            f"count=4 ({rel_w4:.2f})"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ── aggregate_mc_results with compute_ci Tests ──────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestAggregateMCWithCI:
    """Tests that aggregate_mc_results correctly adds CI fields."""

    @pytest.fixture
    def minimal_data(self):
        positions = {"A": [1, 2, 3], "B": [4, 5, 6]}
        champions = {"A": 2, "B": 0}
        stats = {
            "A": {"pts": [6, 4, 3], "gd": [2, 0, -1], "gs": [3, 2, 1],
                  "away_gs": [1, 1, 0], "wins": [2, 1, 1], "away_wins": [1, 0, 0]},
            "B": {"pts": [3, 1, 1], "gd": [-1, -2, -3], "gs": [1, 0, 1],
                  "away_gs": [0, 0, 1], "wins": [1, 0, 0], "away_wins": [0, 0, 0]},
        }
        return positions, champions, stats

    def test_backward_compat(self, minimal_data):
        """compute_ci=False produces identical output to before (no CI fields)."""
        positions, champions, stats = minimal_data
        r = aggregate_mc_results(positions, champions, stats, 3)
        for team_data in r.values():
            assert "champion_ci_lower" not in team_data
            assert "champion_ci_upper" not in team_data

    def test_ci_fields_present(self, minimal_data):
        """compute_ci=True adds CI fields to all teams."""
        positions, champions, stats = minimal_data
        r = aggregate_mc_results(positions, champions, stats, 3, compute_ci=True)
        for team_data in r.values():
            assert "champion_ci_lower" in team_data
            assert "champion_ci_upper" in team_data
            assert "champion_ci_width_pct" in team_data
            assert team_data["champion_ci_width_pct"] >= 0.0

    def test_ci_for_zero_champion(self, minimal_data):
        """Team with champion_count=0 gets CI (0.0, 0.0)."""
        positions, champions, stats = minimal_data
        r = aggregate_mc_results(positions, champions, stats, 3, compute_ci=True)
        assert r["B"]["champion_ci_lower"] == 0.0
        assert r["B"]["champion_ci_upper"] == 0.0
        assert r["B"]["champion_ci_width_pct"] == 0.0

    def test_glicko_uncertainty_field(self, minimal_data):
        """using_glicko=True adds uncertainty_contribution."""
        positions, champions, stats = minimal_data
        r = aggregate_mc_results(
            positions, champions, stats, 3,
            compute_ci=True, using_glicko=True,
        )
        assert "uncertainty_contribution" in r["A"]
        assert r["A"]["uncertainty_contribution"] == r["A"]["champion_ci_width_pct"]

    def test_no_uncertainty_without_glicko(self, minimal_data):
        """using_glicko=False does not add uncertainty_contribution."""
        positions, champions, stats = minimal_data
        r = aggregate_mc_results(
            positions, champions, stats, 3,
            compute_ci=True, using_glicko=False,
        )
        assert "uncertainty_contribution" not in r["A"]
