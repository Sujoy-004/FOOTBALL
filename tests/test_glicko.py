"""Tests for Glicko-1 Bayesian rating system (Phase 10, Plan 02).

Tests cover:
    - g(RD) function: zero, monotonic, known values
    - expected_score_bayesian(): equal ratings, higher μ, σ deflation
    - update_glicko(): win/loss/draw, variance floor, k-multiplier
    - compute_glicko_k_factor(): goal-difference weighting
    - TeamRating dataclass
    - RatingSystem lifecycle: default, set/get, serialize, update
    - _sample_glicko_elos(): count, bounds, reproducibility
"""

import math
import random

import pytest

from football_core.glicko import (
    Q,
    g,
    expected_score_bayesian,
    update_glicko,
    compute_glicko_k_factor,
    TeamRating,
    RatingSystem,
    DEFAULT_MU,
    DEFAULT_SIGMA,
    MIN_SIGMA_SQ,
)
from competitions.ucl.src.simulation import _sample_glicko_elos


# ═══════════════════════════════════════════════════════════════════════════════
# ── g(RD) function
# ═══════════════════════════════════════════════════════════════════════════════


class TestGFunction:
    """Glicko-1 g(RD) probability deflation factor."""

    def test_g_zero_returns_one(self):
        """g(0) must equal 1.0 (zero uncertainty → full impact)."""
        assert g(0.0) == 1.0

    def test_g_monotonically_decreasing(self):
        """g(RD) must decrease as RD increases."""
        assert g(0.0) > g(100.0) > g(200.0) > g(350.0)

    def test_g_always_positive(self):
        """g(RD) must always be positive for finite RD."""
        for rd in [0.0, 10.0, 100.0, 200.0, 350.0, 500.0, 1000.0]:
            assert g(rd) > 0.0, f"g({rd}) = {g(rd)}"

    def test_g_known_numerical_values(self):
        """Check g(RD) against computed values using the Q² formula."""
        # g(RD) = 1 / sqrt(1 + 3 * Q² * RD² / π²)
        # Q = ln(10) / 400 ≈ 0.0057565
        q_sq = Q ** 2
        pi_sq = math.pi ** 2

        expected_100 = 1.0 / math.sqrt(1.0 + 3.0 * q_sq * 10000.0 / pi_sq)
        expected_350 = 1.0 / math.sqrt(1.0 + 3.0 * q_sq * 122500.0 / pi_sq)

        assert abs(g(100.0) - expected_100) < 1e-10
        assert abs(g(350.0) - expected_350) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# ── expected_score_bayesian
# ═══════════════════════════════════════════════════════════════════════════════


