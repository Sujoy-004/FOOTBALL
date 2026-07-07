"""Fetch and process live match results — extends football_core with WC-specific enrichment."""

import logging
from datetime import datetime

from football_core.fetcher import (
    fetch_raw_matches,
    _build_alias_lookup,
    normalize_team,
    find_bracket_match,
    _extract_group_letter,
    find_group_match,
)

from src import constants
from football_core.enrichment import extract_stats, extract_context

logger = logging.getLogger(__name__)


def build_historic_url(league_id: int = 27) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    base = "https://sports.bzzoiro.com/api/events/"
    return f"{base}?league_id={league_id}&date_from={constants.WC_START_DATE}&date_to={today}&limit=200"


def _extract_ai_preview(raw_event: dict) -> str | None:
    preview = raw_event.get("ai_preview")
    if isinstance(preview, dict):
        text = preview.get("text")
        if text and isinstance(text, str) and text.strip():
            return text.strip()
    return None


def process_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    bracket: list[dict],
    aliases: dict[str, list[str]],
    played_ids: set[str],
) -> list[dict]:
    alias_lookup = _build_alias_lookup(aliases, bracket)
    results: list[dict] = []

    for match in raw_matches:
        if match.get("status") != "finished":
            continue

        match_id = str(match.get("id", ""))
        if match_id in played_ids:
            continue

        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")

        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.warning("Unmatchable team names: home=%r, away=%r", home_name, away_name)
            continue

        bracket_id = find_bracket_match(home_norm, away_norm, bracket)
        if bracket_id is None:
            logger.warning("No bracket match found for %s vs %s", home_norm, away_norm)
            continue

        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)

        winner = None
        if home_score > away_score:
            winner = home_norm
        elif away_score > home_score:
            winner = away_norm
        else:
            # Tied — try extra time score (extra_time_score.home/away)
            ets = match.get("extra_time_score")
            if isinstance(ets, dict):
                et_h, et_a = ets.get("home"), ets.get("away")
                if et_h is not None and et_a is not None and et_h != et_a:
                    winner = home_norm if et_h > et_a else away_norm
            # Try penalty shootout (penalty_shootout.home/away)
            if winner is None:
                ps = match.get("penalty_shootout")
                if isinstance(ps, dict):
                    ps_h, ps_a = ps.get("home"), ps.get("away")
                    if ps_h is not None and ps_a is not None and ps_h != ps_a:
                        winner = home_norm if ps_h > ps_a else away_norm
            # Try flat penalty fields
            if winner is None:
                pen_home = match.get("penalty_home") or match.get("home_penalty") or match.get("pen_home")
                pen_away = match.get("penalty_away") or match.get("away_penalty") or match.get("pen_away")
                if pen_home is not None and pen_away is not None and pen_home != pen_away:
                    winner = home_norm if pen_home > pen_away else away_norm
            # Try winner / result field (string or dict with name)
            if winner is None:
                bsd_winner = match.get("winner") or match.get("result")
                if bsd_winner:
                    w_name = None
                    if isinstance(bsd_winner, str):
                        w_name = bsd_winner
                    elif isinstance(bsd_winner, dict):
                        w_name = bsd_winner.get("name") or bsd_winner.get("full_name")
                    if w_name:
                        w_norm = normalize_team(w_name, alias_lookup) or alias_lookup.get(w_name.strip().lower())
                        if w_norm == home_norm:
                            winner = home_norm
                        elif w_norm == away_norm:
                            winner = away_norm

        is_draw = winner is None

        entry: dict = {
            "match_id": bracket_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "is_draw": is_draw,
            "home_score": home_score,
            "away_score": away_score,
            "completed_at": match.get("event_date", ""),
        }

        stats = extract_stats(match)
        if stats is not None:
            entry["stats"] = stats

        ctx = extract_context(match)
        if ctx is not None:
            entry["context"] = ctx

        ai_preview = _extract_ai_preview(match)
        if ai_preview is not None:
            entry["ai_preview"] = ai_preview

        results.append(entry)

    return results


def process_group_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    groups: dict,
    aliases: dict[str, list[str]],
    played_group_ids: set[str],
    played_bsd_event_ids: set[str],
) -> list[dict]:
    alias_lookup = _build_alias_lookup(aliases, [])
    groups_data = groups.get("groups", groups)
    for group_data in groups_data.values():
        for team in group_data.get("teams", []):
            alias_lookup[team.strip().lower()] = team

    results: list[dict] = []

    for match in raw_matches:
        if match.get("status") != "finished":
            continue

        group_name = match.get("group_name")
        if group_name is None:
            continue

        bsd_id = str(match.get("id", ""))
        if bsd_id in played_bsd_event_ids:
            continue
        played_bsd_event_ids.add(bsd_id)

        group_letter = _extract_group_letter(group_name)
        if group_letter is None:
            logger.warning("Invalid group_name: %r", group_name)
            continue

        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.warning(
                "Unmatchable team names: home=%r, away=%r", home_name, away_name
            )
            continue

        round_number = match.get("round_number", 0)
        match_id = find_group_match(
            home_norm, away_norm, group_letter, round_number, groups
        )
        if match_id is None:
            logger.warning(
                "No group match found for %s vs %s in group %s (round %d)",
                home_norm, away_norm, group_letter, round_number,
            )
            continue

        if match_id in played_group_ids:
            continue

        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)
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
            "completed_at": match.get("event_date", ""),
        }

        stats = extract_stats(match)
        if stats is not None:
            entry["stats"] = stats

        ctx = extract_context(match)
        if ctx is not None:
            entry["context"] = ctx

        ai_preview = _extract_ai_preview(match)
        if ai_preview is not None:
            entry["ai_preview"] = ai_preview

        results.append(entry)

    return results
