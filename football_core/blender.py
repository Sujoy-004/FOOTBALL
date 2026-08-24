"""Canonical prediction ensemble — competition-agnostic.

One blending mechanism only:

    Signal predictions
        -> inverse-log-loss weight fitting (compute_log_loss_weights)
        -> normalized signal weights
        -> EnsembleEngine weighted blend
        -> match probabilities

plus post-hoc explainability via compute_signal_contributions.

Uses ONLY Python stdlib (math module). No numpy, no sklearn.
"""

import json

from football_core.signal import BlendedPrediction, PredictionContext, Signal, SignalRegistry, SignalOutput

_WEIGHT_FLOOR = 0.05


def compute_log_loss_weights(log_losses: dict[str, float]) -> dict[str, float]:
    """Compute inverse-log-loss normalized weights for ensemble blending.

    w_i = (1 / max(ll_i, floor)) / sum_j (1 / max(ll_j, floor))

    Deterministic for identical input. Weights are non-negative and sum
    to ~1.0 (rounding to 6 dp). The floor prevents a near-zero log-loss
    on a tiny sample from dominating the ensemble.

    Args:
        log_losses: {signal_name: multiclass log-loss value} from fitting
            on labeled historical outcomes.

    Returns:
        {signal_name: normalized_weight}
    """
    if not log_losses:
        return {}

    raw_weights = {}
    for signal, ll in log_losses.items():
        raw_weights[signal] = 1.0 / max(ll, _WEIGHT_FLOOR)

    total = sum(raw_weights.values())
    return {s: round(w / total, 6) for s, w in raw_weights.items()}


class EnsembleEngine:
    """Orchestrates signal evaluation and blends results into a single prediction.

    Wraps SignalRegistry for signal evaluation, applies weighted averaging
    per outcome (home/draw/away independently), re-normalizes to 1.0.

    Weight resolution precedence:
        1. explicit ``weights`` dict
        2. ``weights_path`` JSON file ({"weights": {...}})
        3. uniform fallback over registered signals
    """

    def __init__(
        self,
        signals: list[Signal],
        weights: dict[str, float] | None = None,
        weights_path: str | None = None,
    ):
        """Construct engine with signals and weights.

        Args:
            signals: List of Signal instances to register and evaluate.
            weights: Optional direct weights dict (takes precedence over file).
            weights_path: Optional path to JSON weight config file.
                If both weights and weights_path are None, uniform weights are used.
        """
        self._registry = SignalRegistry()
        for sig in signals:
            self._registry.register(sig)

        # Resolve weights: direct dict > JSON file > uniform fallback
        if weights is not None:
            self._weights = {k: v for k, v in weights.items() if v > 0}
        elif weights_path is not None:
            with open(weights_path) as f:
                data = json.load(f)
            raw = data.get("weights", {})
            self._weights = {k: v for k, v in raw.items() if v > 0}
        else:
            # Uniform fallback to all registered signals
            names = self._registry.list()
            uniform = 1.0 / len(names) if names else 0.0
            self._weights = {n: uniform for n in names}

    def evaluate(self, match: dict, context: PredictionContext) -> BlendedPrediction:
        """Evaluate all registered signals and blend into a single prediction.

        Args:
            match: Match dict with team_a, team_b, match_id, etc.
            context: PredictionContext with elo_ratings, fixtures, etc.

        Returns:
            BlendedPrediction with blended probabilities, signal breakdown, and weights.
        """
        signal_results = self._registry.evaluate(match, context)
        return self._blend(signal_results)

    def _blend(self, results: dict[str, SignalOutput]) -> BlendedPrediction:
        """Blend per-signal SignalOutputs into a single BlendedPrediction.

        Blends home_prob, draw_prob, away_prob independently, then
        re-normalizes to handle floating-point drift.
        """
        # Filter to signals that have positive weights and produced output
        active = {name: out for name, out in results.items()
                  if self._weights.get(name, 0) > 0}

        if not active:
            return BlendedPrediction(1 / 3, 1 / 3, 1 / 3, {}, {})

        # Re-normalize weights for available signals
        avail_weights = {n: self._weights[n] for n in active}
        total_w = sum(avail_weights.values())  # guaranteed > 0 since active is non-empty
        norm_weights = {n: w / total_w for n, w in avail_weights.items()}

        # Blend each outcome independently
        blended_h = sum(norm_weights[n] * r.home_prob for n, r in active.items())
        blended_d = sum(norm_weights[n] * r.draw_prob for n, r in active.items())
        blended_a = sum(norm_weights[n] * r.away_prob for n, r in active.items())

        # Re-normalize to handle floating-point drift
        total = blended_h + blended_d + blended_a
        if total > 0:
            blended_h /= total
            blended_d /= total
            blended_a /= total

        # Build breakdown dict: {signal_name: {home, draw, away, weight}}
        breakdown = {}
        for name, result in active.items():
            breakdown[name] = {
                "home": round(result.home_prob, 4),
                "draw": round(result.draw_prob, 4),
                "away": round(result.away_prob, 4),
                "weight": round(norm_weights[name], 4),
            }

        return BlendedPrediction(
            home_prob=round(blended_h, 6),
            draw_prob=round(blended_d, 6),
            away_prob=round(blended_a, 6),
            signal_breakdown=breakdown,
            weights_applied=dict(norm_weights),
        )

    @property
    def weights(self) -> dict[str, float]:
        """Return current weights dict (read-only)."""
        return dict(self._weights)


