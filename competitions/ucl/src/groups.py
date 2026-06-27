"""Swiss match simulation and standings computation for UCL league phase.

Provides Poisson-based match simulation using football_core primitives and
the 10-step UCL tiebreaker chain (no H2H — not applicable to Swiss system).

Per UCLT-01, UCLT-02, UCLT-06:
- UCLT-01: Simulate 36-team league phase (144 matches across 8 matchdays)
- UCLT-02: Compute 36-team standings sorted by 10-step UCL tiebreaker chain
- UCLT-06: Reuse football_core Poisson primitives without modifying core
"""

from __future__ import annotations

import random
from collections import defaultdict

from football_core.constants import (
    DEFAULT_ELO,
    EXPECTED_GOALS_BASE_RATE,
    POISSON_TABLE_BITS,
)
from football_core.groups import (
    _build_poisson_table,
    _compute_conduct_score,
    expected_goals,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ── Pre-compute matchup lambdas
# ═══════════════════════════════════════════════════════════════════════════════


def precompute_swiss_matchup_lambdas(
    fixtures: dict,
    elo_ratings: dict[str, float],
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
) -> dict[str, tuple[float, float]]:
    """Pre-compute expected goals lambdas for every match in the fixture schedule.

    Iterates all matches and calls ``expected_goals()`` once per team
    per match.  Returns ``{match_id: (lambda_a, lambda_b)}``.

    Per Pitfall 4: all lambdas are precomputed ONCE before the iteration
    loop, not recalculated inside it.
    """
    lambdas: dict[str, tuple[float, float]] = {}
    schedule = fixtures.get("schedule", fixtures)
    for matchday in schedule["matchdays"]:
        for match in matchday:
            mid = match["match_id"]
            ta, tb = match["team_a"], match["team_b"]
            ea, eb = elo_ratings[ta], elo_ratings[tb]
            lambdas[mid] = (
                expected_goals(ea, eb, base_rate),
                expected_goals(eb, ea, base_rate),
            )
    return lambdas


# ═══════════════════════════════════════════════════════════════════════════════
# ── Match simulation
# ═══════════════════════════════════════════════════════════════════════════════


def simulate_swiss_matches(
    fixtures: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    fair_play: bool = True,
) -> dict[str, dict]:
    """Simulate all Swiss league phase matches using Poisson primitives.

    Follows the same sampling pattern as
    ``football_core.groups.simulate_group_matches()``.

    Parameters
    ----------
    fixtures:
        Fixture schedule dict matching the ``fixtures.json`` schema.
    elo_ratings:
        ``{team_name: elo}`` for all 36 teams.
    rng:
        Seeded ``random.Random`` instance for deterministic results.
    base_rate:
        Base scoring rate (default ``EXPECTED_GOALS_BASE_RATE``).
    matchup_lambdas:
        Pre-computed lambdas.  Computed automatically if ``None``.
    fair_play:
        Sample yellow/red cards when ``True``.

    Returns
    -------
    dict[str, dict]
        Flat dict keyed by ``match_id`` (NOT grouped by matchday).
        Does NOT mutate the input *fixtures*.
    """
    # Defensive copy to guarantee no mutation (WC anti-pattern rule)
    fixtures = {"schedule": {
        "teams": list(fixtures.get("schedule", fixtures).get("teams", [])),
        "matchdays": [
            list(md) for md in fixtures.get("schedule", fixtures).get("matchdays", [])
        ],
    }}

    schedule = fixtures["schedule"]

    if matchup_lambdas is None:
        matchup_lambdas = precompute_swiss_matchup_lambdas(
            fixtures, elo_ratings, base_rate=base_rate,
        )

    getrandbits = rng.getrandbits
    table_bits = POISSON_TABLE_BITS
    build_table = _build_poisson_table

    results: dict[str, dict] = {}
    for matchday in schedule["matchdays"]:
        for match in matchday:
            mid = match["match_id"]
            ta: str = match["team_a"]
            tb: str = match["team_b"]
            la, lb = matchup_lambdas[mid]

            score_a = (
                0 if la <= 0.0 else build_table(la)[getrandbits(table_bits)]
            )
            score_b = (
                0 if lb <= 0.0 else build_table(lb)[getrandbits(table_bits)]
            )

            if score_a > score_b:
                winner = ta
            elif score_b > score_a:
                winner = tb
            else:
                winner = None

            if fair_play:
                yc_table = build_table(2.0)
                rc_table = build_table(0.05)
                yc_a = yc_table[getrandbits(table_bits)]
                rc_a = rc_table[getrandbits(table_bits)]
                yc_b = yc_table[getrandbits(table_bits)]
                rc_b = rc_table[getrandbits(table_bits)]
            else:
                yc_a = rc_a = yc_b = rc_b = 0

            results[mid] = {
                "team_a": ta,
                "team_b": tb,
                "score_a": score_a,
                "score_b": score_b,
                "winner": winner,
                "yellow_cards_a": yc_a,
                "red_cards_a": rc_a,
                "yellow_cards_b": yc_b,
                "red_cards_b": rc_b,
            }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# ── Swiss standings with 10-step UCL tiebreaker
# ═══════════════════════════════════════════════════════════════════════════════


def compute_swiss_standings(
    matches: dict[str, dict],
    elo_ratings: dict[str, float] | None = None,
    uefa_coefficients: dict[str, float] | None = None,
) -> list[dict]:
    """Compute 36-team Swiss standings sorted by the 10-step UCL tiebreaker.

    The UCL tiebreaker chain (per UEFA Article 18) is:
      1. Points (primary — not a tiebreaker step)
      2. Goal difference          (step 1)
      3. Goals scored             (step 2)
      4. Away goals scored        (step 3)
      5. Wins                     (step 4)
      6. Away wins                (step 5)
      7. Opponent points          (step 6, pre-tiebreak raw aggregates)
      8. Opponent GD              (step 7)
      9. Opponent GS              (step 8)
     10. Conduct score            (step 9, lower is better)
     11. UEFA club coefficient    (step 10, higher is better)

    No H2H tiebreaker (not applicable to Swiss system).

    Parameters
    ----------
    matches:
        Flat ``{match_id: result}`` dict from :func:`simulate_swiss_matches`.
    elo_ratings:
        ``{team_name: elo}``.  Used for the ``elo`` field in output.
    uefa_coefficients:
        ``{team_name: coefficient}`` for step 10.  Missing teams get ``0.0``.

    Returns
    -------
    list[dict]
        Teams sorted by position (1-36), each dict containing all
        tiebreaker stats and zone classification.
    """
    if elo_ratings is None:
        elo_ratings = {}
    if uefa_coefficients is None:
        uefa_coefficients = {}

    # ── Pass 1: accumulate per-team statistics from match results ──────
    team_stats: dict[str, dict] = defaultdict(lambda: {
        "pts": 0,
        "gd": 0,
        "gs": 0,
        "away_gs": 0,
        "wins": 0,
        "away_wins": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "opponents": set[str](),
    })

    for result in matches.values():
        ta, tb = result["team_a"], result["team_b"]
        sa, sb = result["score_a"], result["score_b"]

        # --- Team A (home) ---
        team_stats[ta]["gd"] += sa - sb
        team_stats[ta]["gs"] += sa
        team_stats[ta]["opponents"].add(tb)
        team_stats[ta]["yellow_cards"] += result["yellow_cards_a"]
        team_stats[ta]["red_cards"] += result["red_cards_a"]

        # --- Team B (away) ---
        team_stats[tb]["gd"] += sb - sa
        team_stats[tb]["gs"] += sb
        team_stats[tb]["away_gs"] += sb
        team_stats[tb]["opponents"].add(ta)
        team_stats[tb]["yellow_cards"] += result["yellow_cards_b"]
        team_stats[tb]["red_cards"] += result["red_cards_b"]

        # --- Shared: points, wins, away_wins ---
        if sa > sb:
            team_stats[ta]["pts"] += 3
            team_stats[ta]["wins"] += 1
        elif sb > sa:
            team_stats[tb]["pts"] += 3
            team_stats[tb]["wins"] += 1
            team_stats[tb]["away_wins"] += 1
        else:
            team_stats[ta]["pts"] += 1
            team_stats[tb]["pts"] += 1

    # Compute conduct scores from raw yellow/red card counts
    for team, stats in team_stats.items():
        stats["conduct_score"] = _compute_conduct_score(
            stats["yellow_cards"], stats["red_cards"],
        )

    # ── Pass 2: opponent-based stats (pre-tiebreak raw aggregates) ────
    opponent_stats: dict[str, dict] = {}
    for team, stats in team_stats.items():
        opps = stats["opponents"]
        opponent_stats[team] = {
            "opp_pts": sum(team_stats[opp]["pts"] for opp in opps),
            "opp_gd": sum(team_stats[opp]["gd"] for opp in opps),
            "opp_gs": sum(team_stats[opp]["gs"] for opp in opps),
        }

    # ── Sort by 10-step tiebreaker chain ──────────────────────────────
    sorted_teams = sorted(
        team_stats.items(),
        key=lambda item: (
            -item[1]["pts"],                             # primary
            -item[1]["gd"],                              # step 1
            -item[1]["gs"],                              # step 2
            -item[1]["away_gs"],                         # step 3
            -item[1]["wins"],                            # step 4
            -item[1]["away_wins"],                       # step 5
            -opponent_stats[item[0]]["opp_pts"],         # step 6
            -opponent_stats[item[0]]["opp_gd"],          # step 7
            -opponent_stats[item[0]]["opp_gs"],          # step 8
            item[1]["conduct_score"],                    # step 9 (lower better)
            -uefa_coefficients.get(item[0], 0.0),        # step 10
        ),
    )

    # ── Build output with position and zone ───────────────────────────
    standings: list[dict] = []
    for i, (team, stats) in enumerate(sorted_teams):
        pos = i + 1
        if pos <= 8:
            zone = "top_8"
        elif pos <= 24:
            zone = "playoff"
        else:
            zone = "eliminated"

        standings.append({
            "team": team,
            "position": pos,
            "zone": zone,
            "pts": stats["pts"],
            "gd": stats["gd"],
            "gs": stats["gs"],
            "away_gs": stats["away_gs"],
            "wins": stats["wins"],
            "away_wins": stats["away_wins"],
            "opp_pts": opponent_stats[team]["opp_pts"],
            "opp_gd": opponent_stats[team]["opp_gd"],
            "opp_gs": opponent_stats[team]["opp_gs"],
            "conduct_score": stats["conduct_score"],
            "uefa_coefficient": uefa_coefficients.get(team, 0.0),
            "elo": elo_ratings.get(team, float(DEFAULT_ELO)),
        })

    return standings
