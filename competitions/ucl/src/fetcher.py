"""Fetch and normalize live UCL match results from provider API."""

import logging
from football_core.fetcher import fetch_raw_matches, _build_alias_lookup, normalize_team

logger = logging.getLogger(__name__)


def build_ucl_url() -> str:
    """Build API URL for UCL events."""
    return "https://api.football-data.org/v4/competitions/CL/matches"


def fetch_ucl_matches(
    api_key: str,
    aliases: dict[str, list[str]],
    fixtures_schedule: dict,
    api_url: str | None = None,
) -> list[dict]:
    """Fetch completed UCL matches from provider API and normalize to internal format.

    Parameters
    ----------
    api_key : str
        API authentication token.
    aliases : dict[str, list[str]]
        Team alias mapping: {canonical_name: [variant_names]}.
        See ``team_aliases.json`` for format.
    fixtures_schedule : dict
        UCL fixture schedule with ``teams`` and ``matchdays`` keys.
        Structure matches ``fixtures.json`` schema.
    api_url : str, optional
        API URL override.

    Returns
    -------
    list[dict]
        Normalized match entries with keys:
        - match_id: str — internal fixture match identifier
        - team_a: str — normalized home team canonical name
        - team_b: str — normalized away team canonical name
        - winner: str or None — canonical name of winner (None for draw)
        - is_draw: bool — whether match ended in a draw
        - home_score: int — home team goals
        - away_score: int — away team goals
        - completed_at: str — ISO event date from API
        - odds: dict (optional) — fair probabilities
            with keys "home", "draw", "away" (sum ~= 1.0)
    """
    alias_lookup = _build_alias_lookup(aliases, bracket=[])

    # Register fixture teams into alias lookup so teams missing from aliases
    # still resolve through their canonical fixture name.
    for team in fixtures_schedule.get("teams", []):
        alias_lookup[team["name"].strip().lower()] = team["name"]

    url = api_url or build_ucl_url()
    raw = fetch_raw_matches(api_key, url, 0)

    # Build bidirectional fixture lookup: (team_a, team_b) -> match_id
    # Both orientations are stored so events with swapped home/away
    # still match their fixture entry.
    fixture_lookup: dict[tuple[str, str], str] = {}
    for md in fixtures_schedule.get("matchdays", []):
        for match in md:
            pair = (match["team_a"], match["team_b"])
            fixture_lookup[pair] = match["match_id"]
            fixture_lookup[(match["team_b"], match["team_a"])] = match["match_id"]

    results: list[dict] = []
    for event in raw:
        if event.get("status") != "finished":
            continue

        home_name = event.get("home_team", "")
        away_name = event.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.warning(
                "Unmatchable teams: home=%r, away=%r", home_name, away_name
            )
            continue

        match_id = fixture_lookup.get((home_norm, away_norm))
        if match_id is None:
            logger.warning(
                "No fixture match for %s vs %s", home_norm, away_norm
            )
            continue

        home_score = event.get("home_score", 0)
        away_score = event.get("away_score", 0)

        if home_score > away_score:
            winner = home_norm
            is_draw = False
        elif away_score > home_score:
            winner = away_norm
            is_draw = False
        else:
            winner = None
            is_draw = True

        entry: dict = {
            "match_id": match_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "is_draw": is_draw,
            "home_score": home_score,
            "away_score": away_score,
            "completed_at": event.get("event_date", ""),
        }

        # Extract market odds with vig removal (D-03)
        odds_home = event.get("odds_home")
        odds_draw = event.get("odds_draw")
        odds_away = event.get("odds_away")
        if all(o is not None for o in [odds_home, odds_draw, odds_away]):
            from football_core.predictors.odds import remove_vig

            entry["odds"] = remove_vig(odds_home, odds_draw, odds_away)

        results.append(entry)

    return results
