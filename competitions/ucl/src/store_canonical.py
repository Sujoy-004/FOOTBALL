"""One-time, provenance-preserving canonicalization of an existing season store.

Background
----------
2026/27 fixture stores written before multi-season ingestion gained canonical
fixture identity may contain TWO rows for the same real matchup: a stable
``gen-*`` row drawn from the UCL schedule snapshot (family spellings like
``PSV Eindhoven``, ``Inter Milan``, ``Atlético Madrid``) and a numeric provider
row using a legacy short spelling (``PSV``, ``Inter``, ``Atletico Madrid``).

This module merges such duplicates IN PLACE so each matchup has exactly ONE
canonical fixture identity, and re-keys any attached results onto the canonical
row — without touching scores, winners, or any official-result provenance, and
without inventing or promoting any simulated data.

Guarantees
----------
* Never deletes a fixture row unless it is the duplicate of another row for the
  SAME folded (home, away) pairing; rows are idempotent across re-runs.
* The authoritative row is the stable ``gen-*`` row when present, else the
  first row in store order.
* Only mutable fields are merged from duplicates (the dates/status are
  non-conflicting; nothing else is written onto the canonical row).
* Results are re-keyed through the id map (their exact scores and metadata are
  preserved verbatim) and their team names are canonicalized to the fixture row.
*** Do not change the ``LOCAL_HISTORICAL_SEASON`` (2025/26) store — run this
only on an explicitly requested non-historical season.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from football_core.fetcher import fold_pair_key
from competitions.ucl.src.seasons import (
    read_season_fixtures,
    read_season_results,
    write_season_fixtures,
    write_season_results,
)

logger = logging.getLogger(__name__)

#: Field precedence when merging duplicates: for each field the STRONGER value
#: (higher priority, or non-empty) is kept. Unlisted fields on the duplicate
#: row are ignored — the canonical row's identity/metadata is never rewritten.
_STATUS_PRIORITY = {"finished": 3, "timed": 2, "scheduled": 1}


def _alias_resolver(data_dir: str | Path) -> dict | None:
    """Build the team aliases lookup (aliases only) when team_aliases.json exists.

    Returns ``None`` when absent so callers fall back to accent-folding alone.
    """
    from football_core.fetcher import _build_alias_lookup

    aliases_path = Path(data_dir) / "team_aliases.json"
    if not aliases_path.exists():
        return None
    import json as _json

    try:
        aliases = _json.loads(aliases_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return _build_alias_lookup(aliases, bracket=[]) if isinstance(aliases, dict) else None


def _canonical_identity(row: dict, lookup: dict | None) -> tuple[str, str]:
    """(home, away) pair resolved to its canonical alias family, then folded.

    Resolving through the aliases collapses the SHORT-vs-FULL family
    (``Inter`` -> ``Inter Milan``, ``FC Bayern München`` -> ``Bayern Munich``)
    that accent-folding alone cannot, so every stored spelling of one real
    matchup lands on one identity key.
    """
    ta = row.get("team_a") or ""
    tb = row.get("team_b") or ""
    if lookup:
        ta = lookup.get(ta.strip().casefold()) or ta
        tb = lookup.get(tb.strip().casefold()) or tb
    return fold_pair_key(ta, tb)


def _stronger(a: Any, b: Any, priority: dict[str, int] | None = None) -> Any:
    """Return the stronger of two values: non-empty beats empty, else priority."""
    if a is None or a == "":
        return b
    if b is None or b == "":
        return a
    if priority is not None and a in priority and b in priority:
        return a if priority[a] >= priority[b] else b
    return a if a != b else a


def _merge_mutables(canonical: dict, duplicate: dict) -> bool:
    """Fold non-conflicting mutable fields from ``duplicate`` into ``canonical``.

    Returns True when anything changed. Identity (``match_id``, ``team_a``,
    ``team_b``) and any existing metadata on the canonical row are preserved.
    """
    changed = False
    mutable_fields = {
        "event_date": None,
        "status": _STATUS_PRIORITY,
        "stage": None,
        "official_matchday": None,
        "winner": None,
        "event_round": None,
    }
    for field, priority in mutable_fields.items():
        value = duplicate.get(field)
        if value is None or value == "":
            continue
        merged = _stronger(canonical.get(field), value, priority)
        if canonical.get(field) != merged:
            canonical[field] = merged
            changed = True
    return changed


def _authoritative_row(group: list[dict]) -> int:
    """Index of the authoritative row: the stable ``gen-*`` one, else the first."""
    for i, row in enumerate(group):
        mid = str(row.get("match_id") or "")
        if mid.startswith("gen-"):
            return i
    return 0


def canonicalize_season_store(
    data_dir: str | Path,
    season: str,
    dry_run: bool = False,
) -> dict:
    """Merge duplicate fixture identities and re-key results for a season store.

    When ``dry_run=True`` nothing is written; the returned report describes
    exactly what a real run would change (safe to run against a copy).

    Returns a report with: ``season``, ``duplicate_pairs``, ``rows_removed``,
    ``results_rekeyed``, ``results_orphans``, ``total_fixtures_before/after``,
    ``total_results_before/after``, ``id_map``, ``changed_any``.
    """
    fx_doc = read_season_fixtures(data_dir, season)
    res_doc = read_season_results(data_dir, season)

    report: dict = {
        "season": season,
        "duplicate_pairs": 0,
        "rows_removed": 0,
        "results_rekeyed": 0,
        "results_orphans": [],
        "total_fixtures_before": 0,
        "total_fixtures_after": 0,
        "total_results_before": 0,
        "total_results_after": 0,
        "id_map": {},
        "changed_any": False,
    }

    if not (isinstance(fx_doc, dict) and isinstance(fx_doc.get("fixtures"), list)):
        logger.warning("[canonicalize] %s: fixtures.json missing/corrupt — skipping", season)
        return report
    report["total_fixtures_before"] = len(fx_doc["fixtures"])

    # Group rows by ALIAS-RESOLVED canonical (home, away) pairing; detect
    # duplicates across spelling families (short-vs-full AND accent varieties).
    resolver = _alias_resolver(data_dir)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for fx in fx_doc["fixtures"]:
        if not isinstance(fx, dict):
            continue
        groups[_canonical_identity(fx, resolver)].append(fx)

    duplicate_pairs = {key: rows for key, rows in groups.items() if len(rows) > 1}
    report["duplicate_pairs"] = len(duplicate_pairs)

    id_map: dict[str, str] = {}
    for rows in duplicate_pairs.values():
        auth_idx = _authoritative_row(rows)
        canonical = rows[auth_idx]
        changed = False
        for i, row in enumerate(rows):
            if i == auth_idx:
                continue
            changed = _merge_mutables(canonical, row) or changed
            rid = row.get("match_id")
            if rid and rid != canonical.get("match_id"):
                id_map[str(rid)] = str(canonical.get("match_id") or "")
        report["changed_any"] = report["changed_any"] or changed

    # Keep exactly one row per folded pairing, in original store order, and
    # use the merged canonical row (gen-* preferred).
    by_id = {str(fx.get("match_id") or f"_idx{i}"): fx
             for i, fx in enumerate(fx_doc["fixtures"])}
    kept_ids: set[str] = set()
    new_rows: list[dict] = []
    for key, rows in groups.items():
        canonical = rows[_authoritative_row(rows)]
        cid = str(canonical.get("match_id") or "")
        if cid in kept_ids:
            continue
        kept_ids.add(cid)
        new_rows.append(canonical)
    fx_doc["fixtures"][:] = new_rows
    report["total_fixtures_after"] = len(new_rows)
    report["rows_removed"] = report["total_fixtures_before"] - len(new_rows)
    report["rows_removed"] = max(report["rows_removed"], 0)
    report["id_map"] = id_map

    # Re-key results onto the canonical fixture identity.
    matches = []
    if isinstance(res_doc, dict) and isinstance(res_doc.get("matches"), list):
        matches = res_doc["matches"]
    report["total_results_before"] = len(matches)

    remapped: list[dict] = []
    for res in matches:
        if not isinstance(res, dict):
            continue
        mid = str(res.get("match_id") or "")
        target_id = id_map.get(mid, mid)
        target: dict | None = by_id.get(target_id)
        if target is None:
            # Result row not attached to any fixture — keep it untouched.
            remapped.append(dict(res))
            report["results_orphans"].append(mid)
            continue
        new_res = dict(res)
        if target_id != mid:
            new_res["match_id"] = target_id
            report["results_rekeyed"] += 1
            report["changed_any"] = True
        canon_a = target.get("team_a")
        canon_b = target.get("team_b")
        if canon_a and new_res.get("team_a") != canon_a:
            new_res["team_a"] = canon_a
            report["changed_any"] = True
        if canon_b and new_res.get("team_b") != canon_b:
            new_res["team_b"] = canon_b
            report["changed_any"] = True
        remapped.append(new_res)

    fx_doc["fixtures"][:] = new_rows
    if isinstance(fx_doc.get("availability"), dict):
        fx_doc["availability"]["fixtures_count"] = len(new_rows)
        fx_doc["availability"]["results_count"] = len(remapped)
    report["total_results_after"] = len(remapped)
    if isinstance(res_doc, dict):
        res_doc["matches"] = remapped
        if isinstance(res_doc.get("availability"), dict):
            res_doc["availability"]["results_count"] = len(remapped)
            res_doc["availability"]["fixtures_count"] = len(new_rows)

    if dry_run:
        return report

    if report["changed_any"] or id_map or report["rows_removed"]:
        write_season_fixtures(data_dir, season, fx_doc)
    if isinstance(res_doc, dict) and report["changed_any"]:
        write_season_results(data_dir, season, res_doc)

    logger.info(
        "[canonicalize] %s: %d duplicate pair(s), %d rows removed, "
        "%d result(s) re-keyed, %d result orphan(s)",
        season, report["duplicate_pairs"], report["rows_removed"],
        report["results_rekeyed"], len(report["results_orphans"]),
    )
    return report