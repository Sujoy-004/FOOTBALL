"""Monte Carlo simulation engine for UCL league phase.

Provides the top-level orchestration layer:

- :func:`simulate_league_phase` — one complete league phase iteration
- :func:`run_monte_carlo` — N-iteration Monte Carlo loop with aggregation
- :func:`run_monte_carlo_glicko` — N-iteration MC loop with Glicko-1 uncertainty
- :func:`aggregate_mc_results` — isolated aggregation function for testability
- :func:`_sample_glicko_elos` — sample team strengths from N(μ, σ²)

Consumes the match simulation and standings functions from
:mod:`competitions.ucl.src.groups` (Plan 02).
"""

from __future__ import annotations

import json
import os
import random

import math

from competitions.ucl.src.groups import (
    compute_swiss_standings,
    precompute_swiss_matchup_lambdas,
    simulate_swiss_matches,
)
from competitions.ucl.src.knockout import (
    build_r16_bracket,
    simulate_knockout_tree,
    simulate_playoff_round,
    track_knockout_stages,
)
from football_core.constants import EXPECTED_GOALS_BASE_RATE


# ── D-09 stage constants ──────────────────────────────────────────────────────

STAGE_ORDER = [
    "eliminated",
    "playoff",
    "r16",
    "qf",
    "sf",
    "final",
    "champion",
]
"""Ordered list of D-09 stages; index equals numeric value for post-aggregation."""

STAGE_TO_VALUE: dict[str, int] = {s: i for i, s in enumerate(STAGE_ORDER)}
"""Map stage name to its numeric value (0–6) for per-iteration stage tracking."""


# ═══════════════════════════════════════════════════════════════════════════════
# ── Bootstrap CI helpers (Phase 10, Plan 03)
# ═══════════════════════════════════════════════════════════════════════════════


def _binom_pmf(k: int, n: int, p: float) -> float:
    """Binomial probability mass function P(X = k) for X ~ Bin(n, p).

    Computed in log-space for numerical stability with large n.
    Returns 0.0 if the probability is too small to represent.
    """
    if k < 0 or k > n:
        return 0.0
    if p <= 0.0 or p >= 1.0:
        # Handle degenerate cases
        if p <= 0.0:
            return 1.0 if k == 0 else 0.0
        return 1.0 if k == n else 0.0

    # ln(P(X=k)) = ln(C(n,k)) + k*ln(p) + (n-k)*ln(1-p)
    ln_comb = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    log_prob = ln_comb + k * math.log(p) + (n - k) * math.log1p(-p)
    if log_prob < -700:  # exp(-700) ≈ 10^-304 — near float min
        return 0.0
    return math.exp(log_prob)


def _binom_cdf(k: int, n: int, p: float) -> float:
    """Binomial cumulative distribution function P(X <= k) for X ~ Bin(n, p).

    For small k (the common case in Clopper-Pearson for small counts),
    computes the CDF by directly summing PMF values.  This avoids the
    numerical issues of the regularized incomplete beta function for
    large n and small k.

    Parameters
    ----------
    k:
        Number of successes (0 <= k <= n).
    n:
        Number of trials (>= 0).
    p:
        Success probability (0 <= p <= 1).

    Returns
    -------
    float
        P(X <= k) in [0, 1].
    """
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0

    total = 0.0
    for i in range(k + 1):
        total += _binom_pmf(i, n, p)
    return min(total, 1.0)


def _binom_lower_bound(x: int, n: int, alpha: float, lo: float = 0.0,
                       hi: float = 1.0, tol: float = 1e-12) -> float:
    """Clopper-Pearson lower bound: solve P(X >= x) = alpha/2.

    Binary search on p for the lower confidence bound of a binomial
    proportion.  P(X >= x) is **increasing** in p (higher p means more
    successes likely).  When tail > p_target, current p is too high
    (tail too large) → search lower.  When tail < p_target, current p
    is too low → search higher.

    Returns 0.0 for x == 0.
    """
    if x <= 0:
        return 0.0
    if x >= n:
        return (alpha / 2.0) ** (1.0 / n)

    p_target = alpha / 2.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        # P(X >= x) = 1 - P(X <= x-1)
        tail = 1.0 - _binom_cdf(x - 1, n, mid)
        if tail > p_target:
            hi = mid  # tail too large — p is too high, search lower
        else:
            lo = mid  # tail too small — p is too low, search higher
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


