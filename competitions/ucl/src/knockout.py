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

from football_core.constants import EXPECTED_GOALS_BASE_RATE
from football_core.knockout import (
    _simulate_penalty_shootout,
    simulate_single_match,
    simulate_two_legged_tie,
)

_DEFAULT_BRACKET_FILENAME = "bracket_rules.json"


def simulate_playoff_round(
    standings: list[dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
    pairings_data: dict | None = None,
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
    pairings_data:
        Pre-loaded pairings data dict (with ``pairings`` key).  If provided,
        bypasses file loading.  Useful when calling from a tight loop to
        avoid redundant disk I/O.
    playoff_pairings_path:
        Path to the playoff pairings data file.  Ignored if *pairings_data*
        is provided.  Defaults to a conventional path under
        ``competitions/ucl/data/`` using the ``*playoff*`` glob pattern.
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
    if pairings_data is None:
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

    # ── 3. Draw step: shuffle positions within each draw_group ────────────
    # Simulates the UEFA draw ceremony: seeded pairs (9/10, 11/12, etc.)
    # and challenger pairs (23/24, 21/22, etc.) are randomly assigned
    # to silver/blue bracket sides.
    draw_groups: dict[str, list[dict]] = {}
    for p in pairings:
        dg = p.get("draw_group")
        if dg:
            draw_groups.setdefault(dg, []).append(p)
    for g in draw_groups.values():
        if len(g) != 2:
            continue
        seeds = [p["position_a"] for p in g]
        challs = [p["position_b"] for p in g]
        rng.shuffle(seeds)
        rng.shuffle(challs)
        for i, p in enumerate(g):
            p["position_a"] = seeds[i]
            p["position_b"] = challs[i]

    # ── 4. Build position-to-team lookup from standings ──────────────────
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
        return simulate_single_match(
            team_a, team_b, elo_ratings, rng,
            base_rate=base_rate,
            et_lambda_factor=et_lambda_factor,
            penalty_conversion_rate=penalty_conversion_rate,
        )
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
    bracket_data: dict | None = None,
    bracket_rules_path: str | None = None,
    rng: random.Random | None = None,
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
    bracket_data:
        Pre-loaded bracket rules data dict (with ``matches`` key).  If
        provided, bypasses file loading.  Useful when calling from a tight
        loop to avoid redundant disk I/O.
    bracket_rules_path:
        Path to the bracket rules data file.  Ignored if *bracket_data* is
        provided.  Defaults to a conventional path under
        ``competitions/ucl/data/``.

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
    if bracket_data is None:
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

    # ── 4. Draw step: shuffle seeds and playoff ties within each group ────
    # Simulates the UEFA R16 draw: paired seeds (1/2, 3/4, etc.) and their
    # corresponding playoff tie winners are randomly assigned within each
    # quarter.  Skips if no rng provided (backward compat).
    if rng is not None:
        r16_groups: dict[str, list[dict]] = {}
        for m in bracket_data["matches"]:
            if m["round"] == "R16" and "draw_group" in m:
                r16_groups.setdefault(m["draw_group"], []).append(m)
        for g in r16_groups.values():
            if len(g) != 2:
                continue
            seeds = [m["home_seed"] for m in g]
            ties = [m["away_playoff_tie"] for m in g]
            rng.shuffle(seeds)
            rng.shuffle(ties)
            for i, m in enumerate(g):
                m["home_seed"] = seeds[i]
                m["away_playoff_tie"] = ties[i]

    # ── 5. Build seed-to-team lookup from standings ───────────────────────
    seed_to_team: dict[int, str] = {}
    for entry in standings:
        if entry["zone"] == "top_8":
            seed_to_team[entry["position"]] = entry["team"]

    if len(seed_to_team) != 8:
        raise ValueError(
            f"Expected 8 seeds (zone='top_8'), got {len(seed_to_team)}"
        )

    # ── 6. Build playoff winner lookup ────────────────────────────────────
    playoff_winners: dict[int, str] = playoff_results["winners"]

    # ── 7. Construct matchups ─────────────────────────────────────────────
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
                "team_a": team_pw,          # playoff winner hosts leg 1
                "team_b": team_seed,        # seed hosts leg 2 (advantage)
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


def simulate_knockout_tree(
    bracket: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """Simulate the full knockout tree: R16 -> QF -> SF -> Final.

    Traverses the bracket produced by :func:`build_r16_bracket`,
    simulating each match in round order.  R16, QF, and SF are
    two-legged aggregate ties.  The Final is a single match at
    neutral venue.

    Tracks which round each team reaches (D-09: stage granularity).

    Parameters
    ----------
    bracket:
        Bracket dict from :func:`build_r16_bracket` with ``matchups``
        and ``tree``.
    elo_ratings:
        ``{team_name: Elo}`` dict.
    rng:
        Seeded ``random.Random`` for deterministic results.
    base_rate, et_lambda_factor, penalty_conversion_rate:
        Passed to match simulation functions.

    Returns
    -------
    dict
        ``{matchups: [updated match dicts with results],
          rounds: {round_name: [{match_id, team_a, team_b, winner, ...}]},
          stage: {team_name: stage_string},
          champion: team_name | None}``
    """
    # ── 1. Build winner_progression lookup ────────────────────────────────
    winner_progression: dict[str, str] = {}
    # Defensive copy of bracket matchups (T-02-09)
    updated_matchups = list(bracket["matchups"])
    rounds_output: dict[str, list[dict]] = {}
    stage: dict[str, str] = {}

    # ── 2. Traverse rounds in order ───────────────────────────────────────
    round_order = ["R16", "QF", "SF", "FINAL"]

    for round_name in round_order:
        round_matches = [m for m in updated_matchups if m["round"] == round_name]
        is_final = (round_name == "FINAL")
        round_results: list[dict] = []

        for match in round_matches:
            if round_name == "R16":
                # Teams already assigned from bracket construction
                team_a = match["team_a"]
                team_b = match["team_b"]
            else:
                # QF/SF/FINAL: look up winners from source matches
                source_winners = [
                    winner_progression[src] for src in match["source_matches"]
                ]
                team_a, team_b = source_winners[0], source_winners[1]

            # Simulate the match/tie
            result = _simulate_single_knockout_match(
                team_a, team_b, elo_ratings, rng,
                is_final=is_final,
                base_rate=base_rate,
                et_lambda_factor=et_lambda_factor,
                penalty_conversion_rate=penalty_conversion_rate,
            )

            winner = result["winner"]
            loser = result["loser"]
            winner_progression[match["match_id"]] = winner

            # Record stage reached for loser (D-09)
            if round_name == "R16":
                stage[loser] = "R16"
                stage[winner] = "R16"
            elif round_name == "QF":
                stage[loser] = "QF"
            elif round_name == "SF":
                stage[loser] = "SF"
            elif round_name == "FINAL":
                stage[loser] = "FINAL"
                stage[winner] = "CHAMPION"

            # Build round entry
            round_entry = {
                "match_id": match["match_id"],
                "team_a": team_a,
                "team_b": team_b,
                "winner": winner,
                "result": result,
            }
            round_results.append(round_entry)

        # Promote winners to next round stage label
        if round_name == "R16":
            for r in round_results:
                stage[r["winner"]] = "QF"
        elif round_name == "QF":
            for r in round_results:
                stage[r["winner"]] = "SF"
        elif round_name == "SF":
            for r in round_results:
                stage[r["winner"]] = "FINAL"

        rounds_output[round_name] = round_results

    # ── 3. Determine champion ─────────────────────────────────────────────
    champion = winner_progression.get("final_01")

    return {
        "matchups": updated_matchups,
        "rounds": rounds_output,
        "stage": stage,
        "champion": champion,
}


def track_knockout_stages(
    standings: list[dict],
    knockout_result: dict,
) -> dict[str, str]:
    """Map every league phase team to its final stage (D-09).

    Parameters
    ----------
    standings:
        36-team standings from :func:`compute_swiss_standings`.
        Used to determine who was eliminated in league phase (25-36)
        and who reached the playoff (9-24).
    knockout_result:
        Output from :func:`simulate_knockout_tree` containing
        ``stage`` dict (teams that reached R16 or beyond) and
        ``champion``.

    Returns
    -------
    dict[str, str]
        ``{team_name: stage}`` for all 36 teams, where stage is one of:
        ``eliminated``, ``playoff``, ``r16``, ``qf``, ``sf``,
        ``final``, ``champion`` (D-09).
    """
    stages: dict[str, str] = {}

    for entry in standings:
        team = entry["team"]
        position = entry["position"]
        zone = entry["zone"]

        if position >= 25:
            stages[team] = "eliminated"
        elif zone == "top_8":
            # Top 8 auto-qualify for R16; may be overridden by knockout_result
            stages[team] = "r16"
        elif zone == "playoff":
            # 9-24: could be playoff exit or better if they advanced
            stages[team] = "playoff"

    # Override with knockout stages for teams that advanced
    # Normalise to lowercase D-09 format
    knockout_stages = knockout_result.get("stage", {})
    champion = knockout_result.get("champion")

    for team, stage in knockout_stages.items():
        stages[team] = stage.lower()

    if champion and champion not in knockout_stages:
        stages[champion] = "champion"

    # Ensure all 36 teams have a stage
    for entry in standings:
        if entry["team"] not in stages:
            stages[entry["team"]] = "eliminated"

    return stages
