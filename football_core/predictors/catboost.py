"""CatBoost ML prediction ingestion from BSD API — generic."""
import logging
from datetime import datetime, timedelta, timezone

from football_core import constants
from football_core.data_providers.bsd_provider import BSDDataProvider
from football_core.fetcher import find_bracket_match, find_group_match, normalize_team

logger = logging.getLogger(__name__)

_HOME_FIELDS = ("home_probability", "prob_home_win", "home_win", "probability_home")
_DRAW_FIELDS = ("draw_probability", "prob_draw", "draw", "probability_draw")
_AWAY_FIELDS = ("away_probability", "prob_away_win", "away_win", "probability_away")
_XG_HOME_FIELDS: tuple[str, ...] = ("expected_home_goals", "home_expected_goals", "xg_home")
_XG_AWAY_FIELDS: tuple[str, ...] = ("expected_away_goals", "away_expected_goals", "xg_away")


def _normalize_prediction(pred: dict) -> dict:
    event = pred.get("event")
    if not isinstance(event, dict):
        return pred
    flat = dict(pred)
    if "event_id" not in flat and isinstance(event.get("id"), int):
        flat["event_id"] = event["id"]
    ht = event.get("home_team")
    if "home_team" not in flat:
        if isinstance(ht, dict):
            flat["home_team"] = ht.get("name", "")
        elif isinstance(ht, str):
            flat["home_team"] = ht
    at = event.get("away_team")
    if "away_team" not in flat:
        if isinstance(at, dict):
            flat["away_team"] = at.get("name", "")
        elif isinstance(at, str):
            flat["away_team"] = at
    return flat


def _extract_probability(data: dict, field_names: tuple[str, ...]) -> float | None:
    for name in field_names:
        val = data.get(name)
        if val is not None and isinstance(val, (int, float)):
            return float(val) / 100.0
    return None


def _extract_xg(data: dict, field_names: tuple[str, ...]) -> float | None:
    for name in field_names:
        val = data.get(name)
        if val is not None and isinstance(val, (int, float)):
            return float(val)
    return None


def _find_match_id(
    home_norm: str,
    away_norm: str,
    groups: dict,
    bracket: list[dict],
) -> str | None:
    groups_data = groups.get("groups", groups)
    for group_letter in groups_data:
        match_id = find_group_match(home_norm, away_norm, group_letter, 0, groups)
        if match_id:
            return match_id
    return find_bracket_match(home_norm, away_norm, bracket)


def parse_catboost_response(
    bsd_predictions: list[dict],
    alias_lookup: dict[str, str],
    groups: dict,
    bracket: list[dict],
) -> dict[str, dict]:
    now = datetime.now(timezone.utc)
    result: dict[str, dict] = {}

    for prediction in bsd_predictions:
        if not isinstance(prediction, dict):
            continue
        prediction = _normalize_prediction(prediction)
        event_id = prediction.get("event_id")
        if event_id is None:
            continue
        home_name = prediction.get("home_team", "")
        away_name = prediction.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)
        if home_norm is None or away_norm is None:
            logger.debug(
                "Skipping prediction event %s: unmatchable teams %r vs %r",
                event_id, home_name, away_name,
            )
            continue
        match_id = _find_match_id(home_norm, away_norm, groups, bracket)
        if match_id is None:
            logger.debug(
                "Skipping prediction event %s: no match_id for %s vs %s",
                event_id, home_norm, away_norm,
            )
            continue
        timestamp = prediction.get("updated_at", now.isoformat())
        home_prob = _extract_probability(prediction, _HOME_FIELDS)
        draw_prob = _extract_probability(prediction, _DRAW_FIELDS)
        away_prob = _extract_probability(prediction, _AWAY_FIELDS)
        entry: dict = {
            "probability": None,
            "confidence": prediction.get("confidence"),
            "model_version": prediction.get("model_version"),
            "timestamp": timestamp,
        }
        if home_prob is None or draw_prob is None or away_prob is None:
            entry["available"] = False
            entry["reason"] = "predictions_not_available"
        elif not (0 <= home_prob <= 1 and 0 <= draw_prob <= 1 and 0 <= away_prob <= 1):
            entry["available"] = False
            entry["reason"] = "invalid_probability"
        else:
            entry["probability"] = home_prob
            entry["available"] = True
        home_xg = _extract_xg(prediction, _XG_HOME_FIELDS)
        away_xg = _extract_xg(prediction, _XG_AWAY_FIELDS)
        if home_xg is not None:
            entry["expected_home_goals"] = home_xg
        if away_xg is not None:
            entry["expected_away_goals"] = away_xg
        result[match_id] = entry
    return result


def _all_match_ids(
    groups: dict,
    bracket: list[dict] | None,
) -> set[str]:
    """Collect all match IDs from groups and optional bracket."""
    mids: set[str] = set()
    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups
    for gd in groups_data.values():
        for match in gd.get("matches") or []:
            mid = match.get("match_id")
            if mid:
                mids.add(mid)
    if bracket:
        for match in bracket:
            mid = match.get("match_id")
            if mid:
                mids.add(mid)
    return mids


def fetch_and_cache_catboost(
    api_key: str,
    alias_lookup: dict[str, str],
    groups: dict,
    bracket: list[dict],
    cache_ttl_hours: int = 24,
    league_id: int = 27,
) -> dict:
    now = datetime.now(timezone.utc)
    provider = BSDDataProvider(api_key, league_id=league_id)
    results = provider.fetch_predictions(league_id=league_id)
    if not results:
        logger.warning("CatBoost predictions empty or failed — marking all matches unavailable")
        empty_matches: dict[str, dict] = {}
        for mid in _all_match_ids(groups, bracket):
            empty_matches[mid] = {"probability": 0.5, "available": False, "reason": "provider_not_available"}
        return {"fetched_at": now.isoformat(), "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(), "matches": empty_matches}
    parsed = parse_catboost_response(results, alias_lookup, groups, bracket)
    return {"fetched_at": now.isoformat(), "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(), "matches": parsed}
