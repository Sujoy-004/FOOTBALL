"""Behaviour-locking tests for the promoted paired-bootstrap statistics.

Covers D-09 (one copy), D-14 (fixed seed, CI-only output), and the /3 Brier
convention.  No p-value is ever produced — the public shape is a CI plus a
boolean, never a significance claim.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from football_core.historical_backfill import (
    BOOT_SEED,
    N_BOOT,
    Harness,
    bootstrap_cis,
    declare_skill,
    delta_ci,
    holm_thresholds,
    mde_for_n,
    pooled_metrics,
    run_evaluation,
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


# ── holdout block (D-02 / D-13 / D-14 / D-16) ─────────────────────────────────


def _ucl_harness() -> Harness:
    from competitions.ucl.src.historical import (
        ReplayResultProvider,
        build_context_for_match,
        frequency_baseline,
        load_replay_matches,
        order_matches,
        outcome_index,
    )

    return Harness(
        build_context=build_context_for_match,
        outcome_index=outcome_index,
        order_matches=order_matches,
        frequency_baseline=frequency_baseline,
        replay_provider=ReplayResultProvider,
        load_replay_matches=load_replay_matches,
    )


def _write_season(root, season: str, matches: list[dict], elo: dict) -> None:
    sdir = root / season
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "matches.json").write_text(json.dumps(matches), encoding="utf-8")
    (sdir / "elo_ratings.json").write_text(json.dumps(elo), encoding="utf-8")


def _synthetic_corpus(tmp_path) -> None:
    """Two seasons straddling the cutoff; every match completed, 8 teams."""
    teams = [f"T{i}" for i in range(8)]
    elo = {t: 1500.0 + 10 * i for i, t in enumerate(teams)}

    def mk(prefix: str, n: int, year: int) -> list[dict]:
        rows = []
        for k in range(n):
            i, j = (2 * k) % 8, (2 * k + 1) % 8
            hs, aw = (2, 0) if k % 2 == 0 else (1, 1)
            rows.append({
                "match_id": f"{prefix}{k}",
                "team_a": teams[i],
                "team_b": teams[j],
                "event_date": f"{year}-03-{k + 1:02d}T00:00:00Z",
                "home_score": hs,
                "away_score": aw,
            })
        return rows

    _write_season(tmp_path, "2019_20", mk("A", 4, 2019), elo)
    _write_season(tmp_path, "2021_22", mk("B", 4, 2021), elo)


def _run(tmp_path):
    out = tmp_path / "eval_results.json"
    return run_evaluation(
        str(out), str(tmp_path), ["2019_20", "2021_22"],
        ["market_odds", "refined_elo", "rolling_form", "rest_days"],
        {"market_odds": 0.2, "refined_elo": 0.2, "rolling_form": 0.2,
         "rest_days": 0.2, "squad_value": 0.2},
        "synthetic-test-corpus", _ucl_harness(),
    )


def _assert_no_p_key(obj, path="$") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key not in ("p", "p_value"), f"forbidden key {key!r} at {path}"
            _assert_no_p_key(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _assert_no_p_key(value, f"{path}[{i}]")


class TestHoldoutBlock:
    def test_holdout_block_shape_and_determinism(self, tmp_path):
        _synthetic_corpus(tmp_path)
        results = _run(tmp_path)
        holdout = results["holdout"]

        # split record
        assert holdout["split"] == "single fixed chronological (D-02)"
        assert holdout["cutoff"] == "2020-12-31T23:59:59Z"
        assert holdout["n_train"] == 4
        assert holdout["n_test"] == 4
        assert holdout["min_train"] < holdout["min_test"]
        assert holdout["bootstrap"]["seed"] == BOOT_SEED
        assert holdout["bootstrap"]["n_boot"] == N_BOOT

        # render-facing comparisons: single "delta" key, no delta_ll leak
        assert set(holdout["comparisons"]) == {
            "ensemble_vs_uniform", "ensemble_vs_freq",
            "ensemble_vs_elo_only", "ensemble_vs_market_only",
        }
        for comp in holdout["comparisons"].values():
            assert set(comp) == {"delta", "2.5", "97.5", "mde", "n"}
            assert comp["n"] == 4

        # ordered score: ordered_brier == rps/2, declared order
        ordered = holdout["ordered"]
        assert ordered["order"] == ["home", "draw", "away"]
        assert ordered["ordered_brier"] == round(ordered["rps"] / 2, 6)
        assert ordered["note"] == "secondary, not a gate"

        # tournament-level TRPS block: trps + construction present
        tt = holdout["tournament_trps"]
        assert "trps" in tt
        assert "construction" in tt
        assert tt["n_tournaments"] == 1
        assert tt["order"] == "rank 1 = top"

        # calibration overall carries slope/intercept/n
        cal = holdout["calibration_slope_intercept"]["overall"]
        assert {"slope", "intercept", "n"} <= set(cal)

        # verdict + classwise ECE present
        assert holdout["verdict"]["verdict"] in ("skill declared", "not declared")
        assert "classwise_ece" in holdout

        # no p-value anywhere in the returned artifact
        _assert_no_p_key(results)

        # deterministic: a second run reproduces the identical holdout
        again = _run(tmp_path)
        assert again["holdout"] == holdout
