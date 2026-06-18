"""Governance: version tracking, drift detection, and model oversight.

Phase 16 — three-version approach (D-01):
  - data_version:  increments on material dataset changes (D-02)
  - model_version: increments on signal lineup / calibration changes (D-03)
  - run_version:   timestamp-based, updated per governance cycle (D-04)

All functions are pure (no I/O). State persistence is handled in state.py.
"""

import math
from datetime import datetime, timezone

from src.evaluation import brier_score


def _parse_version_number(version_str: str, prefix: str) -> int:
    """Parse version string like 'D14' or 'M7' to integer.

    Args:
        version_str: The version string (e.g., "D14", "M7", "R0").
        prefix: The expected prefix character (e.g., "D", "M", "R").

    Returns:
        Integer version number, or 0 if parsing fails.
    """
    if not version_str or not version_str.startswith(prefix):
        return 0
    try:
        return int(version_str[len(prefix):])
    except (ValueError, IndexError):
        return 0


def _format_version(prefix: str, number: int) -> str:
    """Format version number with prefix, e.g. ('D', 14) -> 'D14'."""
    return f"{prefix}{number}"


def _compute_data_version(
    old_versions: dict,
    prev_history: list[dict],
    new_history: list[dict],
) -> str:
    """Compute new data_version per D-02 increment conditions.

    Increments only when:
      (A) A new match_id appears in new_history that wasn't in prev_history, OR
      (B) An existing entry gained a new signal key not previously present.

    Args:
        old_versions: Current versions dict (must contain 'data_version').
        prev_history: Previous prediction_history entries (list of dicts).
        new_history: New/current prediction_history entries (list of dicts).

    Returns:
        New data_version string (e.g., "D5"), or the old version if no change.
    """
    # Build match_id sets
    prev_ids = {e["match_id"] for e in prev_history if "match_id" in e}
    new_ids = {e["match_id"] for e in new_history if "match_id" in e}

    # Condition A: new match_id appeared
    if new_ids - prev_ids:
        current = _parse_version_number(
            old_versions.get("data_version", "D0"), "D"
        )
        return _format_version("D", current + 1)

    # Condition B: existing entry gained a new signal key
    prev_by_id = {e["match_id"]: e for e in prev_history if "match_id" in e}
    new_by_id = {e["match_id"]: e for e in new_history if "match_id" in e}

    common_ids = prev_ids & new_ids
    for mid in common_ids:
        prev_sigs = set(prev_by_id[mid].get("signals", {}).keys())
        new_sigs = set(new_by_id[mid].get("signals", {}).keys())
        if new_sigs - prev_sigs:
            current = _parse_version_number(
                old_versions.get("data_version", "D0"), "D"
            )
            return _format_version("D", current + 1)

    # No change
    return old_versions.get("data_version", "D0")


def _compute_model_version(
    old_versions: dict,
    prev_signal_keys: list[str],
    new_signal_keys: list[str],
    calibration_changed: bool,
) -> str:
    """Compute new model_version per D-03 increment conditions.

    Increments when:
      - Signal keys differ (signals added or removed), OR
      - calibration_changed is True.

    Args:
        old_versions: Current versions dict (must contain 'model_version').
        prev_signal_keys: Previous active signal key list.
        new_signal_keys: New/current active signal key list.
        calibration_changed: True if calibration_params dict changed.

    Returns:
        New model_version string (e.g., "M3"), or the old version if no change.
    """
    if set(prev_signal_keys) != set(new_signal_keys) or calibration_changed:
        current = _parse_version_number(
            old_versions.get("model_version", "M0"), "M"
        )
        return _format_version("M", current + 1)

    return old_versions.get("model_version", "M0")


def _compute_run_version() -> str:
    """Compute new run_version per D-04 — ISO 8601 timestamp.

    Returns:
        ISO 8601 timestamp string via datetime.now(timezone.utc).isoformat().
    """
    return datetime.now(timezone.utc).isoformat()


def _maybe_update_versions(
    old_versions: dict,
    prev_history: list[dict],
    new_history: list[dict],
    prev_signal_keys: list[str],
    new_signal_keys: list[str],
    calibration_changed: bool,
) -> dict:
    """Compute and return updated versions dict.

    Calls all three _compute_* functions and updates timestamps.

    Args:
        old_versions: Current versions dict.
        prev_history: Previous prediction_history entries.
        new_history: New/current prediction_history entries.
        prev_signal_keys: Previous active signal key list.
        new_signal_keys: New/current active signal key list.
        calibration_changed: True if calibration_params changed.

    Returns:
        Updated versions dict with new version strings and timestamps.
    """
    now = datetime.now(timezone.utc).isoformat()
    new_versions = dict(old_versions)

    new_data = _compute_data_version(
        old_versions, prev_history, new_history
    )
    if new_data != old_versions.get("data_version"):
        new_versions["data_version"] = new_data
        new_versions["last_data_change"] = now

    new_model = _compute_model_version(
        old_versions, prev_signal_keys, new_signal_keys, calibration_changed
    )
    if new_model != old_versions.get("model_version"):
        new_versions["model_version"] = new_model
        new_versions["last_model_change"] = now

    new_versions["run_version"] = _compute_run_version()
    new_versions["last_run_timestamp"] = now

    return new_versions


