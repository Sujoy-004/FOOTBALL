"""The /api/blend view must report real fitted weights or an honest cold start.

Never fabricated weights, and never a degenerate (negative / non-normalized)
set. These assertions hold in both states, so a missing calibration artifact
degrades to cold_start instead of failing.
"""

from __future__ import annotations

import json

from competitions.laliga.src.constants import BLEND_CALIBRATION_PATH
from web.laliga_app import _CALIBRATION_THRESHOLD, api_blend

SHAPE_KEYS = {
    "n_signals_available",
    "available_signals",
    "blend_weights",
    "backtest_briers",
    "calibration_status",
    "n_matches_for_calibration",
    "threshold",
}


def _payload() -> dict:
    return json.loads(api_blend().body)


def test_blend_payload_shape_and_weight_validity():
    payload = _payload()

    assert SHAPE_KEYS <= set(payload)
    assert payload["calibration_status"] in ("calibrated", "cold_start")
    assert payload["threshold"] == _CALIBRATION_THRESHOLD
    assert payload["n_matches_for_calibration"] >= 0

    weights = payload["blend_weights"]
    if payload["calibration_status"] == "cold_start":
        assert weights == {}
        assert payload["available_signals"] == []
        assert payload["n_signals_available"] == 0
        return

    assert weights, "calibrated status must carry real weights"
    assert payload["n_signals_available"] == len(weights) == len(payload["available_signals"])
    assert payload["available_signals"] == sorted(weights)
    assert all(isinstance(w, (int, float)) for w in weights.values())
    assert all(w >= 0.0 for w in weights.values()), f"negative weight: {weights}"
    assert abs(sum(weights.values()) - 1.0) < 1e-6, f"weights do not sum to 1.0: {weights}"
    assert payload["n_matches_for_calibration"] >= _CALIBRATION_THRESHOLD


def test_fitted_artifact_uses_the_ucl_schema_and_a_passed_gate():
    """The on-disk artifact is the shared calibrator's own output, gate PASSed."""
    if not BLEND_CALIBRATION_PATH.exists():
        return

    config = json.loads(BLEND_CALIBRATION_PATH.read_text(encoding="utf-8"))

    assert {"version", "calibrated_at", "method", "source", "n_matches",
            "threshold", "weights", "per_signal"} <= set(config)
    assert config["method"] == "inverse_log_loss"
    assert config["verdict"]["status"] == "PASS", config["verdict"]["reasons"]
    # The view must never advertise a signal the deployed engine does not have.
    engine = json.loads(
        (BLEND_CALIBRATION_PATH.parent / "signal_weights.json").read_text(encoding="utf-8")
    )
    assert set(config["weights"]) <= set(engine["weights"])
