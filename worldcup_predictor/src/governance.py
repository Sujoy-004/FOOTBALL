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


# ─── Governance Orchestrator (Plan 16-02) ─────────────────────────────────


def _run_governance(
    entries: list[dict],
    versions: dict,
    signal_keys: list[str],
    blend_weights: dict[str, float],
    startup: bool = False,
    teams: dict | None = None,
) -> dict:
    """Run one governance cycle: compute metrics, check drift, build snapshot.

    Args:
        entries: Deduplicated prediction_history entries.
        versions: Current version state from load_versions().
        signal_keys: Ordered list of active signal keys.
        blend_weights: Current blend weights from calibrate_and_blend().
        startup: True if called during startup (triggers backtest + reference baseline init).
        teams: Team data dict (needed for backtest at startup). Defaults to None.

    Returns:
        dict: Run snapshot per D-06 schema.
    """
    import sys

    from src.constants import COLD_START_THRESHOLD

    # ── Startup backtest ──
    backtest_summary: str | None = None
    if startup and teams is not None:
        try:
            backtest_results = _run_backtest(teams)
            if backtest_results:
                best_sig = (
                    backtest_results["signal_ranking"][0]
                    if backtest_results["signal_ranking"]
                    else "?"
                )
                best_brier = (
                    backtest_results["per_signal"]
                    .get(best_sig, {})
                    .get("brier", 0.0)
                )
                backtest_summary = (
                    f"{backtest_results['n_total_matches']} matches | "
                    f"Best: {best_sig} Brier={best_brier:.4f}"
                )
        except Exception as e:
            print(f"Backtest failed: {e}", file=sys.stderr)
            backtest_summary = None

    # 1. Deduplicate entries
    deduped = _deduplicate_history(entries)
    n_matches = len(deduped)

    # 2. Compute per-signal rolling Brier
    per_signal_brier: dict[str, float] = {}
    from src.blender import compute_rolling_brier

    for key in signal_keys:
        brier = compute_rolling_brier(deduped, key, window=50)
        per_signal_brier[key] = brier

    # 3. Compute/blend blended Brier
    blended_brier = 0.0
    if "blended" in signal_keys:
        blended_brier = per_signal_brier.get("blended", 0.0)
    elif per_signal_brier and blend_weights:
        # Weighted average of per-signal briers
        total_weight = sum(blend_weights.values()) or 1.0
        blended_brier = sum(
            per_signal_brier.get(k, 0.0) * w / total_weight
            for k, w in blend_weights.items()
            if k in per_signal_brier
        )

    # 4. Compute or load reference baselines
    reference_baselines = compute_reference_baselines(deduped, signal_keys)

    # 5. Check drift per signal
    drift_details: list[dict] = []
    for key in signal_keys:
        baseline = reference_baselines.get(key, 1.0)
        result = check_drift(deduped, key, baseline, window=50, sigma_threshold=2.0)
        if result is not None and result.get("drifted", False):
            drift_details.append(result)

    # 6. Determine drift_status
    if n_matches < COLD_START_THRESHOLD:
        drift_status = "COLD_START"
    elif drift_details:
        drift_status = "DRIFT"
    else:
        drift_status = "HEALTHY"

    # 7. Signal counts
    signal_counts: dict[str, int] = {}
    for key in signal_keys:
        count = sum(
            1 for e in deduped
            if e.get("signals", {}).get(key, {}).get("available", False)
        )
        signal_counts[key] = count

    # 8. Build snapshot dict (D-06 schema)
    snapshot = {
        "run_version": versions.get("run_version", _compute_run_version()),
        "data_version": versions.get("data_version", "D0"),
        "model_version": versions.get("model_version", "M0"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signal_counts": signal_counts,
        "blend_weights": dict(blend_weights),
        "per_signal_brier": per_signal_brier,
        "blended_brier": blended_brier,
        "drift_status": drift_status,
        "drift_details": drift_details if drift_details else None,
    }

    # 9. Save snapshot via state.py
    from src.state import save_run_snapshot

    save_run_snapshot(snapshot)

    # 10. Print governance dashlet
    from src.output import print_governance_dashlet

    drift_results_dict: dict[str, dict] = {}
    for d in drift_details:
        drift_results_dict[d.get("signal", "?")] = d

    print_governance_dashlet(
        versions=versions,
        status=drift_status.replace("_", " "),
        n_matches=n_matches,
        per_signal_brier=per_signal_brier,
        blend_weights=blend_weights,
        drift_results=drift_results_dict if drift_results_dict else None,
        backtest_summary=backtest_summary,
    )

    return snapshot


# ─── Backtest Orchestrator (Plan 16-03) ─────────────────────────────────


def _run_backtest(
    teams: dict[str, dict],
    historical_data_dir: str | None = None,
) -> dict | None:
    """Run backtesting against all historical tournament files.

    One-shot at startup. Loads each historical tournament file,
    replays through backtest_tournament(), collects per-tournament reports,
    produces aggregate report, saves to eval_backtest_report.json.

    Args:
        teams: Current team data (deep-copied for replay by backtest_tournament).
        historical_data_dir: Path to data/historical/ directory.
            Defaults to constants.DATA_DIR / "historical".

    Returns:
        Aggregate report dict with per-tournament results, or None if no data.
    """
    import json
    import sys
    from pathlib import Path

    from src.constants import DATA_DIR, GOV_BACKTEST_TOURNAMENTS
    from src.evaluation import backtest_tournament
    from src.state import save_backtest_report

    if historical_data_dir is None:
        historical_dir = DATA_DIR / "historical"
    else:
        historical_dir = Path(historical_data_dir)

    per_tournament_reports: list[dict] = []

    for tournament in GOV_BACKTEST_TOURNAMENTS:
        file_path = historical_dir / f"{tournament}.json"
        if not file_path.exists():
            print(
                f"Backtest: {tournament} data not found at {file_path}",
                file=sys.stderr,
            )
            continue
        try:
            with open(file_path, encoding="utf-8") as f:
                matches: list[dict] = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"Backtest: failed to load {tournament} data: {e}",
                file=sys.stderr,
            )
            continue

        report = backtest_tournament(matches, teams, tournament_name=tournament)
        per_tournament_reports.append(report)

    if not per_tournament_reports:
        return None

    # Build aggregate report
    tournaments = [r["tournament"] for r in per_tournament_reports]
    n_total_matches = sum(r["n_matches"] for r in per_tournament_reports)

    # Aggregate per-signal metrics across tournaments (weighted by n_matches)
    all_signal_keys: set[str] = set()
    for r in per_tournament_reports:
        all_signal_keys.update(r.get("per_signal", {}).keys())

    aggregate_per_signal: dict[str, dict] = {}
    for signal_key in sorted(all_signal_keys):
        total_brier = 0.0
        total_ll = 0.0
        total_n = 0
        for r in per_tournament_reports:
            ps = r.get("per_signal", {})
            if signal_key in ps:
                sig_n = ps[signal_key].get("n", 0)
                total_brier += ps[signal_key].get("brier", 0.0) * sig_n
                total_ll += ps[signal_key].get("log_loss", 0.0) * sig_n
                total_n += sig_n
        if total_n > 0:
            aggregate_per_signal[signal_key] = {
                "brier": round(total_brier / total_n, 6),
                "log_loss": round(total_ll / total_n, 6),
                "n": total_n,
            }

    # Signal ranking: sorted by aggregate Brier ascending
    signal_ranking = sorted(
        aggregate_per_signal, key=lambda k: aggregate_per_signal[k]["brier"]
    )

    # Governance recommendation
    best_signal = signal_ranking[0] if signal_ranking else None
    if best_signal:
        rec = (
            f"Best signal: {best_signal} "
            f"(Brier={aggregate_per_signal[best_signal]['brier']:.4f}). "
            f"Backtest across {n_total_matches} matches from "
            f"{', '.join(tournaments)}."
        )
    else:
        rec = (
            f"Backtest ran with no computable metrics "
            f"across {n_total_matches} matches."
        )

    aggregate_report = {
        "tournaments": tournaments,
        "n_total_matches": n_total_matches,
        "per_signal": aggregate_per_signal,
        "signal_ranking": signal_ranking,
        "governance_recommendation": rec,
    }

    save_backtest_report(aggregate_report)

    # Print backtest summary line
    if best_signal:
        print(
            f"Backtest: {', '.join(tournaments)} — "
            f"{n_total_matches} matches, "
            f"best signal: {best_signal} "
            f"(Brier={aggregate_per_signal[best_signal]['brier']:.4f})"
        )
    else:
        print(f"Backtest: {', '.join(tournaments)} — {n_total_matches} matches")

    return aggregate_report