class TestExpectedScoreBayesian:
    """Bayesian expected score with opponent uncertainty."""

    def test_equal_ratings_returns_half(self):
        """Equal means must give expected score of 0.5 regardless of σ."""
        for sigma in [0.0, 50.0, 100.0, 350.0]:
            e = expected_score_bayesian(1500.0, 1500.0, sigma)
            assert abs(e - 0.5) < 1e-10, f"sigma={sigma}: e={e}"

    def test_higher_mu_increases_expected_score(self):
        """Higher μ_a must give expected score > 0.5."""
        e = expected_score_bayesian(1650.0, 1500.0, 100.0)
        assert e > 0.5

    def test_lower_mu_decreases_expected_score(self):
        """Lower μ_a must give expected score < 0.5."""
        e = expected_score_bayesian(1350.0, 1500.0, 100.0)
        assert e < 0.5

    def test_deflation_with_higher_uncertainty(self):
        """Higher σ_b must pull expected score closer to 0.5."""
        e_low_sigma = expected_score_bayesian(1650.0, 1500.0, 0.0)
        e_high_sigma = expected_score_bayesian(1650.0, 1500.0, 350.0)
        # Deflation: high sigma → probability closer to 0.5
        assert abs(e_high_sigma - 0.5) < abs(e_low_sigma - 0.5), \
            f"deflation: {e_low_sigma:.4f} -> {e_high_sigma:.4f}"

    def test_zero_sigma_matches_standard_elo(self):
        """σ_b=0 should give same result as standard Elo expected_score."""
        from football_core.elo import expected_score
        e_glicko = expected_score_bayesian(1800.0, 1500.0, 0.0)
        e_elo = expected_score(1800.0, 1500.0)
        assert abs(e_glicko - e_elo) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# ── update_glicko
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateGlicko:
    """Glicko-1 closed-form (μ, σ²) update."""

    def test_win_increases_mu(self):
        """Score 1.0 must increase μ."""
        mu_new, _ = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 1.0)
        assert mu_new > 1500.0

    def test_loss_decreases_mu(self):
        """Score 0.0 must decrease μ."""
        mu_new, _ = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 0.0)
        assert mu_new < 1500.0

    def test_both_reduce_sigma_sq(self):
        """Both win and loss must reduce σ² (more information → less uncertainty)."""
        _, sq_win = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 1.0)
        _, sq_loss = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 0.0)
        assert sq_win < 350.0 ** 2
        assert sq_loss < 350.0 ** 2

    def test_draw_equal_ratings_keeps_mu(self):
        """Draw with equal ratings must keep μ ≈ same."""
        mu_new, _ = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 0.5)
        assert abs(mu_new - 1500.0) < 1.0

    def test_draw_reduces_sigma_sq(self):
        """Draw must still reduce σ² (any match outcome provides information)."""
        _, sq_new = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 0.5)
        assert sq_new < 350.0 ** 2

    def test_variance_floor_enforced(self):
        """σ² must never fall below MIN_SIGMA_SQ."""
        _, sq_new = update_glicko(1500.0, 50.0 ** 2, 1500.0, 50.0 ** 2, 1.0)
        assert sq_new >= MIN_SIGMA_SQ

    def test_repeated_updates_stay_above_floor(self):
        """Repeated updates should not let σ² drop below MIN_SIGMA_SQ."""
        mu, sigma_sq = 1500.0, 350.0 ** 2
        for _ in range(20):
            mu, sigma_sq = update_glicko(mu, sigma_sq, 1500.0, 350.0 ** 2, 0.5)
            assert sigma_sq >= MIN_SIGMA_SQ, f"σ²={sigma_sq} below floor after {_} updates"

    def test_k_multiplier_increases_mu_change(self):
        """k > 1 must produce larger |Δμ| than k = 1."""
        _, sq_k1 = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 1.0, k_multiplier=1.0)
        _, sq_k2 = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 1.0, k_multiplier=2.0)

        mu_k1, _ = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 1.0, k_multiplier=1.0)
        mu_k2, _ = update_glicko(1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 1.0, k_multiplier=2.0)

        delta_k1 = abs(mu_k1 - 1500.0)
        delta_k2 = abs(mu_k2 - 1500.0)
        assert delta_k2 > delta_k1, f"k=1: Δμ={delta_k1:.2f}, k=2: Δμ={delta_k2:.2f}"
        assert sq_k2 < sq_k1, "k=2 must also reduce σ² more than k=1"

    def test_zero_k_multiplier_no_update(self):
        """k_multiplier=0 means no information from this match — no update."""
        mu_new, sq_new = update_glicko(
            1500.0, 350.0 ** 2, 1500.0, 350.0 ** 2, 1.0, k_multiplier=0.0,
        )
        assert mu_new == 1500.0, "No mu change expected with k=0"
        assert sq_new == 350.0 ** 2, "No sigma_sq change expected with k=0"


