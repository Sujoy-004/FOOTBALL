"""Behaviour-locking tests for the promoted paired-bootstrap statistics.

Covers D-09 (one copy), D-14 (fixed seed, CI-only output), and the /3 Brier
convention.  No p-value is ever produced — the public shape is a CI plus a
boolean, never a significance claim.
"""

from __future__ import annotations

import numpy as np
import pytest

from football_core.historical_backfill import (
    BOOT_SEED,
    N_BOOT,
    bootstrap_cis,
    declare_skill,
    delta_ci,
    holm_thresholds,
    mde_for_n,
    pooled_metrics,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_cache(n: int = 50, seed: int = 42) -> dict[str, dict]:
    """Build a synthetic per-match cache with two models."""
    rng = np.random.default_rng(seed)
    cache: dict[str, dict] = {}
    for name in ("model_a", "model_b"):
        ll = rng.uniform(0.5, 1.5, size=n)
        brier = rng.uniform(0.3, 0.9, size=n)
        conf = rng.uniform(0.3, 0.8, size=n)
        hit = rng.integers(0, 2, size=n).astype(bool)
        cache[name] = {"n": n, "ll": ll, "brier": brier, "conf": conf, "hit": hit}
    return cache


# ── promoted bootstrap ───────────────────────────────────────────────────────


class TestDeterminism:
    """Two calls with identical cache produce identical output."""

    def test_bootstrap_cis_deterministic(self):
        cache = _make_cache()
        out1 = bootstrap_cis(cache)
        out2 = bootstrap_cis(cache)
        assert out1 == out2

    def test_delta_ci_deterministic(self):
        cache = _make_cache()
        out1 = delta_ci(cache, "model_a", "model_b")
        out2 = delta_ci(cache, "model_a", "model_b")
        assert out1 == out2

    def test_bootstrap_cis_with_pairs_deterministic(self):
        cache = _make_cache()
        pairs = [("model_a", "model_b")]
        out1 = bootstrap_cis(cache, pairs=pairs)
        out2 = bootstrap_cis(cache, pairs=pairs)
        assert out1 == out2


class TestPairing:
    """delta_ci point estimate is consistent with pooled_metrics difference.

    The bootstrap mean with finite resamples approximates but does not exactly
    equal the raw mean; a tolerance of 0.01 is well within bootstrap error.
    """

    def test_delta_approx_equals_pooled_diff(self):
        cache = _make_cache()
        d = delta_ci(cache, "model_a", "model_b")["delta_ll"]
        diff = (
            pooled_metrics(cache["model_a"])["log_loss"]
            - pooled_metrics(cache["model_b"])["log_loss"]
        )
        assert d == pytest.approx(diff, abs=0.01)


class TestBrierConvention:
    """Brier is mean of per-match squared-error vector length, scaled by 1/3."""

    def test_brier_div3(self):
        cache = _make_cache()
        c = cache["model_a"]
        expected = round(float(c["brier"].mean() / 3), 6)
        assert pooled_metrics(c)["brier"] == expected


class TestNoPValue:
    """No p / p_value key appears anywhere in the returned dicts."""

    def test_bootstrap_cis_no_p_value(self):
        cache = _make_cache()
        out = bootstrap_cis(cache, pairs=[("model_a", "model_b")])
        _assert_no_p_value(out)

    def test_delta_ci_no_p_value(self):
        cache = _make_cache()
        out = delta_ci(cache, "model_a", "model_b")
        _assert_no_p_value(out)

    def test_pooled_metrics_no_p_value(self):
        cache = _make_cache()
        out = pooled_metrics(cache["model_a"])
        _assert_no_p_value(out)


def _assert_no_p_value(obj):
    """Recursively assert no 'p' or 'p_value' key exists in a nested dict."""
    if isinstance(obj, dict):
        for key in obj:
            assert key not in ("p", "p_value"), f"found forbidden key: {key}"
            _assert_no_p_value(obj[key])
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_p_value(item)


# ── constants ────────────────────────────────────────────────────────────────


class TestConstants:
    """BOOT_SEED and N_BOOT are fixed at the locked values."""

    def test_boot_seed(self):
        assert BOOT_SEED == 20260601

    def test_n_boot(self):
        assert N_BOOT == 2000


# ── MDE ─────────────────────────────────────────────────────────────────────


class TestMde:
    """mde_for_n reproduces both locked anchors (D-14)."""

    def test_anchor_144(self):
        assert mde_for_n(144) == pytest.approx(0.058, abs=0.001)

    def test_anchor_104(self):
        assert mde_for_n(104) == pytest.approx(0.069, abs=0.001)

    def test_known_value(self):
        # (1.959964 + 0.841621) * 0.25 / 12 = 0.058366...
        assert mde_for_n(144) == 0.058366


# ── Holm ─────────────────────────────────────────────────────────────────────


class TestHolm:
    """holm_thresholds yields the step-down critical levels, strongest first."""

    def test_six_levels(self):
        levels = holm_thresholds(6)
        assert levels == pytest.approx(
            [0.05 / 6, 0.05 / 5, 0.05 / 4, 0.05 / 3, 0.05 / 2, 0.05], abs=1e-6
        )

    def test_ordering_and_sum(self):
        levels = holm_thresholds(6)
        assert levels == sorted(levels)
        assert levels[0] == pytest.approx(0.008333, abs=1e-6)
        assert levels[-1] == 0.05
        assert sum(levels) == pytest.approx(0.1225, abs=1e-6)

    def test_custom_alpha(self):
        assert holm_thresholds(4, alpha=0.10) == pytest.approx(
            [0.025, 1 / 30, 0.05, 0.10], abs=1e-6
        )


# ── verdict ─────────────────────────────────────────────────────────────────


def _comp(delta: float, lo: float, hi: float) -> dict:
    return {"delta": delta, "2.5": lo, "97.5": hi}


def _all_favourable() -> dict:
    return {
        "ensemble_vs_uniform__log_loss": _comp(-0.05, -0.10, -0.01),
        "ensemble_vs_freq__log_loss": _comp(-0.04, -0.09, -0.005),
        "ensemble_vs_elo_only__log_loss": _comp(-0.03, -0.08, -0.002),
        "ensemble_vs_uniform__brier": _comp(-0.02, -0.07, -0.001),
        "ensemble_vs_freq__brier": _comp(-0.015, -0.06, -0.004),
        "ensemble_vs_elo_only__brier": _comp(-0.01, -0.05, -0.003),
    }


def _freq_wins_both() -> dict:
    return {
        "ensemble_vs_uniform__log_loss": _comp(-0.05, -0.10, -0.01),
        "ensemble_vs_freq__log_loss": _comp(0.02, -0.01, 0.05),
        "ensemble_vs_elo_only__log_loss": _comp(-0.03, -0.08, -0.002),
        "ensemble_vs_uniform__brier": _comp(-0.02, -0.07, -0.001),
        "ensemble_vs_freq__brier": _comp(0.01, -0.005, 0.03),
        "ensemble_vs_elo_only__brier": _comp(-0.01, -0.05, -0.003),
    }


class TestVerdict:
    """declare_skill (D-16): all-six-favourable declares, otherwise names winner."""

    def test_skill_declared(self):
        out = declare_skill(_all_favourable(), n=144)
        assert out["verdict"] == "skill declared"
        assert out["won_by"] is None
        assert out["mde"] == pytest.approx(0.058, abs=0.001)
        assert out["n"] == 144
        assert len(out["comparisons"]) == 6
        assert all(c["favourable"] for c in out["comparisons"])

    def test_not_declared_names_winner(self):
        out = declare_skill(_freq_wins_both(), n=619)
        assert out["verdict"] == "not declared"
        assert out["won_by"] == "freq"
        assert out["n"] == 619
        assert out["mde"] == mde_for_n(619)

    def test_missing_comparison_raises(self):
        bad = _all_favourable()
        del bad["ensemble_vs_freq__brier"]
        with pytest.raises(ValueError, match="freq"):
            declare_skill(bad, n=100)

    def test_no_p_value_in_output(self):
        for comp in declare_skill(_all_favourable(), n=144)["comparisons"]:
            assert "p_value" not in comp
            assert "p" not in comp

    def test_holm_step_down_freezes(self):
        # The weakest favourable comparison has a CI including zero, so it and
        # everything after it (less favourable by ranking) do not survive.
        comps = _all_favourable()
        comps["ensemble_vs_elo_only__brier"] = _comp(-0.01, -0.05, 0.02)
        out = declare_skill(comps, n=144)
        by_name = {c["comparison"]: c for c in out["comparisons"]}
        assert by_name["ensemble_vs_elo_only__brier"]["survives_holm"] is False
        # Still declared: the point deltas are all favourable (D-16).
        assert out["verdict"] == "skill declared"
