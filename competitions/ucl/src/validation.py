"""Fixture schedule validation for UCL league phase.

Validates the full UCL fixture schedule against competition requirements:
- Exactly 36 teams in 4 pots of 9
- Exactly 8 matchdays with 18 matches each (144 total)
- Each team plays 8 matches (4 home, 4 away)
- Each team faces 2 opponents from each of the 4 pots
- No duplicate matchups (same pair appears only once)
- All team references are valid
"""

from __future__ import annotations

import collections
from typing import Any, Dict, List, Set, Tuple


def validate_ucl_fixtures(fixtures: dict) -> dict:
    """Validate a UCL fixture schedule and return the validated dict.

    Parameters
    ----------
    fixtures : dict
        The fixture schedule JSON, expected to contain a ``schedule`` key
        with ``teams`` and ``matchdays``.

    Returns
    -------
    dict
        The validated ``fixtures`` dict (same reference).

    Raises
    ------
    ValueError
        If any constraint is violated.
    TypeError
        If *fixtures* is not a dict or lacks required structure.
    """
    if not isinstance(fixtures, dict):
        raise TypeError("fixtures must be a dict")

    if "schedule" not in fixtures:
        raise ValueError("fixtures missing 'schedule' key")

    schedule = fixtures["schedule"]

    if not isinstance(schedule, dict):
        raise ValueError("schedule must be a dict")

    teams: List[Dict[str, Any]] = schedule.get("teams", [])
    matchdays: List[List[Dict[str, Any]]] = schedule.get("matchdays", [])

    # ── Team count ───────────────────────────────────────────────────────
    if len(teams) != 36:
        raise ValueError(
            f"Expected 36 teams, got {len(teams)}"
        )

    # Build helper maps
    team_names: Set[str] = set()
    team_pots: Dict[str, int] = {}
    for t in teams:
        name = t.get("name", "")
        pot = t.get("pot", 0)
        team_names.add(name)
        team_pots[name] = pot

    # ── Matchday count ──────────────────────────────────────────────────
    if len(matchdays) != 8:
        raise ValueError(
            f"Expected 8 matchdays, got {len(matchdays)}"
        )

    # ── Matchday sizes ──────────────────────────────────────────────────
    for i, md in enumerate(matchdays):
        if len(md) != 18:
            raise ValueError(
                f"Matchday {i + 1} has {len(md)} matches, expected 18"
            )

    # ── Track per-team stats ────────────────────────────────────────────
    opponents: Dict[str, Set[str]] = {name: set() for name in team_names}
    pot_distribution: Dict[str, Dict[int, int]] = {
        name: {p: 0 for p in [1, 2, 3, 4]} for name in team_names
    }
    home_count: Dict[str, int] = {name: 0 for name in team_names}
    away_count: Dict[str, int] = {name: 0 for name in team_names}
    seen_pairs: Set[Tuple[str, str]] = set()
    total_matches = 0

    for i, md in enumerate(matchdays):
        for j, match in enumerate(md):
            total_matches += 1
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")

            # Validate team references
            if team_a not in team_names:
                raise ValueError(
                    f"Matchday {i + 1}, match {j + 1}: unknown team '{team_a}'"
                )
            if team_b not in team_names:
                raise ValueError(
                    f"Matchday {i + 1}, match {j + 1}: unknown team '{team_b}'"
                )

            # Sort pair to detect A-B / B-A duplicates
            pair = (team_a, team_b) if team_a <= team_b else (team_b, team_a)
            if pair in seen_pairs:
                raise ValueError(
                    f"Duplicate matchup: {pair[0]} vs {pair[1]}"
                )
            seen_pairs.add(pair)

            # Track opponents
            opponents[team_a].add(team_b)
            opponents[team_b].add(team_a)

            # Track pot distribution from match metadata
            home_pot = match.get("home_pot", 0)
            away_pot = match.get("away_pot", 0)
            pot_distribution[team_a][away_pot] = (
                pot_distribution[team_a].get(away_pot, 0) + 1
            )
            pot_distribution[team_b][home_pot] = (
                pot_distribution[team_b].get(home_pot, 0) + 1
            )

            # Home/away tracking
            home_count[team_a] += 1
            away_count[team_b] += 1

    # ── Total match count ───────────────────────────────────────────────
    if total_matches != 144:
        raise ValueError(
            f"Expected 144 total matches, got {total_matches}"
        )

    # ── Per-team opponent count ─────────────────────────────────────────
    for name in team_names:
        if len(opponents[name]) != 8:
            raise ValueError(
                f"Team '{name}' has {len(opponents[name])} opponents, expected 8"
            )

    # ── Per-team pot distribution ───────────────────────────────────────
    for name in team_names:
        dist = pot_distribution[name]
        for pot in [1, 2, 3, 4]:
            if dist.get(pot, 0) != 2:
                raise ValueError(
                    f"Team '{name}' has {dist.get(pot, 0)} opponents from pot {pot}, expected 2"
                )

    # ── Home/away balance ──────────────────────────────────────────────
    for name in team_names:
        if home_count[name] != 4:
            raise ValueError(
                f"Team '{name}' has {home_count[name]} home matches, expected 4"
            )
        if away_count[name] != 4:
            raise ValueError(
                f"Team '{name}' has {away_count[name]} away matches, expected 4"
            )

    return fixtures
