"""Leak-free out-of-sample evaluation of the historical World Cup backfill.

Reads the committed dataset under ``competitions/worldcup/data/historical``
and the production signal weights from ``config/signal_weights.json``
(READ-ONLY — no model code, weights, or UI are touched), and evaluates:

  * cross-season and pooled metrics for the ensemble and baselines
    (uniform, empirical-frequency, Elo-only, market-odds-only) on
    identically-labelled match populations (apples-to-apples),
  * leave-one-signal-out ablations,
  * inverse-log-loss weights learned on strictly-prior training windows
    per season, plus their stability across windows,
  * calibration (confidence-based ECE) per config.

Every prediction uses ``competitions.worldcup.src.historical.build_context_for_match``
(prior-only) with the season's own pre-match Elo snapshot — no future data
leaks. That protocol is implemented once in ``football_core.historical_backfill``;
this module is the World Cup configuration of it (seasons, dataset path,
production weights) and keeps the original public helper names/signatures
for the sibling investigation modules.

WC-specific divergences from the LaLiga/UCL driver:

  * Weight-key mapping: ``config/signal_weights.json`` carries ``elo`` and
    ``squad_value`` keys that the harness signal order does not have. The
    driver maps ``elo`` -> ``refined_elo`` and drops ``squad_value`` before
    calling ``run_evaluation`` (the harness would silently drop them
    otherwise).
  * Confidence ECE (D-10): the WC calibration block uses the confidence
    ``multi_class_ece`` (not classwise ECE) because the ~100-match sample
    cannot satisfy the classwise ``observations/bin >= 20`` rule.
  * Knockout H/D/A: the knockout target is the advancing winner (0/2, never
    1) and the forecast is renormalized two-way; the Elo update coding
    ``W = 0.75/0.25`` is a rating adjustment, not a 1X2 target.
  * National-team Elo: no date-indexed historical feed exists;
    ``refined_elo`` is ``insufficient_data:no_elo_ratings`` and the Elo-only
    baseline is reported unavailable (never fabricated).

Output: ``competitions/worldcup/data/historical/evaluation/eval_results.json``
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from football_core.evaluation import multi_class_ece
from football_core.evaluation_report import render_evaluation_markdown
from football_core.historical_backfill import (
    Harness,
    run_evaluation,
)
from football_core.state import atomic_write_text

from competitions.worldcup.historical_backfill.contract import SEASONS as _SEASON_LABELS
from competitions.worldcup.src.historical import (
    ReplayResultProvider,
    build_context_for_match,
    frequency_baseline,
    load_replay_matches,
    order_matches,
    outcome_index,
)

HISTORICAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "historical"
)
OUT_DIR = os.path.join(HISTORICAL_DIR, "evaluation")
OUT_PATH = os.path.join(OUT_DIR, "eval_results.json")
REPORT_PATH = os.path.join(OUT_DIR, "EVALUATION.md")

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
)

# D-01 window, derived from the contract so the evaluated seasons cannot drift
# from the committed corpus the build produced.
SEASONS = list(_SEASON_LABELS)
SIGNAL_ORDER = ["market_odds", "refined_elo", "rolling_form", "rest_days"]

DATASET = "competitions/worldcup/data/historical (2002-2026)"

# Competition-specific declarations rendered once, before the first number, by
# the shared renderer's "## Declarations" block.
_EXTRA_DECLARATIONS = [
    "Weight-key mapping: `competitions/worldcup/config/signal_weights.json` "
    "carries `elo` and `squad_value` keys that the harness signal order does "
    "not have; `elo` is mapped to `refined_elo` and `squad_value` is dropped "
    "before calling `run_evaluation` (the harness would silently drop them "
    "otherwise).",
    "Confidence ECE (D-10): the WC calibration block uses the confidence "
    "`multi_class_ece` (not classwise ECE) because the ~100-match sample "
    "cannot satisfy the classwise `observations/bin >= 20` rule.",
    "Knockout H/D/A + Elo reconciliation: the knockout target is the advancing "
    "winner (0/2, never 1) and the forecast is renormalized two-way "
    "(`p_home/(p_home+p_away)`); the Elo update coding `W = 0.75/0.25` "
    "(`football_core/elo.py:37`) is a rating adjustment, not a 1X2 target.",
    "National-team Elo feed: no date-indexed historical feed exists; "
    "`refined_elo` is `insufficient_data:no_elo_ratings` and the Elo-only "
    "baseline is reported unavailable (never fabricated).",
]

_HARNESS = Harness(
    build_context=build_context_for_match,
    outcome_index=outcome_index,
    order_matches=order_matches,
    frequency_baseline=frequency_baseline,
    replay_provider=ReplayResultProvider,
    load_replay_matches=load_replay_matches,
)


def wc_weights() -> dict[str, float]:
    """Read WC production weights and map them to harness signal keys.

    The WC config carries `elo` (the harness expects `refined_elo`) and
    `squad_value` (not in the harness signal order). Both are translated
    explicitly: `elo` -> `refined_elo`, `squad_value` dropped. An unexpected
    key raises ValueError rather than passing through to be silently dropped
    by the harness's `renormalize`.

    Returns:
        The mapped weights dict with keys in SIGNAL_ORDER.

    Raises:
        ValueError: If the config contains an unexpected weight key.
    """
    config_path = os.path.join(CONFIG_DIR, "signal_weights.json")
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    raw = data["weights"]

    # Validate: no unexpected keys
    allowed = {"elo", "market_odds", "rolling_form", "squad_value", "rest_days"}
    unexpected = set(raw.keys()) - allowed
    if unexpected:
        raise ValueError(
            f"Unexpected weight key(s) in WC config: {sorted(unexpected)}. "
            f"Allowed: {sorted(allowed)}"
        )

    # Map: elo -> refined_elo, drop squad_value
    mapped: dict[str, float] = {}
    for key, value in raw.items():
        if key == "squad_value":
            continue  # dropped: no harness signal
        if key == "elo":
            mapped["refined_elo"] = value
        else:
            mapped[key] = value
    return mapped


def _has_corpus(historical_dir: str) -> bool:
    """True only when at least one tournament dataset directory with a
    ``matches.json`` exists under ``historical_dir``.

    This gates the honest-failure path: if no real corpus is present, the
    driver emits a ``deferred/provider-empty`` artifact rather than
    fabricating results.
    """
    if not os.path.isdir(historical_dir):
        return False
    for season in SEASONS:
        matches_path = os.path.join(historical_dir, season, "matches.json")
        if os.path.isfile(matches_path):
            return True
    return False


def _write_deferred(out_path: str, report_path: str, reason: str) -> dict:
    """Write the honest-failure artifact and return the status dict."""
    status = {
        "status": "deferred/provider-empty",
        "reason": reason,
        "excluded": list(SEASONS),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    atomic_write_text(Path(out_path), json.dumps(status, indent=2))

    md_lines = [
        "# World Cup Out-of-Sample Model Evaluation",
        "",
        "**Status:** deferred/provider-empty",
        "",
        f"**Reason:** {reason}",
        "",
        f"**Excluded:** {', '.join(status['excluded'])}",
        "",
        f"**Generated:** {status['generated_at']}",
        "",
        "The World Cup block is deferred/provider-empty. No real World Cup "
        "corpus is present under `competitions/worldcup/data/historical/`. "
        "The gate is evaluated on LaLiga and UCL only.",
        "",
    ]
    atomic_write_text(Path(report_path), "\n".join(md_lines))
    return status


def run(
    historical_dir: str = HISTORICAL_DIR,
    out_path: str = OUT_PATH,
    report_path: str = REPORT_PATH,
    seasons: list[str] | None = None,
) -> dict:
    """Run the WC evaluation, or emit an honest-failure artifact.

    When no real corpus exists under ``historical_dir``, writes a
    ``deferred/provider-empty`` status to ``out_path`` and a matching
    ``EVALUATION.md`` to ``report_path``. Fabricates nothing.

    When the corpus exists, runs the shared harness, transforms the
    holdout block for the WC-specific calibration variant (D-10), and
    renders the report through the shared renderer.

    Args:
        historical_dir: Path to the ``data/historical`` directory.
        out_path: Path for the JSON results artifact.
        report_path: Path for the markdown report.
        seasons: Optional override for the season list (defaults to
            ``contract.SEASONS``).

    Returns:
        The results dict (or the status dict on the honest-failure path).
    """
    # ── Honest failure (D-04) ──
    if not _has_corpus(historical_dir):
        reason = (
            "no real World Cup corpus found under "
            f"{historical_dir} — the driver consumes ONLY the committed "
            "data/historical/ corpus, never data/played.json"
        )
        return _write_deferred(out_path, report_path, reason)

    # ── Normal path ──
    results = run_evaluation(
        out_path,
        historical_dir,
        seasons or SEASONS,
        SIGNAL_ORDER,
        wc_weights(),
        DATASET,
        _HARNESS,
    )

    # ── WC-specific holdout transformations ──
    holdout = results.get("holdout", {})

    # Drop classwise_ece (D-10: WC uses confidence ECE, not classwise)
    holdout.pop("classwise_ece", None)

    # Set the confidence ECE calibration block
    ensemble_metrics = holdout.get("models", {}).get("ensemble", {})
    ece_val = ensemble_metrics.get("ece")
    if ece_val is not None:
        holdout["calibration"] = {
            "kind": "confidence (multi_class_ece)",
            "ece": round(ece_val, 6),
        }
    # If the test population is empty, omit the block rather than emitting 0.0

    # Drop per_class from calibration_slope_intercept (keep only overall)
    cal_si = holdout.get("calibration_slope_intercept", {})
    if cal_si:
        holdout["calibration_slope_intercept"] = {
            "overall": cal_si.get("overall")
        }

    results["holdout"] = holdout

    # ── Render and write the report ──
    md = render_evaluation_markdown(
        results,
        competition="World Cup",
        extra_declarations=_EXTRA_DECLARATIONS,
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    atomic_write_text(Path(report_path), md)

    return results


def main() -> None:
    run()


if __name__ == "__main__":
    main()
