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

# Fields that represent the factual match result — the only fields that may
# be updated by a provider correction.  Metadata (stats, context,
# ai_preview) is preserved from the original entry regardless of the
# provider response.
_WC_FACTUAL_FIELDS = ("home_score", "away_score", "winner", "is_draw", "completed_at")


def _build_match_entry(
    raw: dict,
    match_id: str,
    home_norm: str,
    away_norm: str,
    alias_lookup: dict[str, str] | None = None,
    *,
    knockout: bool = True,
) -> dict:
    """Build a canonical WC factual-store entry from a normalised provider match.

    ``knockout=True`` applies the full decider chain (extra time, penalties,
    explicit winner fields) that cannot occur in the group stage, where a
    full-time tie is always a draw.
    """
    home_score = raw.get("home_score", 0)
    away_score = raw.get("away_score", 0)

    winner = None
    is_draw = True

    if home_score > away_score:
        winner, is_draw = home_norm, False
    elif away_score > home_score:
        winner, is_draw = away_norm, False
    elif knockout:
        # Draw at full time — check extra time and penalties (knockout only).
        ets = raw.get("extra_time_score")
        if isinstance(ets, dict):
            et_h, et_a = ets.get("home"), ets.get("away")
            if et_h is not None and et_a is not None and et_h != et_a:
                winner = home_norm if et_h > et_a else away_norm
                is_draw = False
        if winner is None:
            ps = raw.get("penalty_shootout")
            if isinstance(ps, dict):
                ps_h, ps_a = ps.get("home"), ps.get("away")
                if ps_h is not None and ps_a is not None and ps_h != ps_a:
                    winner = home_norm if ps_h > ps_a else away_norm
                    is_draw = False
        if winner is None:
            pen_home = raw.get("penalty_home") or raw.get("home_penalty") or raw.get("pen_home")
            pen_away = raw.get("penalty_away") or raw.get("away_penalty") or raw.get("pen_away")
            if pen_home is not None and pen_away is not None and pen_home != pen_away:
                winner = home_norm if pen_home > pen_away else away_norm
                is_draw = False
        if winner is None:
            bsd_winner = raw.get("winner") or raw.get("result")
            if bsd_winner:
                w_name = None
                if isinstance(bsd_winner, str):
                    w_name = bsd_winner
                elif isinstance(bsd_winner, dict):
                    w_name = bsd_winner.get("name") or bsd_winner.get("full_name")
                if w_name:
                    w_norm = normalize_team(
                        w_name, alias_lookup or {}
                    ) or (alias_lookup or {}).get(w_name.strip().lower())
                    if w_norm == home_norm:
                        winner, is_draw = home_norm, False
                    elif w_norm == away_norm:
                        winner, is_draw = away_norm, False

    entry: dict = {
        "match_id": match_id,
        "team_a": home_norm,
        "team_b": away_norm,
        "winner": winner,
        "is_draw": is_draw,
        "home_score": home_score,
        "away_score": away_score,
        "completed_at": raw.get("event_date", ""),
    }

    stats = extract_stats(raw)
    if stats is not None:
        entry["stats"] = stats

    ctx = extract_context(raw)
    if ctx is not None:
        entry["context"] = ctx

    ai_preview = _extract_ai_preview(raw)
    if ai_preview is not None:
        entry["ai_preview"] = ai_preview

    return entry


def _should_apply_wc_update(existing: dict, proposed: dict) -> bool:
    """Decide whether proposed factual result can overwrite existing without downgrading.

    WC-specific variant of the UCL ``_should_apply_update`` guard.
    Provider data must never downgrade existing authoritative data:

    1. A decided winner must not be cleared to None.
    2. A match decided on penalties must not lose its pen-decided status.
    3. A completed match must not revert to an incomplete state.
    4. Scores must not regress (e.g. from a valid result to 0-0).

    Returns True when the update is safe to apply.
    """
    existing_winner = existing.get("winner")
    new_winner = proposed.get("winner")

    # 1. Never nullify an existing winner.
    if existing_winner and not new_winner:
        return False

    # 2. Never lose penalty-decided evidence.
    #    An existing match with a winner and equal full-time scores was
    #    decided on penalties/extra-time.  A new entry with equal scores
    #    and no winner would erase that decision.
    if (existing_winner
            and existing.get("home_score") == existing.get("away_score")
            and not new_winner):
        return False

    # 3. Never downgrade a completed match.
    if existing.get("completed_at") and not proposed.get("completed_at"):
        return False

    return True


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


