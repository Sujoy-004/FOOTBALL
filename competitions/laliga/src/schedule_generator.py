"""Deterministic Berger table double round-robin schedule generator for LaLiga."""

from __future__ import annotations


def generate_berger_schedule(
    teams: list[str],
    season_token: str = "2026/27",
) -> list[dict]:
    """Generate 380 fixtures (38 matchdays x 10 fixtures) for 20 teams.

    Uses deterministic Berger table circle rotation algorithm.
    Round 1-19: First round-robin (190 matches).
    Round 20-38: Second round-robin mirroring round 1-19 with home/away inverted (190 matches).
    """
    sorted_teams = sorted(teams)
    n = len(sorted_teams)
    if n != 20:
        raise ValueError(f"Berger generator requires exactly 20 teams, got {n}")

    # Circle algorithm: fix team index n-1, rotate indices 0..n-2
    # 19 rounds in first half
    rounds: list[list[tuple[str, str]]] = []
    indices = list(range(n - 1))

    for round_idx in range(n - 1):
        round_matches: list[tuple[str, str]] = []
        # Match with fixed team
        fixed = sorted_teams[n - 1]
        opponent = sorted_teams[indices[0]]
        if round_idx % 2 == 0:
            round_matches.append((opponent, fixed))
        else:
            round_matches.append((fixed, opponent))

        # Pair remaining teams
        for k in range(1, (n // 2)):
            home_idx = indices[k]
            away_idx = indices[n - 1 - k]
            if (round_idx + k) % 2 == 0:
                round_matches.append((sorted_teams[home_idx], sorted_teams[away_idx]))
            else:
                round_matches.append((sorted_teams[away_idx], sorted_teams[home_idx]))

        rounds.append(round_matches)
        # Rotate indices (keep first fixed or standard cyclic shift)
        indices = [indices[-1]] + indices[:-1]

    fixtures: list[dict] = []
    token_clean = season_token.replace("/", "_")

    # Matchdays 1-19
    for md_idx, r_matches in enumerate(rounds, 1):
        for home, away in r_matches:
            fixtures.append({
                "match_id": f"derived_{token_clean}_md{md_idx:02d}_{home}_{away}",
                "home_team": home,
                "away_team": away,
                "matchday": md_idx,
                "stage": "REGULAR_SEASON",
                "status": "scheduled",
                "provenance": "derived",
                "schedule_source": "derived_fixtures",
                "event_date": None,
            })

    # Matchdays 20-38 (inverted mirror)
    for md_idx, r_matches in enumerate(rounds, 20):
        for home, away in r_matches:
            fixtures.append({
                "match_id": f"derived_{token_clean}_md{md_idx:02d}_{away}_{home}",
                "home_team": away,
                "away_team": home,
                "matchday": md_idx,
                "stage": "REGULAR_SEASON",
                "status": "scheduled",
                "provenance": "derived",
                "schedule_source": "derived_fixtures",
                "event_date": None,
            })

    return fixtures