# ─── Drift Detection (Plan 16-02) ──────────────────────────────────────────


def _deduplicate_history(entries: list[dict]) -> list[dict]:
    """Deduplicate prediction_history entries by match_id (Pitfall 7).

    Groups by match_id, keeps the last entry per match_id (list is
    chronologically ordered). Returns deduplicated list preserving order.

    Args:
        entries: List of prediction_history entry dicts.

    Returns:
        Deduplicated list with only the last entry per match_id.
    """
    seen: dict[str, dict] = {}
    order: list[str] = []
    for entry in entries:
        mid = entry.get("match_id")
        if mid is None:
            continue
        if mid not in seen:
            order.append(mid)
        seen[mid] = entry
    return [seen[mid] for mid in order]


def _per_match_briers(entries: list[dict], signal_key: str) -> list[float]:
    """Extract ordered per-match Brier scores for a signal.

    Per D-09, extracts per-match Brier scores for sigma computation.
    For each entry: checks signal availability, gets probability + actual,
    computes (p - a) ** 2 via brier_score().

    Args:
        entries: Prediction_history entries (deduplicated recommended).
        signal_key: Signal name (e.g., "elo", "market_odds").

    Returns:
        Ordered list of per-match Brier scores for valid entries.
    """
    briers: list[float] = []
    for entry in entries:
        signals = entry.get("signals", {})
        sig = signals.get(signal_key)
        if not sig or not sig.get("available", False):
            continue
        prob = sig.get("probability")
        actual = entry.get("actual")
        if prob is None or actual is None:
            continue
        briers.append(brier_score(prob, actual))
    return briers


def check_drift(
    entries: list[dict],
    signal_key: str,
    reference_baseline: float,
    window: int = 50,
    sigma_threshold: float = 2.0,
) -> dict | None:
    """Check if a signal has drifted from its reference baseline.

    Per D-09 formula:
      rolling_sigma = std(per_match_briers in last window matches)
      drift_alert = rolling_mean > reference_baseline + 2 * rolling_sigma

    Args:
        entries: Deduplicated prediction_history entries.
        signal_key: Signal name to check.
        reference_baseline: Fixed reference Brier for this signal.
        window: Rolling window size (default 50).
        sigma_threshold: Number of sigma above baseline for drift (default 2.0).

    Returns:
        Dict with drift info if check performed, or None if insufficient data.
        Dict keys: signal, rolling_mean, reference_baseline, sigma, threshold, drifted.
    """
    per_match = _per_match_briers(entries, signal_key)

    # Cold-start guard (D-10, Pitfall 3)
    from src.constants import COLD_START_THRESHOLD

    if len(per_match) < COLD_START_THRESHOLD:
        return None

    # Rolling window
    rolling = per_match[-window:] if len(per_match) > window else per_match
    n = len(rolling)
    if n == 0:
        return None

    rolling_mean = sum(rolling) / n

    # Population standard deviation
    if n >= 2:
        variance = sum((x - rolling_mean) ** 2 for x in rolling) / n
        sigma = math.sqrt(variance)
    else:
        sigma = 0.0

    threshold = reference_baseline + sigma_threshold * sigma
    drifted = rolling_mean > threshold
    delta = rolling_mean - threshold if drifted else 0.0

    return {
        "signal": signal_key,
        "rolling_mean": rolling_mean,
        "reference_baseline": reference_baseline,
        "sigma": sigma,
        "threshold": threshold,
        "drifted": drifted,
        "delta": delta,
    }


def compute_reference_baselines(entries: list[dict], signal_keys: list[str]) -> dict[str, float]:
    """Compute reference baselines (overall Brier) for each signal.

    Uses all entries for each signal to compute the overall mean Brier.
    This serves as the fixed reference baseline per D-08.

    Args:
        entries: Deduplicated prediction_history entries.
        signal_keys: List of signal keys to compute baselines for.

    Returns:
        Dict mapping signal_key -> overall Brier score.
    """
    baselines: dict[str, float] = {}
    for key in signal_keys:
        briers = _per_match_briers(entries, key)
        if briers:
            baselines[key] = sum(briers) / len(briers)
        else:
            baselines[key] = 1.0  # worst case for no data
    return baselines