def _maybe_merge_provider_metadata(existing: dict, entry: dict) -> None:
    """Additively enrich an updated entry with provider metadata it lacked.

    Only fills keys that are absent; never overwrites existing metadata.
    """
    for key in ("stats", "context", "ai_preview"):
        if key not in existing and key in entry:
            existing[key] = entry[key]


def partition_events_by_stage(raw_matches: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition provider events by stage using the normalised group_name field.

    Events with a non-empty group/stage identifier are group-stage events;
    events without one (None or empty string, e.g. FDO ``_map_group(None)``)
    are knockout events.  No new heuristic: this is exactly the field the
    group processor already uses to route its own events.

    Returns ``(group_events, ko_events)``.
    """
    group_events = [m for m in raw_matches if m.get("group_name")]
    ko_events = [m for m in raw_matches if not m.get("group_name")]
    return group_events, ko_events


def process_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    bracket: list[dict],
    aliases: dict[str, list[str]],
    played: dict[str, dict] | set[str],
    played_event_ids: set[str] | None = None,
    ingestion_stats: dict | None = None,
) -> list[dict]:
    from football_core.fetcher import (
        new_ingestion_stats, count_finished, note_unmatchable,
        note_no_target, summarize_ingestion,
    )
    istats = ingestion_stats if ingestion_stats is not None else new_ingestion_stats()
    alias_lookup = _build_alias_lookup(aliases, bracket)
    if isinstance(played, dict):
        played_store: dict[str, dict] = played
        legacy_ids: set[str] = set()
    else:
        # Legacy call style: a set mixing already-seen provider event ids and
        # already-recorded bracket ids.  Preserve the old "skip entirely"
        # semantics for every id in that set; no record is updated.
        played_store = {}
        legacy_ids = set(played or ())
    # NOTE: played_event_ids mutates the caller's set when one is supplied
    # (the historical contract of the group processor's played_bsd_event_ids),
    # matching legacy in-call event deduplication.
    played_event_ids_local = (
        played_event_ids if played_event_ids is not None else set()
    )
    results: list[dict] = []

    for match in raw_matches:
        if match.get("status") != "finished":
            continue
        count_finished(istats)

        match_id = str(match.get("id", ""))
        if match_id and (match_id in played_event_ids_local or match_id in legacy_ids):
            continue
        played_event_ids_local.add(match_id)

        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")

        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            note_unmatchable(istats, logger, home_name, away_name,
                             (match.get("home_score"), match.get("away_score")))
            continue

        istats["normalized"] += 1

        bracket_id = find_bracket_match(home_norm, away_norm, bracket)
        if bracket_id is None:
            note_no_target(istats, logger, home_norm, away_norm)
            continue
        if bracket_id in legacy_ids:
            continue

        entry = _build_match_entry(
            match, bracket_id, home_norm, away_norm, alias_lookup, knockout=True
        )

        if bracket_id in played_store:
            # Existing factual result: apply safe correction policy.
            existing = played_store[bracket_id]
            if all(existing.get(f) == entry[f] for f in _WC_FACTUAL_FIELDS):
                # Exactly equivalent result — true no-op.  New provider
                # metadata (stats, context, ai_preview) is NOT mixed in.
                continue
            if not _should_apply_wc_update(existing, entry):
                logger.warning(
                    "RESULT UPDATE REJECTED (would downgrade): %s %s %d-%d -> %s %d-%d",
                    bracket_id, existing.get("winner"),
                    existing.get("home_score"), existing.get("away_score"),
                    entry["winner"], entry["home_score"], entry["away_score"],
                )
                continue
            logger.warning(
                "RESULT UPDATE: %s %d-%d -> %d-%d",
                bracket_id, existing.get("home_score"), existing.get("away_score"),
                entry["home_score"], entry["away_score"],
            )
            for field in _WC_FACTUAL_FIELDS:
                existing[field] = entry[field]
            _maybe_merge_provider_metadata(existing, entry)
            continue

        # New result.
        results.append(entry)
        istats["ingested"] += 1

    summarize_ingestion(istats, logger, "knockout")
    return results


def process_group_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    groups: dict,
    aliases: dict[str, list[str]],
    played_groups: dict[str, dict] | set[str],
    played_bsd_event_ids: set[str] | None = None,
    ingestion_stats: dict | None = None,
) -> list[dict]:
    from football_core.fetcher import (
        new_ingestion_stats, count_finished, note_unmatchable,
        note_no_target, summarize_ingestion,
    )
    istats = ingestion_stats if ingestion_stats is not None else new_ingestion_stats()
    alias_lookup = _build_alias_lookup(aliases, [])
    groups_data = groups.get("groups", groups)
    for group_data in groups_data.values():
        for team in group_data.get("teams", []):
            alias_lookup[team.strip().lower()] = team

    if isinstance(played_groups, dict):
        played_store: dict[str, dict] = played_groups
        legacy_ids: set[str] = set()
    else:
        # Legacy call style: a set of already-recorded group fixture ids.
        # Preserve the old "skip entirely" semantics for those ids.
        played_store = {}
        legacy_ids = set(played_groups or ())
    # NOTE: played_bsd_event_ids mutates the caller's set when one is
    # supplied, matching the historical in-call/cross-call event
    # deduplication contract relied on by callers.
    played_bsd_event_ids = (
        played_bsd_event_ids if played_bsd_event_ids is not None else set()
    )

    results: list[dict] = []

    for match in raw_matches:
        if match.get("status") != "finished":
            continue
        count_finished(istats)

        group_name = match.get("group_name")
        if not group_name:
            # Not a group-stage event for this processor (e.g. knockout event).
            # Also catches empty-string group_name from FDO _map_group(None).
            istats["skipped_no_target"] += 1
            continue

        bsd_id = str(match.get("id", ""))
        if bsd_id in played_bsd_event_ids:
            continue
        played_bsd_event_ids.add(bsd_id)

        group_letter = _extract_group_letter(group_name)
        if group_letter is None:
            note_no_target(istats, logger, match.get("home_team", ""), match.get("away_team", ""))
            logger.warning(
                "RESULT INGESTION SKIP (unparseable group_name %r): %r vs %r",
                group_name, match.get("home_team"), match.get("away_team"),
            )
            continue

        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            note_unmatchable(istats, logger, home_name, away_name,
                             (match.get("home_score"), match.get("away_score")))
            continue

        istats["normalized"] += 1

        round_number = match.get("round_number", 0)
        match_id = find_group_match(
            home_norm, away_norm, group_letter, round_number, groups
        )
        if match_id is None:
            note_no_target(istats, logger, home_norm, away_norm)
            continue

        if match_id in legacy_ids:
            continue

        entry = _build_match_entry(
            match, match_id, home_norm, away_norm, alias_lookup, knockout=False
        )

        if match_id in played_store:
            # Existing factual result: apply safe correction policy.
            existing = played_store[match_id]
            if all(existing.get(f) == entry[f] for f in _WC_FACTUAL_FIELDS):
                # Exactly equivalent result — true no-op.  New provider
                # metadata (stats, context, ai_preview) is NOT mixed in.
                continue
            if not _should_apply_wc_update(existing, entry):
                logger.warning(
                    "RESULT UPDATE REJECTED (would downgrade): %s %s %d-%d -> %s %d-%d",
                    match_id, existing.get("winner"),
                    existing.get("home_score"), existing.get("away_score"),
                    entry["winner"], entry["home_score"], entry["away_score"],
                )
                continue
            logger.warning(
                "RESULT UPDATE: %s %d-%d -> %d-%d",
                match_id, existing.get("home_score"), existing.get("away_score"),
                entry["home_score"], entry["away_score"],
            )
            for field in _WC_FACTUAL_FIELDS:
                existing[field] = entry[field]
            _maybe_merge_provider_metadata(existing, entry)
            continue

        results.append(entry)
        istats["ingested"] += 1

    summarize_ingestion(istats, logger, "group stage")
    return results