# ═══════════════════════════════════════════════════════════════════════════════
# ── compute_glicko_k_factor
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeGlickoKFactor:
    """Goal-difference information multiplier."""

    def test_goal_diff_0_returns_base(self):
        """goal_diff ≤ 1 must return base_K unchanged."""
        assert compute_glicko_k_factor(0, 1.0) == 1.0
        assert compute_glicko_k_factor(1, 1.0) == 1.0

    def test_goal_diff_2_returns_one_point_five(self):
        """goal_diff = 2 must return base_K * 1.5."""
        result = compute_glicko_k_factor(2, 1.0)
        assert result == 1.5

    def test_goal_diff_4_formula(self):
        """goal_diff ≥ 3 must return base_K * (11 + goal_diff) / 8."""
        result = compute_glicko_k_factor(4, 1.0)
        expected = (11 + 4) / 8.0
        assert result == expected

    def test_goal_diff_0_with_custom_base(self):
        """Custom base_K should be respected."""
        result = compute_glicko_k_factor(0, 2.0)
        assert result == 2.0

    def test_goal_diff_3_boundary(self):
        """goal_diff=3 is the boundary of the ≥3 branch."""
        result = compute_glicko_k_factor(3, 1.0)
        expected = (11 + 3) / 8.0
        assert result == expected


# ═══════════════════════════════════════════════════════════════════════════════
# ── TeamRating
# ═══════════════════════════════════════════════════════════════════════════════


class TestTeamRating:
    """TeamRating N(μ, σ²) dataclass."""

    def test_sigma_sq_property(self):
        """sigma_sq should be sigma ** 2."""
        tr = TeamRating(1500.0, 100.0)
        assert tr.sigma_sq == 10000.0

    def test_zero_sigma(self):
        """sigma=0 should give sigma_sq=0."""
        tr = TeamRating(1500.0, 0.0)
        assert tr.sigma_sq == 0.0

    def test_dataclass_equality(self):
        """Two TeamRatings with same values should be equal."""
        tr1 = TeamRating(1500.0, 100.0)
        tr2 = TeamRating(1500.0, 100.0)
        assert tr1 == tr2


# ═══════════════════════════════════════════════════════════════════════════════
# ── RatingSystem
# ═══════════════════════════════════════════════════════════════════════════════


