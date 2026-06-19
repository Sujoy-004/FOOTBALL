"""Match enrichment: extract stats and context from raw BSD event dicts.

Phase 17 — Enriched Match Context. Two extractors:
  - extract_stats(): P0 stat fields from live_stats (yellow/red cards,
    shots on target, possession)
  - extract_context(): venue name and referee name from top-level fields

Each returns None when BSD returned no data, or a partial dict per
the sparse-fields convention (D-07). Only P0 fields are extracted in
this phase — deferred fields are ignored.
"""

import logging

logger = logging.getLogger(__name__)

_STATS_FIELD_MAP: dict[str, str] = {
    "yellow_cards_home": "yellow_cards",
    "yellow_cards_away": "yellow_cards",
    "red_cards_home": "red_cards",
    "red_cards_away": "red_cards",
    "shots_on_target_home": "shots_on_target",
    "shots_on_target_away": "shots_on_target",
    "possession_home": "ball_possession",
    "possession_away": "ball_possession",
}

_CONTEXT_SOURCE_MAP: dict[str, tuple[str, str]] = {
    "venue": ("venue", "name"),
    "referee": ("referee", "name"),
}


def extract_stats(raw_event: dict) -> dict | None:
    """Extract P0 match statistics from a raw BSD event dict.

    Reads ``live_stats.home`` and ``live_stats.away``, resolves each
    internal field name through the FIELD_MAP, and returns a flat dict
    of internal → value. Returns ``None`` when BSD returned no stats
    (``live_stats`` is ``None`` or empty).

    Per D-07 (sparse-fields convention): only fields that actually
    resolved are included. If possession was returned but cards were
    not, the result contains ``possession_home`` / ``possession_away``
    but no card keys.
    """
    live_stats = raw_event.get("live_stats")
    if not live_stats or not isinstance(live_stats, dict):
        return None

    home = live_stats.get("home")
    away = live_stats.get("away")
    if not home or not away:
        return None

    result: dict = {}

    for internal_name, bsd_leaf in _STATS_FIELD_MAP.items():
        source = home if internal_name.endswith("_home") else away
        val = source.get(bsd_leaf)
        if val is not None:
            result[internal_name] = int(val) if isinstance(val, (int, float)) else val

    return result if result else None


def extract_context(raw_event: dict) -> dict | None:
    """Extract match context (venue, referee) from a raw BSD event dict.

    Reads top-level ``venue`` and ``referee`` dicts, extracts the
    ``name`` key from each. Returns ``None`` when neither source is
    available. Per D-07: returns partial dict if only one source
    resolved.
    """
    result: dict = {}

    for internal_name, (source_key, sub_key) in _CONTEXT_SOURCE_MAP.items():
        source = raw_event.get(source_key)
        if isinstance(source, dict):
            val = source.get(sub_key)
            if val is not None:
                result[internal_name] = str(val)

    return result if result else None
