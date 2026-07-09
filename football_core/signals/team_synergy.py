"""Team synergy signal — attack/defence balance from played results.

Measures how well each team's attack and defence work together by
analysing their goals-scored vs goals-conceded ratio across played
matches. A team with high synergy scores more than they concede.

The signal uses context.played_results (populated by orchestrator from
real results) rather than requiring its own data source.

Formula:
  For each team, from played_results:
    avg_scored   = sum(home/away goals scored) / n_matches
    avg_conceded = sum(home/away goals conceded) / n_matches
    synergy      = avg_scored / (avg_scored + avg_conceded)  ∈ [0, 1]

  home_prob = sigmoid(k * (synergy_a - synergy_b) * 3)
"""

import logging
from collections import defaultdict

from football_core.math_utils import sigmoid
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)

DEFAULT_K: float = 2.0


class TeamSynergySignal(Signal):
    """Attack/defence synergy signal using goals ratio from played results.

    Requires context.played_results with team_a, team_b, home_score, away_score.
    Falls back to uniform when played_results is empty.
    """

    name: str = "team_synergy"

    def __init__(self, k: float = DEFAULT_K) -> None:
        self._k = k

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        results = context.played_results or []
        if not results:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        synergies = _compute_team_synergies(results)

        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")

        syn_a = synergies.get(team_a, 0.5)
        syn_b = synergies.get(team_b, 0.5)

        home_prob = sigmoid(self._k * (syn_a - syn_b) * 3)
        draw_prob = 0.25
        away_prob = max(0.0, 1.0 - home_prob - draw_prob)
        home_prob = 1.0 - draw_prob - away_prob

        return SignalOutput(home_prob, draw_prob, away_prob)


def _compute_team_synergies(
    results: list[dict],
) -> dict[str, float]:
    """Compute synergy (goals-scored ratio) per team from played results."""
    scored: dict[str, float] = defaultdict(float)
    conceded: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)

    for r in results:
        ta = r.get("team_a", "")
        tb = r.get("team_b", "")
        hs = r.get("home_score", 0) or 0
        aws = r.get("away_score", 0) or 0

        scored[ta] += hs
        conceded[ta] += aws
        scored[tb] += aws
        conceded[tb] += hs
        counts[ta] += 1
        counts[tb] += 1

    synergies: dict[str, float] = {}
    for team in scored:
        n = counts.get(team, 0)
        if n == 0:
            synergies[team] = 0.5
            continue
        avg_s = scored[team] / n
        avg_c = conceded[team] / n
        denom = avg_s + avg_c
        synergies[team] = avg_s / denom if denom > 0 else 0.5

    return synergies
