"""Offline weight calibration for UCL prediction signals.

Reads replay data (Phase 6 format), evaluates all registered signals,
computes per-signal multi-class log-loss, derives inverse-log-loss weights,
and writes them atomically to signal_weights.json.

Usage:
    from competitions.ucl.src.calibrate import run_calibration
    config = run_calibration(replay_data_path="path/to/replay.json")
"""

import datetime
import json
import logging
import os
import tempfile

from football_core.evaluation import log_loss
from football_core.blender import compute_log_loss_weights
from football_core.signal import PredictionContext, SignalRegistry

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 20  # minimum matches for a signal to be included


class _EmptyResultProvider:
    """Minimal stub that returns empty results — used when no MatchResultProvider is available.

    During calibration with replay data, match-level detail needed by RollingFormSignal
    isn't readily available in the provider format. This stub ensures RollingFormSignal
    still runs (returning uniform fallback ~0.5).
    """

    def get_team_results(
        self, team: str, before_date: str, limit: int = 10
    ) -> list[dict]:
        return []


def _build_signal_registry() -> SignalRegistry:
    """Build the standard UCL signal registry for calibration.

    Imports and registers all signals. Adding a new signal requires only
    an import + register line here — calibration and config auto-adapt.
    """
    from football_core.signals.refined_elo import RefinedEloSignal
    from football_core.signals.market_odds import MarketOddsSignal
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signals.squad_value import SquadValueSignal
    from football_core.signals.rest_days import RestDaysSignal

    registry = SignalRegistry()
    registry.register(RefinedEloSignal())
    registry.register(MarketOddsSignal())
    registry.register(RollingFormSignal(result_provider=_EmptyResultProvider()))
    registry.register(SquadValueSignal())
    registry.register(RestDaysSignal())
    return registry


def _get_default_output_path() -> str:
    """Return the default path for signal_weights.json relative to this file."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "signal_weights.json",
    )


def run_calibration(
    replay_data_path: str,
    threshold: int = DEFAULT_THRESHOLD,
    output_path: str | None = None,
) -> dict:
    """Run weight calibration using replay data.

    Evaluates all registered signals against each match in the replay data,
    computes per-signal multi-class log-loss (average of 3 binary log-losses:
    home, draw, away), derives inverse-log-loss weights, and writes the
    config atomically.

    Args:
        replay_data_path: Path to replay JSON file (Phase 6 format).
        threshold: Minimum matches for a signal to be included in blend.
        output_path: Path for output signal_weights.json. Defaults to
            competitions/ucl/config/signal_weights.json.

    Returns:
        The full config dict (weights, per_signal stats, metadata).

    Raises:
        FileNotFoundError: If replay_data_path doesn't exist.
        ValueError: If replay data is empty or has no matches.
    """
    # 1. Load replay data via ReplayMatchResultProvider
    from competitions.ucl.src.result_provider import ReplayMatchResultProvider

    provider = ReplayMatchResultProvider(replay_data_path)
    played_matches = provider.load()  # {(team_a, team_b): (home_score, away_score)}

    if not played_matches:
        raise ValueError(f"No matches loaded from replay data: {replay_data_path}")

    # 2. Build signal registry
    registry = _build_signal_registry()

    # 3. Evaluate each match, accumulate per-signal probabilities vs actuals
    # signal_results: {sig_name: {"home_probs": [...], "draw_probs": [...],
    #                              "away_probs": [...], "actual_home": [...], ...}}
    signal_results: dict[str, dict[str, list]] = {}

    for (team_a, team_b), (home_score, away_score) in played_matches.items():
        match = {
            "team_a": team_a,
            "team_b": team_b,
            "match_id": f"{team_a}-{team_b}",
        }

        # Build minimal context (Elo is essential for signals to work)
        context = PredictionContext(
            fixtures=[],
            elo_ratings={},  # Will use default 1500 if specific ratings unavailable
            played_results=[],
        )

        outputs = registry.evaluate(match, context)

        # Determine actual one-hot outcome vector
        if home_score > away_score:
            actual_home, actual_draw, actual_away = 1.0, 0.0, 0.0
        elif away_score > home_score:
            actual_home, actual_draw, actual_away = 0.0, 0.0, 1.0
        else:
            actual_home, actual_draw, actual_away = 0.0, 1.0, 0.0

        for sig_name, output in outputs.items():
            if sig_name not in signal_results:
                signal_results[sig_name] = {
                    "home_probs": [],
                    "draw_probs": [],
                    "away_probs": [],
                    "actual_home": [],
                    "actual_draw": [],
                    "actual_away": [],
                }
            sr = signal_results[sig_name]
            sr["home_probs"].append(output.home_prob)
            sr["draw_probs"].append(output.draw_prob)
            sr["away_probs"].append(output.away_prob)
            sr["actual_home"].append(actual_home)
            sr["actual_draw"].append(actual_draw)
            sr["actual_away"].append(actual_away)

    # 4. Compute per-signal multi-class log-loss per Pitfall 4
    # Average of 3 binary log-losses (home, draw, away)
    log_losses: dict[str, float] = {}
    n_matches: dict[str, int] = {}

    for sig_name, sr in signal_results.items():
        n = len(sr["home_probs"])
        n_matches[sig_name] = n

        if n < threshold:
            logger.info(
                "Signal '%s' excluded — only %d matches (threshold=%d)",
                sig_name, n, threshold,
            )
            continue

        # Per-signal multi-class log-loss = average of 3 binary log-losses
        ll_home = sum(
            log_loss(p, a) for p, a in zip(sr["home_probs"], sr["actual_home"])
        ) / n
        ll_draw = sum(
            log_loss(p, a) for p, a in zip(sr["draw_probs"], sr["actual_draw"])
        ) / n
        ll_away = sum(
            log_loss(p, a) for p, a in zip(sr["away_probs"], sr["actual_away"])
        ) / n
        log_losses[sig_name] = (ll_home + ll_draw + ll_away) / 3

    # 5. Compute inverse-log-loss weights per D-01
    weights = compute_log_loss_weights(log_losses)

    # 6. Assemble config dict
    config = {
        "version": 1,
        "calibrated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "n_matches": max(n_matches.values()) if n_matches else 0,
        "threshold": threshold,
        "weights": weights,
        "per_signal": {
            sig: {
                "log_loss": round(log_losses.get(sig, 0), 4),
                "n_matches": n_matches.get(sig, 0),
                "excluded": sig not in weights,
            }
            for sig in sorted(signal_results.keys())
        },
    }

    # 7. Atomic write per Pitfall 2
    output = output_path or _get_default_output_path()
    os.makedirs(os.path.dirname(output), exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".tmp", encoding="utf-8",
    ) as f:
        json.dump(config, f, indent=2)
        tmp_path = f.name

    os.replace(tmp_path, output)
    logger.info("Calibration weights written to %s", output)

    return config
