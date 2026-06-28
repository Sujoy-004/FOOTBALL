"""Two-legged knockout tie simulation for UCL.

Provides the core two-legged aggregate scoring primitive with
extra time (reduced Poisson lambda) and penalty shootouts, plus
the playoff round orchestrator (positions 9-24).

Per D-01: ET simulated locally — BSD API does not expose ET scores.
Per D-02: Penalties simulated locally — calibration in config constant.
Per D-03: ET home advantage belongs to second-leg home team.
Per D-04: Playoff pairings from dedicated data file.
Per D-05: Seeded teams (9-16) get second-leg home advantage.
Per D-11: No football_core modifications.
"""

from __future__ import annotations

import glob as _glob
import json
import os
import random

from football_core.constants import (
    EXPECTED_GOALS_BASE_RATE,
    HOME_ADVANTAGE_MULTIPLIER,
    POISSON_TABLE_BITS,
)
from football_core.groups import _build_poisson_table, expected_goals

# ── Configurable constants ─────────────────────────────────────
# These are module-level defaults. Move to a shared
# config/constants layer (e.g. competitions/ucl/src/config.py)
# if they stabilise across multiple modules.  Exact values are
# implementation decisions, not architectural contracts.
# For now, inline defaults keep the API self-contained.

PENALTY_SHOTS_PER_SIDE: int = 5

# Default expected goals base rate for single-match finals
_DEFAULT_BRACKET_FILENAME = "bracket_rules.json"


def _simulate_penalty_shootout(
    rng: random.Random,
    conversion_rate: float = 0.76,
) -> tuple[int, int]:
    """Simulate a penalty shootout with sudden death if level after 5 shots each.

    Each shot is a configurable Bernoulli trial (default ~76%
    reflects historical UCL conversion rate).

    Parameters
    ----------
    rng:
        Seeded random.Random for deterministic results.
    conversion_rate:
        Probability each penalty is converted.

    Returns
    -------
    tuple[int, int]
        (goals_a, goals_b) — the final penalty scores.
    """
    shots = PENALTY_SHOTS_PER_SIDE
    a_scored = b_scored = 0
    for i in range(shots):
        if rng.random() < conversion_rate:
            a_scored += 1
        if rng.random() < conversion_rate:
            b_scored += 1
        # Early termination: one team cannot be caught
        remaining = shots - (i + 1)
        if a_scored > b_scored + remaining or b_scored > a_scored + remaining:
            break

    # Sudden death if still level
    while a_scored == b_scored:
        if rng.random() < conversion_rate:
            a_scored += 1
        if rng.random() < conversion_rate:
            b_scored += 1

    return a_scored, b_scored