def compute_signal_contributions(
    blended_predictions: list[BlendedPrediction],
    target_team: str,
    weights: dict[str, float],
    match_fixtures: list[dict] | None = None,
) -> dict[str, float]:
    """Compute per-signal contribution to champion probability for a target team.

    Uses post-hoc attribution approximation: each signal is attributed a share of
    the champion probability based on its ensemble weight and how much its
    prediction deviates from uniform (1/3) for the target team's match outcomes.

    This is NOT exact decomposition — champion probability emerges from a non-linear
    MC pipeline (simulation -> standings -> tiebreakers -> bracket) and cannot be
    exactly decomposed into additive signal contributions. The attribution provides
    directional intuition (which signals push the prediction up/down), not causal
    decomposition.

    Args:
        blended_predictions: List of BlendedPrediction for all tournament matches.
        target_team: The team name to compute contributions for.
        weights: {signal_name: normalized_weight} from EnsembleEngine.
        match_fixtures: Optional list of match dicts with team_a/team_b keys.
            Must be same length as blended_predictions. When provided, contributions
            are computed only for matches involving target_team, using the correct
            home/away direction. When omitted, contributions are computed across
            all matches using average of home/away probabilities.

    Returns:
        {signal_name: raw_contribution} dict. Values are un-normalized contribution
        scores that the display layer scales to match champion probability.
        Returns empty dict if no relevant data.
    """
    if not blended_predictions or not weights or target_team is None:
        return {}

    # Initialize contribution accumulators for all signals in weights
    contributions: dict[str, float] = {sig: 0.0 for sig in weights}
    match_count: dict[str, int] = {sig: 0 for sig in weights}
    uniform_baseline = 1 / 3

    if match_fixtures is not None and len(match_fixtures) == len(blended_predictions):
        # ── Team-filtered mode: compute contributions only for target_team's matches ──
        for bp, match in zip(blended_predictions, match_fixtures):
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")
            if target_team not in (team_a, team_b):
                continue

            outcome_key = "home" if target_team == team_a else "away"
            for signal, weight in weights.items():
                if signal in bp.signal_breakdown:
                    sig_prob = bp.signal_breakdown[signal].get(outcome_key, uniform_baseline)
                    contributions[signal] += weight * (sig_prob - uniform_baseline)
                    match_count[signal] += 1
    else:
        # ── Global mode: compute across all matches (fallback without match info) ──
        for bp in blended_predictions:
            for signal, weight in weights.items():
                if signal in bp.signal_breakdown:
                    sig_home = bp.signal_breakdown[signal].get("home", uniform_baseline)
                    sig_away = bp.signal_breakdown[signal].get("away", uniform_baseline)
                    # Use the larger of home/away deviation as a directional proxy
                    best_outcome = max(sig_home, sig_away)
                    contributions[signal] += weight * (best_outcome - uniform_baseline)
                    match_count[signal] += 1

    # Remove signals with zero contribution/no matches
    result = {sig: round(val, 4) for sig, val in contributions.items()
              if match_count.get(sig, 0) > 0}

    return result