def _binom_upper_bound(x: int, n: int, alpha: float, lo: float = 0.0,
                       hi: float = 1.0, tol: float = 1e-12) -> float:
    """Clopper-Pearson upper bound: solve P(X <= x) = alpha/2.

    Binary search on p for the upper confidence bound of a binomial
    proportion.  P(X <= x) is **decreasing** in p (higher p means more
    successes beyond x).  When tail < p_target, current p is too high
    (tail too small) → search lower.  When tail > p_target, current p
    is too low → search higher.

    Returns 1.0 for x >= n.
    """
    if x >= n:
        return 1.0
    if x <= 0:
        return 1.0 - (alpha / 2.0) ** (1.0 / n)

    p_target = alpha / 2.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        # P(X <= x)
        tail = _binom_cdf(x, n, mid)
        if tail < p_target:
            hi = mid  # tail too small — p is too high, search lower
        else:
            lo = mid  # tail too large — p is too low, search higher
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


def compute_bootstrap_ci(
    champion_counts: dict[str, int],
    n_iterations: int,
    n_resamples: int = 1000,
    alpha: float = 0.05,
) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap confidence intervals on champion probabilities.

    For each team with champion_count > 0, generates *n_resamples* bootstrap
    samples from Bernoulli(p_hat), computes champion probability per resample,
    and extracts the (alpha/2, 1-alpha/2) percentiles.

    Teams with champion_count = 0 receive CI = (0.0, 0.0).

    Parameters
    ----------
    champion_counts:
        ``{team_name: count_of_iterations_where_team_was_champion}``.
    n_iterations:
        Total number of Monte Carlo iterations.
    n_resamples:
        Number of bootstrap resamples (default 1000).
    alpha:
        Significance level (default 0.05 → 95% CI).

    Returns
    -------
    dict[str, tuple[float, float]]
        ``{team_name: (lower, upper)}`` with CI endpoints in [0, 1].
    """
    ci: dict[str, tuple[float, float]] = {}
    for team, count in champion_counts.items():
        if count <= 0:
            ci[team] = (0.0, 0.0)
            continue

        p_hat = count / n_iterations
        # Generate bootstrap resamples from Bernoulli(p_hat)
        resampled_probs: list[float] = []
        rng = random.Random(42)  # fixed seed for reproducibility
        for _ in range(n_resamples):
            # Draw n_iterations Bernoulli(p_hat) trials
            successes = sum(1 for _ in range(n_iterations) if rng.random() < p_hat)
            resampled_probs.append(successes / n_iterations)

        resampled_probs.sort()
        lower_idx = max(0, int(n_resamples * alpha / 2))
        upper_idx = min(n_resamples - 1, int(n_resamples * (1 - alpha / 2)))
        ci[team] = (resampled_probs[lower_idx], resampled_probs[upper_idx])

    return ci


def compute_bootstrap_ci_small_sample(
    champion_counts: dict[str, int],
    n_iterations: int,
    n_resamples: int = 10000,
    alpha: float = 0.05,
) -> dict[str, tuple[float, float]]:
    """Confidence intervals using Clopper-Pearson for teams with very small counts.

    For teams with champion_count < 5 (small-sample regime), uses the exact
    Clopper-Pearson binomial interval (conservative, avoids degenerate bootstrap
    samples).  For teams with count >= 5, delegates to
    :func:`compute_bootstrap_ci`.

    The Clopper-Pearson bounds are computed via binary search on binomial tail
    probabilities — no external dependencies required.

    Parameters
    ----------
    champion_counts:
        ``{team_name: count_of_iterations_where_team_was_champion}``.
    n_iterations:
        Total number of Monte Carlo iterations.
    n_resamples:
        Number of bootstrap resamples for the fallback path (default 10000).
    alpha:
        Significance level (default 0.05 → 95% CI).

    Returns
    -------
    dict[str, tuple[float, float]]
        ``{team_name: (lower, upper)}`` with CI endpoints in [0, 1].
        Teams with count < 5 get Clopper-Pearson intervals; others get
        bootstrap intervals.
    """
    ci: dict[str, tuple[float, float]] = {}
    for team, count in champion_counts.items():
        if count <= 0:
            ci[team] = (0.0, 0.0)
            continue

        if count < 5:
            # Clopper-Pearson exact binomial interval
            # Lower: solve P(X >= count) = alpha/2
            # Upper: solve P(X <= count) = alpha/2
            lower = _binom_lower_bound(count, n_iterations, alpha)
            upper = _binom_upper_bound(count, n_iterations, alpha)
            ci[team] = (lower, upper)
        else:
            # Fall back to bootstrap for non-small counts
            p_hat = count / n_iterations
            resampled_probs: list[float] = []
            rng = random.Random(42)
            for _ in range(n_resamples):
                successes = sum(1 for _ in range(n_iterations) if rng.random() < p_hat)
                resampled_probs.append(successes / n_iterations)
            resampled_probs.sort()
            lower_idx = max(0, int(n_resamples * alpha / 2))
            upper_idx = min(n_resamples - 1, int(n_resamples * (1 - alpha / 2)))
            ci[team] = (resampled_probs[lower_idx], resampled_probs[upper_idx])

    return ci


# ═══════════════════════════════════════════════════════════════════════════════
# ── Single-iteration orchestration
# ═══════════════════════════════════════════════════════════════════════════════


def simulate_league_phase(
    fixtures: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    uefa_coefficients: dict[str, float] | None = None,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> list[dict]:
    """Simulate one complete UCL league phase iteration.

    Parameters
    ----------
    fixtures:
        UCL fixture schedule dict from ``fixtures.json``.
    elo_ratings:
        ``{team_name: Elo}`` for all 36 teams.
    rng:
        Seeded ``random.Random`` instance for reproducibility.
    uefa_coefficients:
        ``{team_name: coefficient}`` for tiebreaker step 10.
    matchup_lambdas:
        Precomputed Poisson lambdas.  Computed once if ``None``.

    Returns
    -------
    list[dict]
        List of 36 standings dicts sorted by position (1-36), each with
        full tiebreaker stats and zone classification.
    """
    if matchup_lambdas is None:
        matchup_lambdas = precompute_swiss_matchup_lambdas(
            fixtures, elo_ratings, EXPECTED_GOALS_BASE_RATE,
        )

    matches = simulate_swiss_matches(
        fixtures,
        elo_ratings,
        rng,
        base_rate=EXPECTED_GOALS_BASE_RATE,
        matchup_lambdas=matchup_lambdas,
        played_matches=played_matches,
    )

    standings = compute_swiss_standings(
        matches,
        elo_ratings=elo_ratings,
        uefa_coefficients=uefa_coefficients,
    )

    return standings


# ═══════════════════════════════════════════════════════════════════════════════
# ── Aggregation (testable in isolation)
# ═══════════════════════════════════════════════════════════════════════════════


def aggregate_mc_results(
    positions: dict[str, list[int]],
    champions: dict[str, int],
    stat_collectors: dict[str, dict[str, list[int | float]]],
    n_iterations: int,
    stage_collectors: dict[str, list[int]] | None = None,
    compute_ci: bool = False,
) -> dict[str, dict]:
    """Aggregate per-iteration results into per-team D-06/D-07/D-09 output.

    Computes zone probabilities, champion probability, and averages
    for all 6 tiebreaker stats plus position.

    If *stage_collectors* is provided, also computes D-09 stage
    probabilities (stage_eliminated_prob, stage_playoff_prob, …).

    When *compute_ci* is True, confidence intervals on champion probabilities
    are computed via bootstrap (percentile method) with Clopper-Pearson
    exact intervals for small-sample teams (champion_count < 5).

    Parameters
    ----------
    positions:
        ``{team_name: [per-iteration position]}`` for all N iterations.
    champions:
        ``{team_name: count_of_iterations_where_team_was_champion}``.
    stat_collectors:
        ``{team_name: {stat: [per-iteration values]}}``.
    n_iterations:
        Total number of Monte Carlo iterations.
    stage_collectors:
        ``{team_name: [per-iteration stage values]}``, where values
        are ints from 0 (eliminated) to 6 (champion) per STAGE_ORDER.
        If None, stage probabilities are skipped (backward compat).
    compute_ci:
        If True, compute bootstrap confidence intervals on champion
        probabilities (default False — backward compatible).

    Returns
    -------
    dict[str, dict]
        Per-team dict with D-06/D-07 fields plus D-09 stage probability
        fields if *stage_collectors* was provided.  When *compute_ci* is
        True, each team entry also includes ``champion_ci_lower``,
        ``champion_ci_upper``, and ``champion_ci_width_pct`` fields.
    """
    teams: dict[str, dict] = {}
    for team in positions:
        entry = {
            "top_8_prob": sum(1 for p in positions[team] if p <= 8) / n_iterations,
            "playoff_prob": sum(1 for p in positions[team] if 9 <= p <= 24) / n_iterations,
            "eliminated_prob": sum(1 for p in positions[team] if p >= 25) / n_iterations,
            "champion_prob": champions[team] / n_iterations,
            "avg_position": sum(positions[team]) / n_iterations,
            "avg_pts": sum(stat_collectors[team]["pts"]) / n_iterations,
            "avg_gd": sum(stat_collectors[team]["gd"]) / n_iterations,
            "avg_gs": sum(stat_collectors[team]["gs"]) / n_iterations,
            "avg_away_gs": sum(stat_collectors[team]["away_gs"]) / n_iterations,
            "avg_wins": sum(stat_collectors[team]["wins"]) / n_iterations,
            "avg_away_wins": sum(stat_collectors[team]["away_wins"]) / n_iterations,
        }

        if stage_collectors and team in stage_collectors:
            stages = stage_collectors[team]
            # T-02-11: Verify stage values in range [0, 6], clamp invalid to 0
            clamped = [s if 0 <= s <= 6 else 0 for s in stages]
            entry["stage_eliminated_prob"] = sum(1 for s in clamped if s == 0) / n_iterations
            entry["stage_playoff_prob"] = sum(1 for s in clamped if s == 1) / n_iterations
            entry["stage_r16_prob"] = sum(1 for s in clamped if s == 2) / n_iterations
            entry["stage_qf_prob"] = sum(1 for s in clamped if s == 3) / n_iterations
            entry["stage_sf_prob"] = sum(1 for s in clamped if s == 4) / n_iterations
            entry["stage_final_prob"] = sum(1 for s in clamped if s == 5) / n_iterations
            # champion_prob already set above from champions dict

        teams[team] = entry

    # ── Bootstrap CIs on champion probabilities (Phase 10, Plan 03) ──
    if compute_ci:
        ci_main = compute_bootstrap_ci(champions, n_iterations)
        ci_small = compute_bootstrap_ci_small_sample(champions, n_iterations)
        for team in teams:
            # Prefer Clopper-Pearson for small-count teams, bootstrap for others
            if champions.get(team, 0) < 5:
                lower, upper = ci_small.get(team, (0.0, 0.0))
            else:
                lower, upper = ci_main.get(team, (0.0, 0.0))
            teams[team]["champion_ci_lower"] = round(lower, 6)
            teams[team]["champion_ci_upper"] = round(upper, 6)
            teams[team]["champion_ci_width_pct"] = round((upper - lower) * 100, 4)

    return teams


# ═══════════════════════════════════════════════════════════════════════════════
# ── Monte Carlo loop
# ═══════════════════════════════════════════════════════════════════════════════


def run_monte_carlo(
    fixtures: dict,
    elo_ratings: dict[str, float] | None = None,
    n_iterations: int = 10000,
    seed: int = 42,
    uefa_coefficients: dict[str, float] | None = None,
    team_aliases: dict[str, str] | None = None,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
    compute_ci: bool = False,
) -> dict:
    """Run Monte Carlo simulation of UCL league phase.

    Orchestrates the full simulation pipeline: optionally fetches Elo
    ratings from ClubElo, precomputes matchup lambdas once, runs
    *n_iterations* of the league phase (match simulation → standings),
    and aggregates per-team zone/champion probabilities and stat averages.

    When *compute_ci* is True, adds bootstrap confidence intervals on
    champion probabilities to the output.

    Parameters
    ----------
    fixtures:
        UCL fixture schedule dict (36 teams, 144 matches).
    elo_ratings:
        ``{team_name: Elo}``.  Fetched from ClubElo if ``None``.
    n_iterations:
        Number of Monte Carlo iterations (default 10 000).
    seed:
        Random seed for reproducibility.
    uefa_coefficients:
        ``{team_name: coefficient}`` for tiebreaker step 10.
    team_aliases:
        ``{team_name: clubelo_slug}`` mapping.  Loaded from
        ``data/team_aliases.json`` if not provided.
    compute_ci:
        If True, compute bootstrap CIs on champion probabilities
        (default False).

    Returns
    -------
    dict
        Output dict matching D-06/D-07 specification:
        ``{snapshot_date, n_iterations, seed,
          teams: {team_name: {top_8_prob, playoff_prob, eliminated_prob,
                              champion_prob, avg_position, avg_pts, avg_gd,
                              avg_gs, avg_away_gs, avg_wins, avg_away_wins}}}``
        When *compute_ci* is True, each team entry also includes
        ``champion_ci_lower``, ``champion_ci_upper``, ``champion_ci_width_pct``.
    """
    # ── 1. Fetch / resolve Elo ratings ──────────────────────────────────
    if elo_ratings is None:
        from competitions.ucl.src.elo_fetcher import fetch_team_elos

        team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
        elo_ratings = fetch_team_elos(team_names)

    # ── 2. Initialise seeded RNG ────────────────────────────────────────
    rng = random.Random(seed)

    # ── 3. Precompute matchup lambdas ONCE (Pitfall 4) ──────────────────
    matchup_lambdas = precompute_swiss_matchup_lambdas(
        fixtures, elo_ratings, EXPECTED_GOALS_BASE_RATE,
    )

    # ── 4. Initialise per-team collectors (post-aggregation pattern) ────
    team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
    positions: dict[str, list[int]] = {t: [] for t in team_names}
    champions: dict[str, int] = {t: 0 for t in team_names}
    stat_collectors: dict[str, dict[str, list[int | float]]] = {
        t: {"pts": [], "gd": [], "gs": [], "away_gs": [],
            "wins": [], "away_wins": []}
        for t in team_names
    }
    # D-09: stage tracking collector (value 0-6 per iteration)
    stage_collectors: dict[str, list[int]] = {
        t: [] for t in team_names
    }

    # Pre-build Elo dict lookup for knockout pipeline (T-02-13)
    elo_dict: dict[str, float] = dict(elo_ratings)

    # ── 4b. Load competition data files ONCE (perf: avoid O(n) disk I/O) ─
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
    )
    pairings_path = os.path.join(data_dir, "playoff_pairings.json")
    with open(pairings_path) as f:
        _pairings_data = json.load(f)
    bracket_path = os.path.join(data_dir, "bracket_rules.json")
    with open(bracket_path) as f:
        _bracket_data = json.load(f)

    # ── 5. Main iteration loop ──────────────────────────────────────────
    for _ in range(n_iterations):
        standings = simulate_league_phase(
            fixtures,
            elo_ratings,
            rng,
            uefa_coefficients=uefa_coefficients,
            matchup_lambdas=matchup_lambdas,
            played_matches=played_matches,
        )

        # ── Knockout pipeline (Phase 2) ─────────────────────────────────
        playoff_result = simulate_playoff_round(
            standings, elo_dict, rng,
            pairings_data=_pairings_data,
        )
        bracket = build_r16_bracket(
            standings, playoff_result,
            bracket_data=_bracket_data,
        )
        tree_result = simulate_knockout_tree(
            bracket, elo_dict, rng,
        )
        stages = track_knockout_stages(standings, tree_result)
        # ── end knockout pipeline ──────────────────────────────────────

        for entry in standings:
            team = entry["team"]
            pos = entry["position"]
            positions[team].append(pos)
            stat_collectors[team]["pts"].append(entry["pts"])
            stat_collectors[team]["gd"].append(entry["gd"])
            stat_collectors[team]["gs"].append(entry["gs"])
            stat_collectors[team]["away_gs"].append(entry["away_gs"])
            stat_collectors[team]["wins"].append(entry["wins"])
            stat_collectors[team]["away_wins"].append(entry["away_wins"])
            # D-09: champion determined by knockout tree, not league position 1
            if stages[team] == "champion":
                champions[team] += 1
            # D-09: track stage value for post-aggregation
            stage_collectors[team].append(STAGE_TO_VALUE[stages[team]])

    # ── 6. Aggregate and return ─────────────────────────────────────────
    from competitions.ucl.src.elo_fetcher import get_clubelo_snapshot_date

    return {
        "snapshot_date": get_clubelo_snapshot_date(),
        "n_iterations": n_iterations,
        "seed": seed,
        "teams": aggregate_mc_results(
            positions, champions, stat_collectors, n_iterations,
            stage_collectors=stage_collectors,
            compute_ci=compute_ci,
        ),
        "stage_order": STAGE_ORDER,  # D-09 metadata for consumers
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ── Glicko-1 uncertainty propagation  (Phase 10, Plan 02)
# ═══════════════════════════════════════════════════════════════════════════════


def _sample_glicko_elos(
    rating_system,
    rng: random.Random,
) -> dict[str, float]:
    """Sample team strengths from N(μ, σ²) per Glicko rating.

    Each iteration samples a point-estimate Elo from each team's
    posterior distribution N(μ, σ²).  Values are clamped to [0, 3000]
    to prevent degenerate outlier samples during early iterations when
    σ is large (e.g., DEFAULT_SIGMA=350).

    Parameters
    ----------
    rating_system:
        :class:`~football_core.glicko.RatingSystem` with per-team
        (μ, σ²) distributions.
    rng:
        Seeded ``random.Random`` for reproducibility.

    Returns
    -------
    dict[str, float]
        ``{team_name: sampled_mu}`` with all teams from the rating
        system, each clamped to [0, 3000].
    """
    elos: dict[str, float] = {}
    for team, rating in rating_system.teams():
        sampled = rng.gauss(rating.mu, rating.sigma)
        # Clamp to prevent degenerate outlier samples
        sampled = max(0.0, min(3000.0, sampled))
        elos[team] = sampled
    return elos


def run_monte_carlo_glicko(
    fixtures: dict,
    rating_system,
    n_iterations: int = 10000,
    seed: int = 42,
    uefa_coefficients: dict[str, float] | None = None,
    team_aliases: dict[str, str] | None = None,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
    compute_ci: bool = False,
) -> dict:
    """Monte Carlo simulation with Glicko-1 uncertainty sampling.

    Instead of a fixed point-estimate Elo rating per team (as in
    :func:`run_monte_carlo`), this function samples each team's
    strength from N(μ, σ²) at **every iteration**, propagating rating
    uncertainty into the champion probability distribution.

    The matchup lambdas (Poisson rates) are precomputed once using
    the mean ratings (μ), while per-iteration Elo samples are used
    for match simulation and the knockout pipeline.

    When *compute_ci* is True, adds bootstrap confidence intervals on
    champion probabilities to the output.

    Parameters
    ----------
    fixtures:
        UCL fixture schedule dict (36 teams, 144 matches).
    rating_system:
        :class:`~football_core.glicko.RatingSystem` with per-team
        (μ, σ²) distributions.  Must contain ratings for all 36 teams.
    n_iterations:
        Number of Monte Carlo iterations (default 10 000).
    seed:
        Random seed for reproducibility.
    uefa_coefficients:
        ``{team_name: coefficient}`` for tiebreaker step 10.
    team_aliases:
        Unused (reserved for future alias-based sampling).
    played_matches:
        ``{(team_a, team_b): (home_goals, away_goals)}`` dict for
        conditioning on real results.
    compute_ci:
        If True, compute bootstrap CIs on champion probabilities
        (default False).

    Returns
    -------
    dict
        Same structure as :func:`run_monte_carlo`: ``{snapshot_date,
        n_iterations, seed, teams, stage_order}``.  When *compute_ci*
        is True, each team entry also includes ``champion_ci_lower``,
        ``champion_ci_upper``, ``champion_ci_width_pct``.
    """
    # Use mean ratings for precomputation (per-iteration sampling is
    # done inside the loop)
    mean_elos: dict[str, float] = rating_system.to_elo_dict()

    # ── 1. Initialise seeded RNG ────────────────────────────────────────
    rng = random.Random(seed)

    # ── 2. Precompute matchup lambdas ONCE using mean ratings ───────────
    matchup_lambdas = precompute_swiss_matchup_lambdas(
        fixtures, mean_elos, EXPECTED_GOALS_BASE_RATE,
    )

    # ── 3. Initialise per-team collectors ───────────────────────────────
    team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
    positions: dict[str, list[int]] = {t: [] for t in team_names}
    champions: dict[str, int] = {t: 0 for t in team_names}
    stat_collectors: dict[str, dict[str, list[int | float]]] = {
        t: {"pts": [], "gd": [], "gs": [], "away_gs": [],
            "wins": [], "away_wins": []}
        for t in team_names
    }
    stage_collectors: dict[str, list[int]] = {
        t: [] for t in team_names
    }

    # ── 3b. Load competition data files ONCE ────────────────────────────
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
    )
    pairings_path = os.path.join(data_dir, "playoff_pairings.json")
    with open(pairings_path) as f:
        _pairings_data = json.load(f)
    bracket_path = os.path.join(data_dir, "bracket_rules.json")
    with open(bracket_path) as f:
        _bracket_data = json.load(f)

    # ── 4. Main iteration loop ──────────────────────────────────────────
    for _ in range(n_iterations):
        # Sample team strengths from N(μ, σ²) — each iteration gets a
        # different sample, propagating uncertainty into champion variance
        sampled_elos = _sample_glicko_elos(rating_system, rng)

        standings = simulate_league_phase(
            fixtures,
            sampled_elos,
            rng,
            uefa_coefficients=uefa_coefficients,
            matchup_lambdas=matchup_lambdas,
            played_matches=played_matches,
        )

        # ── Knockout pipeline ───────────────────────────────────────────
        playoff_result = simulate_playoff_round(
            standings, sampled_elos, rng,
            pairings_data=_pairings_data,
        )
        bracket = build_r16_bracket(
            standings, playoff_result,
            bracket_data=_bracket_data,
        )
        tree_result = simulate_knockout_tree(
            bracket, sampled_elos, rng,
        )
        stages = track_knockout_stages(standings, tree_result)

        # ── Collect results ─────────────────────────────────────────────
        for entry in standings:
            team = entry["team"]
            pos = entry["position"]
            positions[team].append(pos)
            stat_collectors[team]["pts"].append(entry["pts"])
            stat_collectors[team]["gd"].append(entry["gd"])
            stat_collectors[team]["gs"].append(entry["gs"])
            stat_collectors[team]["away_gs"].append(entry["away_gs"])
            stat_collectors[team]["wins"].append(entry["wins"])
            stat_collectors[team]["away_wins"].append(entry["away_wins"])
            if stages[team] == "champion":
                champions[team] += 1
            stage_collectors[team].append(STAGE_TO_VALUE[stages[team]])

    # ── 5. Aggregate and return ─────────────────────────────────────────
    from competitions.ucl.src.elo_fetcher import get_clubelo_snapshot_date

    return {
        "snapshot_date": get_clubelo_snapshot_date(),
        "n_iterations": n_iterations,
        "seed": seed,
        "teams": aggregate_mc_results(
            positions, champions, stat_collectors, n_iterations,
            stage_collectors=stage_collectors,
            compute_ci=compute_ci,
        ),
        "stage_order": STAGE_ORDER,
    }