def simulate_two_legged_tie(
    team_a: str,
    team_b: str,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """Simulate a two-legged knockout tie with aggregate scoring.

    Simulates both legs using Poisson match simulation from
    football_core, then resolves by aggregate score.  If aggregate
    is level, extra time is played with configurable reduced Poisson
    lambda (per D-01).  If still level, a penalty shootout decides
    with a configurable calibrated conversion model (per D-02).

    Per D-03: extra time home advantage goes to the second-leg home
    team (team_b in leg 2, since team_a hosts leg 1).

    Per the 2025+ format: no away goals rule — aggregate score is
    the only tiebreaker.

    Parameters
    ----------
    team_a:
        Home team for leg 1 (away team for leg 2).
    team_b:
        Away team for leg 1 (home team for leg 2).
    elo_ratings:
        ``{team_name: Elo}`` dict.
    rng:
        Seeded random.Random for deterministic results.
    base_rate:
        Normal time expected goals base rate.
    et_lambda_factor:
        Configurable factor: ET lambda = normal_lambda * factor.
        Reflects shorter ET duration and fatigue.  Move to config
        layer if value stabilises.
    penalty_conversion_rate:
        Configurable probability each penalty shot is converted.
        Historical UCL baseline ~76%.  Move to config layer if
        value stabilises.

    Returns
    -------
    dict
        ``{winner, loser, aggregate_a, aggregate_b,
          agg_a_full, agg_b_full,
          leg1: {team_a, team_b, score_a, score_b},
          leg2: {team_a, team_b, score_a, score_b},
          et_played: bool, et_a, et_b,
          penalties_played: bool, penalty_a, penalty_b}``
    """
    # ── 1. Fetch Elo ratings ──────────────────────────────────────────────
    ea = elo_ratings[team_a]
    eb = elo_ratings[team_b]

    # ── 2. Leg 1 (team_a home, team_b away) ──────────────────────────────
    lam_a1 = expected_goals(ea, eb, base_rate)
    lam_b1 = expected_goals(eb, ea, base_rate)
    score_a1 = _build_poisson_table(lam_a1)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a1 > 0 else 0
    score_b1 = _build_poisson_table(lam_b1)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b1 > 0 else 0

    # ── 3. Leg 2 (team_b home, team_a away) ──────────────────────────────
    lam_b2 = expected_goals(eb, ea, base_rate)    # home advantage for team_b
    lam_a2 = expected_goals(ea, eb, base_rate)    # away for team_a
    score_b2 = _build_poisson_table(lam_b2)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b2 > 0 else 0
    score_a2 = _build_poisson_table(lam_a2)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a2 > 0 else 0

    # ── 4. Compute aggregate ─────────────────────────────────────────────
    agg_a = score_a1 + score_a2
    agg_b = score_b1 + score_b2

    # ── 5. Extra time (if aggregate level, per D-01) ─────────────────────
    et_played = False
    et_a = et_b = 0
    if agg_a == agg_b:
        et_played = True
        # ET: reduced lambda — home advantage to leg 2 host (team_b per D-03)
        # Team_b (second-leg host) gets an extra HOME_ADVANTAGE_MULTIPLIER boost
        # on top of the base factor already applied by expected_goals().
        et_lam_a = expected_goals(ea, eb, base_rate) * et_lambda_factor   # team_a away
        et_lam_b = expected_goals(eb, ea, base_rate) * et_lambda_factor * HOME_ADVANTAGE_MULTIPLIER  # team_b home (D-03)
        et_a = _build_poisson_table(et_lam_a)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_a > 0 else 0
        et_b = _build_poisson_table(et_lam_b)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_b > 0 else 0
        agg_a += et_a
        agg_b += et_b

    # ── 6. Penalties (if still level, per D-02) ──────────────────────────
    penalties_played = False
    pen_a = pen_b = 0
    if agg_a == agg_b:
        penalties_played = True
        pen_a, pen_b = _simulate_penalty_shootout(rng, penalty_conversion_rate)

    # ── 7. Determine winner ──────────────────────────────────────────────
    if agg_a > agg_b:
        winner, loser = team_a, team_b
    elif agg_b > agg_a:
        winner, loser = team_b, team_a
    elif penalties_played:
        # Penalty shootout resolves the tie
        if pen_a > pen_b:
            winner, loser = team_a, team_b
        else:
            winner, loser = team_b, team_a
    else:
        winner, loser = None, None

    # ── 8. Return result dict ────────────────────────────────────────────
    # aggregate_a/b = normal time only (subtract ET contributions)
    return {
        "winner": winner,
        "loser": loser,
        "aggregate_a": score_a1 + score_a2,
        "aggregate_b": score_b1 + score_b2,
        "agg_a_full": agg_a,
        "agg_b_full": agg_b,
        "leg1": {"team_a": team_a, "team_b": team_b, "score_a": score_a1, "score_b": score_b1},
        "leg2": {"team_a": team_a, "team_b": team_b, "score_a": score_a2, "score_b": score_b2},
        "et_played": et_played,
        "et_a": et_a,
        "et_b": et_b,
        "penalties_played": penalties_played,
        "penalty_a": pen_a,
        "penalty_b": pen_b,
    }


def simulate_playoff_round(
    standings: list[dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
    playoff_pairings_path: str | None = None,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """Simulate the UCL knockout phase playoff round (positions 9-24).

    Takes the 36-team standings, resolves the 8 two-legged ties
    (positions 9-24 paired per the dedicated competition data file),
    and returns the 8 winners plus full per-tie results.

    Per D-04: pairings from dedicated competition data file.
    Per D-05: seeded teams (9-16) get second leg at home.
    Per D-11: no football_core modifications.

    Parameters
    ----------
    standings:
        List of 36 team standings dicts from :func:`compute_swiss_standings`.
        Teams with ``zone == "playoff"`` (positions 9-24) participate.
    elo_ratings:
        ``{team_name: Elo}`` dict for Elo-based Poisson simulation.
    rng:
        Seeded ``random.Random`` for deterministic results.
    playoff_pairings_path:
        Path to the playoff pairings data file.  Defaults to a
        conventional path under ``competitions/ucl/data/`` using
        the ``*playoff*`` glob pattern.
    base_rate, et_lambda_factor, penalty_conversion_rate:
        Passed through to :func:`simulate_two_legged_tie`.

    Returns
    -------
    dict
        ``{winners: {tie_number: team_name},
          ties: {tie_number: full tie result dict},
          standings: [the input standings]}``

    Raises
    ------
    ValueError
        If pairings reference invalid positions (not 9-24), if positions
        are duplicated across pairings, or if a team at a required
        position is missing from standings (T-02-05, T-02-06).
    """
    # ── 1. Load pairings ─────────────────────────────────────────────────
    if playoff_pairings_path is None:
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
        )
        candidates = _glob.glob(os.path.join(data_dir, "*playoff*"))
        playoff_pairings_path = (
            candidates[0] if candidates
            else os.path.join(data_dir, "playoff_pairings.json")
        )

    with open(playoff_pairings_path) as f:
        pairings_data = json.load(f)
    pairings = pairings_data["pairings"]

    # ── 2. Threat model validation (T-02-06) ────────────────────────────
    # Validate all 8 pairings reference positions 9-24 inclusive
    seen_positions: set[int] = set()
    for pairing in pairings:
        pos_a = pairing["position_a"]
        pos_b = pairing["position_b"]
        if not (9 <= pos_a <= 16) or not (17 <= pos_b <= 24):
            raise ValueError(
                f"Invalid pairing: position_a={pos_a}, position_b={pos_b}. "
                "Expected position_a in 9-16 (seeded), position_b in 17-24."
            )
        # Check no duplicate positions across pairings
        if pos_a in seen_positions or pos_b in seen_positions:
            raise ValueError(
                f"Duplicate position in pairings: {pos_a} or {pos_b} "
                "appears in multiple ties."
            )
        seen_positions.add(pos_a)
        seen_positions.add(pos_b)

    if len(pairings) != 8:
        raise ValueError(
            f"Expected 8 pairings, got {len(pairings)}"
        )

    # ── 3. Build position-to-team lookup from standings ──────────────────
    pos_to_team: dict[int, str] = {}
    elo: dict[str, float] = {}
    for entry in standings:
        pos = entry["position"]
        team = entry["team"]
        pos_to_team[pos] = team
        elo[team] = entry.get("elo", elo_ratings.get(team, 1500.0))

    # Merge with provided elo_ratings (existing dict takes precedence for
    # any teams not directly in the standings' elo fields)
    for team, rating in elo_ratings.items():
        if team not in elo:
            elo[team] = rating

    # ── 4. Simulate each tie ────────────────────────────────────────────
    # Per D-05: position_a is the seeded team (9-16, second leg at home).
    # Pass seeded team as team_b (home in leg 2).
    winners: dict[int, str] = {}
    tie_results: dict[int, dict] = {}

    for pairing in pairings:
        tie_num = pairing["tie"]
        pos_a = pairing["position_a"]
        pos_b = pairing["position_b"]

        # Threat model validation (T-02-05): validate team exists
        if pos_a not in pos_to_team:
            raise ValueError(
                f"Position {pos_a} not found in standings. "
                "Cannot determine seeded playoff team."
            )
        if pos_b not in pos_to_team:
            raise ValueError(
                f"Position {pos_b} not found in standings. "
                "Cannot determine challenger team."
            )

        team_playoff = pos_to_team[pos_a]    # seeded (home in leg 2)
        team_challenger = pos_to_team[pos_b]  # away in leg 2

        # Seeded team = team_b (home in leg 2 per D-05)
        result = simulate_two_legged_tie(
            team_a=team_challenger,
            team_b=team_playoff,
            elo_ratings=elo,
            rng=rng,
            base_rate=base_rate,
            et_lambda_factor=et_lambda_factor,
            penalty_conversion_rate=penalty_conversion_rate,
        )
        winners[tie_num] = result["winner"]
        tie_results[tie_num] = result

    return {
        "winners": winners,
        "ties": tie_results,
        "standings": standings,
    }


def _simulate_single_knockout_match(
    team_a: str,
    team_b: str,
    elo_ratings: dict[str, float],
    rng: random.Random,
    is_final: bool = False,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """Simulate a single knockout match or tie.

    For finals (is_final=True): single match at neutral venue
    (no home advantage).  Extra time and penalties as needed.

    For non-finals: two-legged tie via simulate_two_legged_tie().
    team_a hosts leg 1, team_b hosts leg 2.

    Returns a result dict compatible with simulate_two_legged_tie
    output (winner, loser, aggregate scores, leg details).
    """
    if is_final:
        # Neutral venue — no home advantage for either team
        lam_a = expected_goals(elo_ratings[team_a], elo_ratings[team_b], base_rate)
        lam_b = expected_goals(elo_ratings[team_b], elo_ratings[team_a], base_rate)
        score_a = _build_poisson_table(lam_a)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a > 0 else 0
        score_b = _build_poisson_table(lam_b)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b > 0 else 0

        if score_a != score_b:
            winner = team_a if score_a > score_b else team_b
            loser = team_b if score_a > score_b else team_a
            et_played = penalties_played = False
            et_a = et_b = pen_a = pen_b = 0
        else:
            # Extra time — neutral venue (both lambdas reduced equally)
            et_played = True
            et_lam_a = lam_a * et_lambda_factor
            et_lam_b = lam_b * et_lambda_factor
            et_a = _build_poisson_table(et_lam_a)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_a > 0 else 0
            et_b = _build_poisson_table(et_lam_b)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_b > 0 else 0

            if (score_a + et_a) != (score_b + et_b):
                winner = team_a if (score_a + et_a) > (score_b + et_b) else team_b
                loser = team_b if (score_a + et_a) > (score_b + et_b) else team_a
                penalties_played = False
                pen_a = pen_b = 0
            else:
                penalties_played = True
                pen_a, pen_b = _simulate_penalty_shootout(rng, penalty_conversion_rate)
                winner = team_a if pen_a > pen_b else team_b
                loser = team_b if pen_a > pen_b else team_a

        return {
            "winner": winner,
            "loser": loser,
            "score_a": score_a + et_a,
            "score_b": score_b + et_b,
            "et_played": et_played,
            "penalties_played": penalties_played,
            "is_final": True,
        }
    else:
        return simulate_two_legged_tie(
            team_a, team_b, elo_ratings, rng,
            base_rate=base_rate,
            et_lambda_factor=et_lambda_factor,
            penalty_conversion_rate=penalty_conversion_rate,
        )


def _validate_bracket_entry(entry: dict) -> None:
    """Validate a bracket rules entry against threat model T-02-08.

    Raises ValueError if required keys are missing or invalid.
    """
    if "match_id" not in entry:
        raise ValueError(f"Bracket entry missing 'match_id': {entry}")
    if "round" not in entry:
        raise ValueError(f"Bracket entry {entry.get('match_id', '?')} missing 'round'")

    rnd = entry["round"]
    if rnd == "R16":
        if "home_seed" not in entry:
            raise ValueError(f"R16 match {entry['match_id']} missing 'home_seed'")
        if "away_playoff_tie" not in entry:
            raise ValueError(f"R16 match {entry['match_id']} missing 'away_playoff_tie'")
        if "quarter" not in entry:
            raise ValueError(f"R16 match {entry['match_id']} missing 'quarter'")
        if not isinstance(entry["home_seed"], int) or not (1 <= entry["home_seed"] <= 8):
            raise ValueError(f"R16 match {entry['match_id']}: invalid home_seed")
        if not isinstance(entry["away_playoff_tie"], int) or not (1 <= entry["away_playoff_tie"] <= 8):
            raise ValueError(f"R16 match {entry['match_id']}: invalid away_playoff_tie")
    else:
        if "source_matches" not in entry:
            raise ValueError(f"{rnd} match {entry['match_id']} missing 'source_matches'")


def build_r16_bracket(
    standings: list[dict],
    playoff_results: dict,
    bracket_rules_path: str | None = None,
) -> dict:
    """Construct the seeded R16 bracket from league standings and playoff results.

    Reads the bracket structure from a dedicated competition data file
    (D-06), matches each league seed (positions 1-8) against the
    corresponding playoff winner, and produces a bracket dict with all
    R16 matchups.

    Per D-06: bracket structure is data-driven (dedicated competition
    data file), not hardcoded in Python.
    Per D-12: competition structure is replaceable data.

    Parameters
    ----------
    standings:
        List of 36 team standings dicts from :func:`compute_swiss_standings`.
        Top 8 (zone='top_8') become seeds.
    playoff_results:
        Output from :func:`simulate_playoff_round` — must contain
        a ``winners`` dict mapping tie_number to team_name.
    bracket_rules_path:
        Path to the bracket rules data file.  Defaults to a
        conventional path under ``competitions/ucl/data/``.

    Returns
    -------
    dict
        ``{matchups: [{match_id, round, quarter, team_a, team_b, ...}],
          tree: {round: [match_ids]}}``

    Raises
    ------
    ValueError
        If bracket data has missing/invalid keys (T-02-08), if
        source_matches reference nonexistent match_ids (T-02-09),
        or if fewer than 8 seeds found in standings.
    """
    # ── 1. Load bracket rules ─────────────────────────────────────────────
    if bracket_rules_path is None:
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
        )
        candidates = _glob.glob(os.path.join(data_dir, "*bracket*"))
        bracket_rules_path = (
            candidates[0] if candidates
            else os.path.join(data_dir, _DEFAULT_BRACKET_FILENAME)
        )

    with open(bracket_rules_path) as f:
        bracket_data = json.load(f)

    # ── 2. Validate bracket entries (T-02-08) ─────────────────────────────
    for entry in bracket_data["matches"]:
        _validate_bracket_entry(entry)

    # ── 3. Verify source_matches references resolve (T-02-09) ─────────────
    all_match_ids = {m["match_id"] for m in bracket_data["matches"]}
    for entry in bracket_data["matches"]:
        if entry["round"] != "R16":
            for src in entry.get("source_matches", []):
                if src not in all_match_ids:
                    raise ValueError(
                        f"{entry['round']} match {entry['match_id']} references "
                        f"unknown source_match '{src}'"
                    )

    # ── 4. Build seed-to-team lookup from standings ───────────────────────
    seed_to_team: dict[int, str] = {}
    for entry in standings:
        if entry["zone"] == "top_8":
            seed_to_team[entry["position"]] = entry["team"]

    if len(seed_to_team) != 8:
        raise ValueError(
            f"Expected 8 seeds (zone='top_8'), got {len(seed_to_team)}"
        )

    # ── 5. Build playoff winner lookup ────────────────────────────────────
    playoff_winners: dict[int, str] = playoff_results["winners"]

    # ── 6. Construct matchups ─────────────────────────────────────────────
    matchups = []
    tree: dict[str, list[str]] = {}

    for match in bracket_data["matches"]:
        if match["round"] == "R16":
            seed_pos = match["home_seed"]
            playoff_tie = match["away_playoff_tie"]
            team_seed = seed_to_team[seed_pos]
            team_pw = playoff_winners[playoff_tie]
            matchups.append({
                "match_id": match["match_id"],
                "round": "R16",
                "quarter": match["quarter"],
                "team_a": team_seed,       # home leg 1
                "team_b": team_pw,          # away leg 1
                "seed_position": seed_pos,
                "playoff_tie": playoff_tie,
                "resolved": False,
                "winner": None,
            })
            tree.setdefault("R16", []).append(match["match_id"])

        elif match.get("source_matches"):
            # QF, SF, FINAL — teams TBD (resolved during simulation)
            matchups.append({
                "match_id": match["match_id"],
                "round": match["round"],
                "quarter": match.get("quarter"),
                "source_matches": match["source_matches"],
                "team_a": None,
                "team_b": None,
                "resolved": False,
                "winner": None,
            })
            tree.setdefault(match["round"], []).append(match["match_id"])

    return {"matchups": matchups, "tree": tree}


def simulate_knockout_tree(*args, **kwargs):
    """Stub — full implementation in Task 2."""
    raise NotImplementedError("Implemented in Task 2")
