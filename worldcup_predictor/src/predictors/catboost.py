"""CatBoost ML prediction ingestion from BSD API.

Downloads home/draw/away probabilities with confidence scores from BSD's
/api/predictions/ endpoint, maps BSD event IDs to internal match_ids via
team-pair resolution, and caches results with 24h TTL.

The BSD CatBoost model (58k+ matches, 163 features, catboost-v5.0) provides
a mature ML signal that diversifies the predictor beyond pure Elo. Consumed
via REST API — no local CatBoost library needed.

Threat model:
- T-13-04: Handle multiple field name patterns via priority-ordered fallback
  chain. Validate probability ∈ [0,1] with type checks. Set available=False
  for anything outside range or None.
- T-13-05: 3-attempt retry with backoff (1s, 2s, 4s). On all failures, return
  empty matches dict (never crash). Same pattern as fetch_raw_matches.
- T-13-06: Never log BSD_API_KEY. Use same Authorization: Token header pattern
  as fetcher.py. Exception messages exclude sensitive data.
- T-13-SC: No new packages. catboost Python library NOT installed (REST API).
- Phase 18: xG fields (expected_home_goals, expected_away_goals) extracted alongside
  probabilities. xG values are already in Poisson lambda scale — no /100 division.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from src import constants
from src.fetcher import (
    _find_bracket_match,
    _find_group_match,
    _normalize_team,
)

logger = logging.getLogger(__name__)

# Priority-ordered fallback field names for home/draw/away probabilities.
# The BSD predictions endpoint may use different key names depending on
# API version. Each tuple is tried in order until a valid value is found.
_HOME_FIELDS = ("home_probability", "home_win", "probability_home")
_DRAW_FIELDS = ("draw_probability", "draw", "probability_draw")
_AWAY_FIELDS = ("away_probability", "away_win", "probability_away")

# xG field names (Phase 18): BSD predictions endpoint contains
# expected_home_goals / expected_away_goals (already in Poisson lambda scale).
_XG_HOME_FIELDS: tuple[str, ...] = ("expected_home_goals", "home_expected_goals", "xg_home")
_XG_AWAY_FIELDS: tuple[str, ...] = ("expected_away_goals", "away_expected_goals", "xg_away")


# ─── Helpers ──────────────────────────────────────────────────────────────


def _extract_probability(
    data: dict,
    field_names: tuple[str, ...],
) -> float | None:
    """Extract a single probability value by trying field names in priority order.

    The BSD predictions API returns flat top-level percentage fields (0-100).
    This function extracts the raw value and converts it to a 0-1 float.

    Args:
        data: The prediction dict (or sub-dict) to read from.
        field_names: Ordered tuple of field names to try (e.g. "home_probability"
                     → "home_win" → "probability_home").

    Returns:
        Float value between 0 and 1 if found and valid, None otherwise.
    """
    for name in field_names:
        val = data.get(name)
        if val is not None and isinstance(val, (int, float)):
            return float(val) / 100.0
    return None


def _extract_xg(
    data: dict,
    field_names: tuple[str, ...],
) -> float | None:
    """Extract xG value by trying field names in priority order.

    xG values are already in the correct scale (0.3–3.0) for Poisson lambdas
    — do NOT divide by 100. Phase 18: xG overrides Elo in precompute_matchup_lambdas().

    Args:
        data: The prediction dict to read from.
        field_names: Ordered tuple of field names to try.

    Returns:
        Float xG value if found, None otherwise.
    """
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
    """Find match_id by searching all groups first, then the bracket.

    Unlike the events endpoint (which includes group_name), the predictions
    endpoint does not include group information. This helper iterates over
    all groups to find the matching team pair, then falls back to bracket
    lookup for knockout matches.

    Args:
        home_norm: Normalized home team name.
        away_norm: Normalized away team name.
        groups: Groups dict with nested "groups" key or flat.
        bracket: Bracket list for knockout match resolution.

    Returns:
        Match ID string or None if not found in any group or bracket.
    """
    groups_data = groups.get("groups", groups)
    for group_letter in groups_data:
        match_id = _find_group_match(home_norm, away_norm, group_letter, 0, groups)
        if match_id:
            return match_id
    return _find_bracket_match(home_norm, away_norm, bracket)


# ─── Response Parsing ─────────────────────────────────────────────────────


def parse_catboost_response(
    bsd_predictions: list[dict],
    alias_lookup: dict[str, str],
    groups: dict,
    bracket: list[dict],
) -> dict[str, dict]:
    """Parse BSD predictions API response into match_id → prediction entry mapping.

    For each prediction entry in the BSD response list:
      1. Validates event_id is present.
      2. Normalizes team names via alias_lookup.
      3. Resolves match_id via group/bracket team-pair matching.
      4. Extracts predictions sub-dict with field-name fallback chain.
      5. Validates probability range [0, 1].
      6. Stores canonical home-win probability per D-13.

    Args:
        bsd_predictions: List of BSD prediction event dicts from /api/predictions/.
        alias_lookup: Mapping of team name variants to canonical names.
        groups: Groups dict for group stage match resolution.
        bracket: Bracket list for knockout match resolution.

    Returns:
        dict mapping match_id → entry dict with keys:
        {probability, confidence, model_version, timestamp, available, reason?}
        and optional keys {expected_home_goals, expected_away_goals} (Phase 18 xG).
    """
    now = datetime.now(timezone.utc)
    result: dict[str, dict] = {}

    for prediction in bsd_predictions:
        if not isinstance(prediction, dict):
            continue

        # Skip entries without a valid event_id
        event_id = prediction.get("event_id")
        if event_id is None:
            continue

        # Normalize team names
        home_name = prediction.get("home_team", "")
        away_name = prediction.get("away_team", "")
        home_norm = _normalize_team(home_name, alias_lookup)
        away_norm = _normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.debug(
                "Skipping prediction event %s: unmatchable teams %r vs %r",
                event_id, home_name, away_name,
            )
            continue

        # Resolve match_id (search groups first, then bracket)
        match_id = _find_match_id(home_norm, away_norm, groups, bracket)
        if match_id is None:
            logger.debug(
                "Skipping prediction event %s: no match_id for %s vs %s",
                event_id, home_norm, away_norm,
            )
            continue

        # Build the entry dict
        timestamp = prediction.get("updated_at", now.isoformat())

        # BSD predictions API returns flat top-level fields (percentages 0-100),
        # not a nested "predictions" sub-dict. Read directly from prediction dict.
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
            # Store canonical home-win probability per D-13
            entry["probability"] = home_prob
            entry["available"] = True

        # Phase 18: Extract xG values alongside probabilities (no /100 division)
        home_xg = _extract_xg(prediction, _XG_HOME_FIELDS)
        away_xg = _extract_xg(prediction, _XG_AWAY_FIELDS)
        if home_xg is not None:
            entry["expected_home_goals"] = home_xg
        if away_xg is not None:
            entry["expected_away_goals"] = away_xg

        result[match_id] = entry

    return result


# ─── Fetch and Cache ──────────────────────────────────────────────────────


def fetch_and_cache_catboost(
    api_key: str,
    alias_lookup: dict[str, str],
    groups: dict,
    bracket: list[dict],
    cache_ttl_hours: int = 24,
) -> dict:
    """Fetch CatBoost predictions from BSD API, parse, and return cache dict.

    Implements 3-attempt exponential backoff (1s, 2s, 4s) matching the
    pattern from fetcher.py::fetch_raw_matches. On any failure (timeout,
    connection, HTTP error, JSON decode, 401), returns an empty matches
    dict — graceful degradation per T-13-05.

    Args:
        api_key: BSD API key for Authorization header.
        alias_lookup: Team name alias lookup for match_id resolution.
        groups: Groups dict for group stage matching.
        bracket: Bracket list for knockout matching.
        cache_ttl_hours: Cache TTL in hours (default: 24).

    Returns:
        Cache dict with keys: fetched_at (ISO), expires_at (ISO),
        matches (dict of match_id → entry).
    """
    now = datetime.now(timezone.utc)
    url = "https://sports.bzzoiro.com/api/predictions/?league=27"
    headers = {"Authorization": f"Token {api_key}"}
    backoff_seconds = [1, 2, 4]

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=constants.API_TIMEOUT)

            if resp.status_code == 401:
                logger.warning(
                    "HTTP 401 (invalid API key) for catboost predictions, "
                    "returning empty matches"
                )
                return {
                    "fetched_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
                    "matches": {},
                }

            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            parsed = parse_catboost_response(results, alias_lookup, groups, bracket)

            # Upsert into permanent prediction ledger — matches form.py pattern
            if parsed:
                try:
                    from src.state import ledger_upsert
                    for mid, entry in parsed.items():
                        ledger_upsert(mid, "catboost", entry)
                except Exception:
                    logger.warning(
                        "Failed to upsert catboost into prediction ledger",
                        exc_info=True,
                    )

            return {
                "fetched_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
                "matches": parsed,
            }

        except requests.exceptions.Timeout:
            logger.warning(
                "CatBoost predictions request timed out (attempt %d/3)",
                attempt + 1,
            )
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue

        except requests.exceptions.ConnectionError:
            logger.warning(
                "CatBoost predictions connection error (attempt %d/3)",
                attempt + 1,
            )
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue

        except requests.exceptions.HTTPError:
            logger.warning(
                "CatBoost predictions HTTP error (attempt %d/3)",
                attempt + 1,
            )
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue

        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            logger.warning("CatBoost predictions malformed JSON, returning empty matches")
            return {
                "fetched_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
                "matches": {},
            }

    # All retries exhausted
    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
        "matches": {},
    }
