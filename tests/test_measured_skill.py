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
    delta_ci,
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