class TestRatingSystem:
    """RatingSystem lifecycle."""

    def test_new_team_gets_defaults(self):
        """Unseen teams must return DEFAULT_MU and DEFAULT_SIGMA."""
        rs = RatingSystem()
        r = rs.get_rating("NewTeam")
        assert r.mu == DEFAULT_MU
        assert r.sigma == DEFAULT_SIGMA

    def test_set_and_get(self):
        """set_rating followed by get_rating must return the same value."""
        rs = RatingSystem()
        rs.set_rating("TeamA", 1600.0, 75.0)
        r = rs.get_rating("TeamA")
        assert r.mu == 1600.0
        assert r.sigma == 75.0

    def test_to_from_dict_round_trip(self):
        """Export to dict and re-import must preserve all ratings."""
        rs = RatingSystem()
        rs.set_rating("TeamA", 1500.0, 100.0)
        rs.set_rating("TeamB", 1600.0, 200.0)
        rs.set_rating("TeamC", 1400.0, 50.0)

        data = rs.to_dict()
        rs2 = RatingSystem.from_dict(data)

        for team in ["TeamA", "TeamB", "TeamC"]:
            r1 = rs.get_rating(team)
            r2 = rs2.get_rating(team)
            assert abs(r1.mu - r2.mu) < 1e-10, f"{team} mu mismatch"
            assert abs(r1.sigma - r2.sigma) < 1e-10, f"{team} sigma mismatch"

    def test_to_elo_dict_returns_mu_only(self):
        """to_elo_dict must return {team: mu} without sigma."""
        rs = RatingSystem()
        rs.set_rating("TeamA", 1500.0, 100.0)
        rs.set_rating("TeamB", 1600.0, 200.0)
        ed = rs.to_elo_dict()
        assert ed == {"TeamA": 1500.0, "TeamB": 1600.0}

    def test_update_ratings_modifies_both(self):
        """update_ratings must update both teams' μ symmetrically."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 350.0)
        rs.set_rating("B", 1500.0, 350.0)
        rs.update_ratings("A", "B", 1.0, 0.0)
        ra = rs.get_rating("A")
        rb = rs.get_rating("B")
        assert ra.mu > 1500.0, "Winner should gain rating"
        assert rb.mu < 1500.0, "Loser should lose rating"
        # Symmetry: Δμ_A ≈ -Δμ_B (approximately for equal ratings)
        assert abs((ra.mu - 1500.0) + (rb.mu - 1500.0)) < 1.0

    def test_update_ratings_with_k_multiplier(self):
        """update_ratings must accept k_multiplier via RatingSystem."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 350.0)
        rs.set_rating("B", 1500.0, 350.0)
        rs.update_ratings("A", "B", 1.0, 0.0, k_multiplier=2.0)
        ra = rs.get_rating("A")
        rb = rs.get_rating("B")
        # k=2 should produce larger Δμ than k=1 (tested above) — just verify works
        assert ra.mu != 1500.0
        assert rb.mu != 1500.0

    def test_teams_returns_stored_teams(self):
        """teams() must return only explicitly stored ratings."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 100.0)
        rs.set_rating("B", 1500.0, 100.0)
        teams = rs.teams()
        assert len(teams) == 2
        team_names = {t for t, _ in teams}
        assert team_names == {"A", "B"}


# ═══════════════════════════════════════════════════════════════════════════════
# ── _sample_glicko_elos
# ═══════════════════════════════════════════════════════════════════════════════


class TestSampleGlickoElos:
    """MC sampling from Glicko-1 N(μ, σ²) distributions."""

    def test_returns_correct_team_count(self):
        """_sample_glicko_elos must return an entry for every team in the RS."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 100.0)
        rs.set_rating("B", 1600.0, 200.0)
        rs.set_rating("C", 1400.0, 50.0)
        rng = random.Random(42)
        elos = _sample_glicko_elos(rs, rng)
        assert len(elos) == 3
        assert set(elos.keys()) == {"A", "B", "C"}

    def test_values_bounded(self):
        """Sampled μ values must be in [0, 3000]."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 1000.0)  # High sigma to test clamping
        rng = random.Random(42)
        for _ in range(100):
            elos = _sample_glicko_elos(rs, rng)
            for v in elos.values():
                assert 0.0 <= v <= 3000.0, f"Sampled value {v} out of bounds"

    def test_reproducible_with_same_seed(self):
        """Same seed → same sample (deterministic via seeded rng)."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 100.0)

        rng1 = random.Random(123)
        rng2 = random.Random(123)
        e1 = _sample_glicko_elos(rs, rng1)
        e2 = _sample_glicko_elos(rs, rng2)
        assert e1 == e2

    def test_different_seed_different_sample(self):
        """Different seed must (likely) produce different samples."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 100.0)
        rs.set_rating("B", 1500.0, 100.0)

        rng1 = random.Random(42)
        rng2 = random.Random(999)
        e1 = _sample_glicko_elos(rs, rng1)
        e2 = _sample_glicko_elos(rs, rng2)
        # Almost certainly different
        assert e1 != e2

    def test_mean_convergence(self):
        """Mean of many samples should be close to μ (law of large numbers)."""
        rs = RatingSystem()
        rs.set_rating("TestTeam", 1500.0, 50.0)

        samples = []
        for seed_i in range(5000):
            rng = random.Random(seed_i)
            elos = _sample_glicko_elos(rs, rng)
            samples.append(elos["TestTeam"])

        mean = sum(samples) / len(samples)
        assert abs(mean - 1500.0) < 5.0, f"Mean {mean:.2f} too far from 1500"

    def test_zero_sigma_returns_mu(self):
        """σ=0 must always return exactly μ (no sampling noise)."""
        rs = RatingSystem()
        rs.set_rating("A", 1500.0, 0.0)
        for seed_i in range(20):
            rng = random.Random(seed_i)
            elos = _sample_glicko_elos(rs, rng)
            assert elos["A"] == 1500.0
