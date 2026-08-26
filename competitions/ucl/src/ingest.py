"""Authoritative UCL event ingestion — league ledger + knockout store v2.

This module is the SINGLE writer for the two stores inside the UCL data dir:

- ``results.json`` — league-phase ledger, upserted by fixture ``match_id``
  (``fixtures.json`` remains the schedule authority; rows are never invented
  for pairs that have no fixture).
- ``knockout_results.json`` — knockout store, schema version **2**, written
  atomically (temp file + ``os.replace``), utf-8, ``indent=2``,
  ``ensure_ascii=False``.

Store schema v2 (the only format ever written)::

    {
      "schema": 2,
      "matches": {
        "playoff":  [<two-legged TIE> x8],
        "rounds":   {"R16": [TIE x8], "QF": [TIE x4], "SF": [TIE x2]},
        "final":    [<single-match FINAL_MATCH> x1],
        "champion": "PSG" | null
      },
      "meta": {"provider": str|null, "backfilled_from": str|null,
               "updated_at": iso8601|null}
    }

The FINAL is a single match, not a two-legged tie, so it lives OUTSIDE
``rounds``. Legacy v1 payloads (FINAL nested under ``rounds``, aggregate
fields named ``score_a``/``score_b``, no ``schema`` key) are accepted and
normalized to v2 IN MEMORY on read (:func:`upgrade_on_read`); v1 is never
written back.

Skeleton derivation (deterministic, idempotent): when the store is missing,
unreadable or empty, a bracket skeleton is derived from

1. the final Swiss standings computed from the league ledger — playoff ties
   cross standings positions 9..24 with the ``playoff_pairings.json``
   template order. The seeded team (positions 9-16) hosts leg 2 and is
   stored as ``team_b``; the unseeded team (positions 17-24) hosts leg 1 and
   is stored as ``team_a``. ``slot_sources`` records the template's
   ``position_a``/``position_b`` values;
2. ``bracket_rules.json`` — R16 slots get ``team_a`` = seed by ``home_seed``
   from the top-8 zone, ``team_b`` = null until the corresponding playoff
   winner is known (``slot_sources`` records ``home_seed`` /
   ``away_playoff_tie``); QF/SF/FINAL are created with ``source_matches``
   and null teams.

After updates, downstream null slots are filled deterministically from
upstream winners (playoff winners -> R16 ``team_b`` via
``slot_sources.away_playoff_tie``; R16 winners -> QF teams via
``source_matches`` order; and so on). The champion is written once the FINAL
has a winner.

Provenance rule (honesty contract):

- An entry whose decisive outcome data (legs, aggregates recomputed from
  legs, winner) all originates from the current provider feed becomes
  ``"official"``.
- An entry carrying backfilled/historical aggregate-only data stays
  ``"manual"`` until live legs fully replace that history; partial
  enrichment (tie still undecided) does NOT flip provenance.
- Unplayed skeleton slots inherit the origin of their derivation:
  standings/draw templates computed from official feed results ->
  ``"official"``; offline backfilled history -> ``"manual"``.

Extra time / penalty shootouts are captured ONLY when the incoming event
carries explicit evidence. Recognized optional event fields:

- ``duration``: ``"EXTRA_TIME"`` or ``"PENALTY_SHOOTOUT"`` marks ET played;
- ``et_home`` / ``et_away``: extra-time goals for this leg's home/away side;
- ``shootout``: ``{"home": int, "away": int}`` shootout score for this leg
  (optionally plus ``"winner"``), or flat ``penalty_home``/``penalty_away``
  ints.

Leg scores remain regulation-time scores (football-data.org's regularTime
substitution is preserved upstream); ET goals are stored separately at tie
level (``et_played``/``et_a``/``et_b``). When the source lacks shootout
numbers, the flags stay false — nothing is ever invented.

Idempotency: ingesting the same event list twice produces byte-identical
stores on the second run (no file rewrite, no ``meta.updated_at`` bump).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_core.domain import is_semantically_empty
from football_core.fetcher import (
    IngestReport,
    count_finished,
    new_ingestion_stats,
    note_no_target,
    note_unmatchable,
    summarize_ingestion,
)
from competitions.ucl.src.seasons import (
    LOCAL_HISTORICAL_SEASON,
    derive_fixture_id,
    empty_fixtures_document,
    empty_results_document,
    normalize_season_token,
    read_season_fixtures,
    read_season_results,
    season_dir,
    write_season_fixtures,
    write_season_results,
)

logger = logging.getLogger(__name__)

# API stage token -> internal round key (UCL-specific vocabulary).
KO_STAGE_MAP = {
    "PLAYOFFS": "playoff",
    "LAST_16": "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS": "SF",
    "FINAL": "FINAL",
}

_ROUND_ORDER = ("playoff", "R16", "QF", "SF", "FINAL")

# Optional per-event fields forwarded into knockout leg persistence.
EVENT_PASSTHROUGH_FIELDS = (
    "event_date",
    "duration",
    "extra_time",
    "et_home",
    "et_away",
    "shootout",
    "penalty_home",
    "penalty_away",
)

BACKFILL_SOURCE_TAG = "bootstrap/2025_26_knockout_results.json (git 7cbc0f6)"


# ── atomic JSON persistence ──────────────────────────────────────────────────


def _atomic_write_json(data: dict | list, path: Path) -> None:
    """Write *data* to *path* atomically (utf-8, indent=2, ensure_ascii=False)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── store schema v2 ──────────────────────────────────────────────────────────


def _empty_v2_document() -> dict:
    return {
        "schema": 2,
        "matches": {
            "playoff": [],
            "rounds": {"R16": [], "QF": [], "SF": []},
            "final": [],
            "champion": None,
        },
        "meta": {"provider": None, "backfilled_from": None, "updated_at": None},
    }


def _normalize_v1_tie(entry: dict, round_: str, index: int) -> dict:
    """Convert one legacy v1 two-legged entry into a v2 TIE shape."""
    mid = entry.get("match_id") or (
        f"playoff_t{entry['tie_num']}" if round_ == "playoff" and entry.get("tie_num")
        else f"{round_.lower()}_{index + 1:02d}"
    )
    winner = entry.get("winner") or None
    out = {
        "match_id": mid,
        "round": round_,
        "quarter": entry.get("quarter"),
        "team_a": entry.get("team_a"),
        "team_b": entry.get("team_b"),
        "slot_sources": entry.get("slot_sources"),
        "source_matches": entry.get("source_matches"),
        "legs": entry.get("legs"),
        "aggregate_a": entry.get("aggregate_a", entry.get("score_a")),
        "aggregate_b": entry.get("aggregate_b", entry.get("score_b")),
        "et_played": bool(entry.get("et_played", False)),
        "et_a": int(entry.get("et_a", 0) or 0),
        "et_b": int(entry.get("et_b", 0) or 0),
        "penalties_played": bool(entry.get("penalties_played", False)),
        "penalty_a": int(entry.get("penalty_a", 0) or 0),
        "penalty_b": int(entry.get("penalty_b", 0) or 0),
        "penalty_winner": entry.get("penalty_winner"),
        "winner": winner,
        "status": "played" if winner else "scheduled",
        # v1 predates provenance tracking; such rows were hand-recorded.
        "provenance": entry.get("provenance") or "manual",
    }
    if round_ == "playoff":
        out["tie_num"] = entry.get("tie_num")
    return out


def _normalize_v1_final(entry: dict) -> dict:
    """Convert one legacy v1 FINAL entry into the v2 single-match variant."""
    pens = entry.get("penalties") or {}
    penalties_played = bool(pens or entry.get("penalties_played"))
    home = entry.get("score_a", entry.get("home_score"))
    away = entry.get("score_b", entry.get("away_score"))
    winner = entry.get("winner") or None
    return {
        "match_id": entry.get("match_id") or "final_01",
        "round": "FINAL",
        "team_a": entry.get("team_a"),
        "team_b": entry.get("team_b"),
        "score": {"home": home, "away": away} if home is not None and away is not None else None,
        "et_played": bool(entry.get("et_played", False)),
        "et_a": int(entry.get("et_a", 0) or 0),
        "et_b": int(entry.get("et_b", 0) or 0),
        "penalties_played": penalties_played,
        "penalty_winner": pens.get("winner") or entry.get("penalty_winner"),
        "penalty_score": pens.get("score") or entry.get("penalty_score"),
        "winner": winner,
        "status": (
            "played_pens" if penalties_played and winner
            else ("played" if winner else "scheduled")
        ),
        "provenance": entry.get("provenance") or "manual",
        "source_matches": entry.get("source_matches"),
    }


def upgrade_on_read(data: Any) -> dict:
    """Normalize any accepted store payload (missing/v1/v2) to a v2 document."""
    doc = _empty_v2_document()
    if not isinstance(data, dict):
        return doc
    matches = data.get("matches")
    if not isinstance(matches, dict):
        return doc

    rounds_src = dict(matches.get("rounds") or {})
    final_src = matches.get("final")
    if final_src is None:
        # v1 location of the single final match.
        final_src = rounds_src.pop("FINAL", []) or []

    if data.get("schema") == 2:
        # Already v2: preserve entries verbatim, only repair container shape.
        doc["matches"]["playoff"] = list(matches.get("playoff") or [])
        for rnd in ("R16", "QF", "SF"):
            doc["matches"]["rounds"][rnd] = list(rounds_src.get(rnd) or [])
        doc["matches"]["final"] = list(final_src)
    else:
        doc["matches"]["playoff"] = [
            _normalize_v1_tie(e, "playoff", i) for i, e in enumerate(matches.get("playoff") or [])
        ]
        for rnd in ("R16", "QF", "SF"):
            doc["matches"]["rounds"][rnd] = [
                _normalize_v1_tie(e, rnd, i) for i, e in enumerate(rounds_src.get(rnd) or [])
            ]
        doc["matches"]["final"] = [_normalize_v1_final(e) for e in final_src]

    doc["matches"]["champion"] = matches.get("champion")

    meta_src = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    doc["meta"] = {key: meta_src.get(key) for key in ("provider", "backfilled_from", "updated_at")}
    doc["schema"] = 2
    return doc


def load_knockout_store(data_dir: str | Path) -> dict:
    """Load knockout_results.json as a normalized v2 document (never raises)."""
    path = Path(data_dir) / "knockout_results.json"
    if not path.exists():
        return _empty_v2_document()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning(
            "[UCL] knockout_results.json unreadable (%s) — starting from empty store", exc,
        )
        return _empty_v2_document()
    if is_semantically_empty(data):
        return _empty_v2_document()
    return upgrade_on_read(data)


def write_knockout_store(data_dir: str | Path, document: dict) -> str:
    """Persist a v2 document atomically; returns the written path."""
    path = Path(data_dir) / "knockout_results.json"
    _atomic_write_json(document, path)
    return str(path)


def _store_has_entries(matches: dict) -> bool:
    if matches.get("playoff"):
        return True
    if any(matches.get("rounds", {}).get(r) for r in ("R16", "QF", "SF")):
        return True
    return bool(matches.get("final"))


# ── skeleton derivation ──────────────────────────────────────────────────────


def _compute_standings(rows: list[dict]) -> list[dict]:
    """Final Swiss standings from the league ledger (canonical UCL brain)."""
    try:
        from competitions.ucl.src.pipeline import compute_deterministic_standings
        return compute_deterministic_standings(rows or [])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "[UCL] standings computation failed (%s) — playoff skeleton slots stay unresolved", exc,
        )
        return []


def _build_skeleton(matches: dict, standings: list[dict], pairings: dict, rules: dict) -> None:
    """Populate an empty store with the deterministic bracket skeleton."""
    pos_team: dict[int, str] = {}
    for s in standings:
        try:
            pos_team[int(s.get("position"))] = s.get("team")
        except (TypeError, ValueError):
            continue

    for p in sorted(pairings.get("pairings", []), key=lambda x: x.get("tie", 0)):
        tie_num = int(p["tie"])
        seeded_pos = p.get("position_a")      # 9..16 — hosts leg 2 -> team_b
        unseeded_pos = p.get("position_b")    # 17..24 — hosts leg 1 -> team_a
        matches["playoff"].append({
            "match_id": f"playoff_t{tie_num}",
            "tie_num": tie_num,
            "round": "playoff",
            "quarter": None,
            "team_a": pos_team.get(unseeded_pos),
            "team_b": pos_team.get(seeded_pos),
            "slot_sources": {"position_a": seeded_pos, "position_b": unseeded_pos},
            "source_matches": None,
            "legs": None,
            "aggregate_a": None,
            "aggregate_b": None,
            "et_played": False,
            "et_a": 0,
            "et_b": 0,
            "penalties_played": False,
            "penalty_a": 0,
            "penalty_b": 0,
            "penalty_winner": None,
            "winner": None,
            "status": "scheduled",
            "provenance": "official",
        })

    for m in rules.get("matches", []):
        rnd = m.get("round")
        if rnd == "FINAL":
            matches["final"].append({
                "match_id": m["match_id"],
                "round": "FINAL",
                "team_a": None,
                "team_b": None,
                "score": None,
                "et_played": False,
                "et_a": 0,
                "et_b": 0,
                "penalties_played": False,
                "penalty_winner": None,
                "penalty_score": None,
                "winner": None,
                "status": "scheduled",
                "provenance": "official",
                "source_matches": m.get("source_matches"),
            })
            continue
        base = {
            "match_id": m["match_id"],
            "round": rnd,
            "quarter": m.get("quarter"),
            "slot_sources": None,
            "source_matches": m.get("source_matches"),
            "legs": None,
            "aggregate_a": None,
            "aggregate_b": None,
            "et_played": False,
            "et_a": 0,
            "et_b": 0,
            "penalties_played": False,
            "penalty_a": 0,
            "penalty_b": 0,
            "penalty_winner": None,
            "winner": None,
            "status": "scheduled",
            "provenance": "official",
        }
        if rnd == "R16":
            base["team_a"] = pos_team.get(m.get("home_seed"))
            base["team_b"] = None
            base["source_matches"] = None
            base["slot_sources"] = {
                "home_seed": m.get("home_seed"),
                "away_playoff_tie": m.get("away_playoff_tie"),
            }
        else:  # QF / SF
            base["team_a"] = None
            base["team_b"] = None
        matches["rounds"].setdefault(rnd, []).append(base)


# ── slot cascade + champion ──────────────────────────────────────────────────


def _winners_by_id(entries: list[dict]) -> dict[str, str]:
    return {
        e["match_id"]: e["winner"]
        for e in entries
        if e.get("match_id") and e.get("winner")
    }


def _cascade_slots(matches: dict) -> int:
    """Fill downstream null slots from upstream winners. Returns fill count."""
    filled = 0

    playoff_winners: dict[int, str] = {}
    for tie in matches.get("playoff", []):
        tie_num, winner = tie.get("tie_num"), tie.get("winner")
        if tie_num is not None and winner:
            playoff_winners[int(tie_num)] = winner

    r16_entries = matches["rounds"].get("R16", [])
    for entry in r16_entries:
        src = entry.get("slot_sources") or {}
        apt = src.get("away_playoff_tie")
        if entry.get("team_b") is None and apt is not None and int(apt) in playoff_winners:
            entry["team_b"] = playoff_winners[int(apt)]
            filled += 1

    def _fill_from_sources(entries: list[dict], winners: dict[str, str]) -> None:
        nonlocal filled
        for entry in entries:
            sources = entry.get("source_matches") or []
            if len(sources) >= 1 and entry.get("team_a") is None and sources[0] in winners:
                entry["team_a"] = winners[sources[0]]
                filled += 1
            if len(sources) >= 2 and entry.get("team_b") is None and sources[1] in winners:
                entry["team_b"] = winners[sources[1]]
                filled += 1

    rounds = matches["rounds"]
    r16_winners = _winners_by_id(r16_entries)
    qf_entries = rounds.get("QF", [])
    _fill_from_sources(qf_entries, r16_winners)
    sf_entries = rounds.get("SF", [])
    _fill_from_sources(sf_entries, _winners_by_id(qf_entries))
    _fill_from_sources(matches.get("final", []), _winners_by_id(sf_entries))
    return filled


def _update_champion(matches: dict) -> bool:
    finals = matches.get("final") or []
    if finals and finals[0].get("winner"):
        if matches.get("champion") != finals[0]["winner"]:
            matches["champion"] = finals[0]["winner"]
            return True
    return False


# ── leg persistence ──────────────────────────────────────────────────────────


def _order_legs(legs_raw: list[dict]) -> list[dict]:
    """Deterministic ordering (by event_date, then arrival); dedupe repeats."""
    seen: set[tuple] = set()
    ordered: list[dict] = []
    for leg in sorted(legs_raw, key=lambda l: l.get("event_date") or ""):
        key = (
            leg.get("event_date") or "", leg["home"], leg["away"],
            leg["home_score"], leg["away_score"],
        )
        if key in seen:
            continue
        seen.add(key)
        ordered.append(leg)
    return ordered


def _capture_et_pens(leg: dict, home: str, away: str, et_totals: dict, pen_totals: dict) -> tuple[bool, bool, str | None]:
    """Extract ET/pens evidence from one leg. Returns (et_played, pens_evidence, pen_winner)."""
    duration = (leg.get("duration") or "").upper()
    et_played = duration in ("EXTRA_TIME", "PENALTY_SHOOTOUT") or bool(leg.get("extra_time"))
    et_home, et_away = leg.get("et_home"), leg.get("et_away")
    if isinstance(et_home, int):
        et_totals[home] += et_home
    if isinstance(et_away, int):
        et_totals[away] += et_away

    sho = leg.get("shootout")
    pens_home = pens_away = None
    sho_winner = None
    if isinstance(sho, dict):
        pens_home, pens_away = sho.get("home"), sho.get("away")
        sho_winner = sho.get("winner")
    if pens_home is None:
        pens_home = leg.get("penalty_home")
    if pens_away is None:
        pens_away = leg.get("penalty_away")

    pen_winner = None
    pens_evidence = False
    if isinstance(pens_home, int) and isinstance(pens_away, int):
        pens_evidence = True
        pen_totals[home] += pens_home
        pen_totals[away] += pens_away
        if pens_home != pens_away:
            pen_winner = home if pens_home > pens_away else away
        elif sho_winner:
            pen_winner = sho_winner
    elif sho_winner:
        # Explicit shootout winner without numbers: capture the decision,
        # never invent the missing score.
        pens_evidence = True
        pen_winner = sho_winner
    return et_played, pens_evidence, pen_winner


def _apply_legs(entry: dict, legs_raw: list[dict]) -> bool:
    """Persist each leg into *entry* and recompute everything derivable.

    Returns True when the stored entry changed.
    """
    team_a, team_b = entry.get("team_a"), entry.get("team_b")
    if not team_a or not team_b:
        return False

    legs: list[dict] = []
    et_totals = {team_a: 0, team_b: 0}
    pen_totals = {team_a: 0, team_b: 0}
    et_played = False
    pens_evidence = False
    penalty_winner = None

    for i, leg in enumerate(_order_legs(legs_raw), start=1):
        legs.append({
            "leg": i,
            "home": leg["home"],
            "away": leg["away"],
            "home_score": int(leg["home_score"]),
            "away_score": int(leg["away_score"]),
        })
        leg_et, leg_pens, leg_pen_winner = _capture_et_pens(
            leg, leg["home"], leg["away"], et_totals, pen_totals,
        )
        et_played = et_played or leg_et
        if leg_pens:
            pens_evidence = True
            penalty_winner = leg_pen_winner or penalty_winner

    aggregate_a = sum(
        l["home_score"] if l["home"] == team_a else l["away_score"] for l in legs
    )
    aggregate_b = sum(
        l["away_score"] if l["home"] == team_a else l["home_score"] for l in legs
    )

    if aggregate_a > aggregate_b:
        winner = team_a
    elif aggregate_b > aggregate_a:
        winner = team_b
    elif et_played and et_totals[team_a] != et_totals[team_b]:
        winner = team_a if et_totals[team_a] > et_totals[team_b] else team_b
    elif pens_evidence and penalty_winner:
        winner = penalty_winner
    else:
        winner = None

    status = (
        "played_pens" if pens_evidence and winner
        else ("played" if winner else "scheduled")
    )
    prev_prov = entry.get("provenance")
    provenance = "manual" if (prev_prov == "manual" and winner is None) else "official"

    new_state = {
        "legs": legs,
        "aggregate_a": aggregate_a,
        "aggregate_b": aggregate_b,
        "et_played": et_played,
        "et_a": et_totals[team_a],
        "et_b": et_totals[team_b],
        "penalties_played": pens_evidence,
        "penalty_a": pen_totals[team_a],
        "penalty_b": pen_totals[team_b],
        "penalty_winner": penalty_winner if pens_evidence else None,
        "winner": winner,
        "status": status,
        "provenance": provenance,
    }
    changed = False
    for key, value in new_state.items():
        if entry.get(key) != value:
            entry[key] = value
            changed = True
    return changed


def _apply_final(entry: dict, events_raw: list[dict]) -> bool:
    """Apply the single-match FINAL event; returns True when changed."""
    team_a, team_b = entry.get("team_a"), entry.get("team_b")
    if not team_a or not team_b:
        return False
    ordered = _order_legs(events_raw)
    if not ordered:
        return False
    ev = ordered[-1]

    home, away = ev["home"], ev["away"]
    home_is_a = home == team_a
    score_home = int(ev["home_score"]) if home_is_a else int(ev["away_score"])
    score_away = int(ev["away_score"]) if home_is_a else int(ev["home_score"])

    et_totals = {team_a: 0, team_b: 0}
    pen_totals = {team_a: 0, team_b: 0}
    et_played, pens_evidence, penalty_winner = _capture_et_pens(
        ev, home, away, et_totals, pen_totals,
    )

    if score_home > score_away:
        winner = team_a
    elif score_away > score_home:
        winner = team_b
    elif et_played and et_totals[team_a] != et_totals[team_b]:
        winner = team_a if et_totals[team_a] > et_totals[team_b] else team_b
    elif pens_evidence and penalty_winner:
        winner = penalty_winner
    else:
        winner = None

    status = (
        "played_pens" if pens_evidence and winner
        else ("played" if winner else "scheduled")
    )
    prev_prov = entry.get("provenance")
    provenance = "manual" if (prev_prov == "manual" and winner is None) else "official"

    new_state = {
        "score": {"home": score_home, "away": score_away},
        "et_played": et_played,
        "et_a": et_totals[team_a],
        "et_b": et_totals[team_b],
        "penalties_played": pens_evidence,
        "penalty_winner": penalty_winner if pens_evidence else None,
        "penalty_score": (
            f"{pen_totals[team_a]}-{pen_totals[team_b]}" if pens_evidence
            else entry.get("penalty_score")
        ),
        "winner": winner,
        "status": status,
        "provenance": provenance,
    }
    changed = False
    for key, value in new_state.items():
        if entry.get(key) != value:
            entry[key] = value
            changed = True
    return changed


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning("[UCL] %s unreadable (%s)", path.name, exc)
        return default


def _load_fixture_lookup(dp: Path) -> dict[tuple[str, str], str]:
    fixtures = _load_json(dp / "fixtures.json", {})
    lookup: dict[tuple[str, str], str] = {}
    for md in fixtures.get("schedule", {}).get("matchdays", []):
        for match in md:
            pair = (match["team_a"], match["team_b"])
            lookup[pair] = match["match_id"]
            lookup[(match["team_b"], match["team_a"])] = match["match_id"]
    return lookup


def _load_league_rows(dp: Path) -> list[dict]:
    data = _load_json(dp / "results.json", {"matches": []})
    if isinstance(data, dict):
        rows = data.get("matches", [])
    else:
        rows = data if isinstance(data, list) else []
    return [r for r in rows if isinstance(r, dict)]


# ── main entry point ─────────────────────────────────────────────────────────


def ingest_ucl_events(
    events: list[dict],
    data_dir: Path,
    provider_name: str,
    api_key_unused=None,
) -> IngestReport:
    """Ingest normalized UCL events into results.json + knockout_results.json.

    Parameters
    ----------
    events:
        Normalized flat event dicts as produced by the live path today:
        alias-resolved ``home_team``/``away_team``, integer
        ``home_score``/``away_score``, ``status == "finished"``, and a
        ``stage`` token (``LEAGUE_STAGE`` or one of :data:`KO_STAGE_MAP`
        keys). Optional ET/shootout evidence fields are documented in the
        module docstring.
    data_dir:
        UCL data directory holding fixtures.json / results.json /
        knockout_results.json / playoff_pairings.json / bracket_rules.json.
    provider_name:
        Label recorded in ``meta.provider`` and the report.
    api_key_unused:
        Accepted for signature compatibility; unused.

    Returns a truthful :class:`IngestReport` (stage checklist + finished
    counters + actually-written files).
    """
    dp = Path(data_dir) if isinstance(data_dir, str) else data_dir
    stats = new_ingestion_stats()
    report = IngestReport(provider=provider_name or "unknown", attempted=True, success=True, error=None)

    n_league_changed = 0
    n_playoff_changed = 0
    n_knockout_changed = 0
    written_files: list[str] = []

    # ── validate + partition incoming events ─────────────────────────
    # Counter semantics keep the strict truth-ingestion invariant:
    # received == normalized == ingested + skipped_unmatchable +
    # skipped_no_target. Every finished event passes through normalization
    # exactly once (counted in "normalized"); failures land in exactly one
    # skipped_* bucket; only successfully persisted events count as
    # "ingested".
    prepared: list[dict] = []
    for event in events or []:
        count_finished(stats)
        stats["normalized"] += 1
        home = (event.get("home_team") or "").strip()
        away = (event.get("away_team") or "").strip()
        stage = event.get("stage") or ""
        if not home or not away:
            note_unmatchable(stats, logger, event.get("home_team"), event.get("away_team"),
                             (event.get("home_score"), event.get("away_score")))
            continue
        if stage != "LEAGUE_STAGE" and stage not in KO_STAGE_MAP:
            stats["skipped_no_target"] += 1
            logger.warning(
                "RESULT INGESTION SKIP (unknown stage %r): %r vs %r", stage, home, away,
            )
            continue
        ev = dict(event)
        ev["home_team"], ev["away_team"], ev["stage"] = home, away, stage
        prepared.append(ev)

    # ── league phase: upsert keyed by fixture match_id ────────────────
    fixture_lookup = _load_fixture_lookup(dp)
    league_rows = _load_league_rows(dp)
    by_id = {m.get("match_id"): m for m in league_rows}
    results_dirty = False
    had_league_events = False
    for ev in prepared:
        if ev["stage"] != "LEAGUE_STAGE":
            continue
        had_league_events = True
        match_id = fixture_lookup.get((ev["home_team"], ev["away_team"]))
        if match_id is None:
            note_no_target(stats, logger, ev["home_team"], ev["away_team"])
            continue
        home_score = int(ev.get("home_score") or 0)
        away_score = int(ev.get("away_score") or 0)
        if match_id in by_id:
            entry = by_id[match_id]
            if entry.get("home_score") != home_score or entry.get("away_score") != away_score:
                entry["home_score"] = home_score
                entry["away_score"] = away_score
                results_dirty = True
                n_league_changed += 1
                logger.info("[UCL] League %s: %s %d-%d %s",
                            match_id, ev["home_team"], home_score, away_score, ev["away_team"])
        else:
            league_rows.append({
                "match_id": match_id,
                "team_a": ev["home_team"],
                "team_b": ev["away_team"],
                "home_score": home_score,
                "away_score": away_score,
            })
            by_id[match_id] = league_rows[-1]
            results_dirty = True
            n_league_changed += 1
            logger.info("[UCL] League %s: %s %d-%d %s",
                        match_id, ev["home_team"], home_score, away_score, ev["away_team"])
        stats["ingested"] += 1

    if results_dirty:
        results_path = dp / "results.json"
        _atomic_write_json({"matches": league_rows}, results_path)
        written_files.append(str(results_path))

    # ── group knockout events per round/pair ──────────────────────────
    ko_grouped: dict[str, dict[frozenset, list[dict]]] = {r: {} for r in _ROUND_ORDER}
    for ev in prepared:
        if ev["stage"] == "LEAGUE_STAGE":
            continue
        rnd = KO_STAGE_MAP[ev["stage"]]
        pair = frozenset((ev["home_team"], ev["away_team"]))
        payload = {
            "home": ev["home_team"], "away": ev["away_team"],
            "home_score": int(ev.get("home_score") or 0),
            "away_score": int(ev.get("away_score") or 0),
        }
        for field_name in EVENT_PASSTHROUGH_FIELDS:
            if field_name in ev:
                payload[field_name] = ev[field_name]
        ko_grouped[rnd].setdefault(pair, []).append(payload)

    # ── knockout store: load, skeleton, apply, cascade ────────────────
    document = load_knockout_store(dp)
    matches = document["matches"]

    skeleton_created = False
    if not _store_has_entries(matches):
        pairings = _load_json(dp / "playoff_pairings.json", {})
        rules = _load_json(dp / "bracket_rules.json", {})
        _build_skeleton(matches, _compute_standings(league_rows), pairings, rules)
        skeleton_created = True
        logger.info("[UCL] Derived knockout skeleton from standings + bracket rules")

    # Apply rounds in bracket order, re-running the slot cascade after each
    # round so events for later rounds in the SAME batch can match slots
    # freshly filled by earlier-round winners.
    slots_filled = 0
    for rnd in _ROUND_ORDER:
        entries = (
            matches["playoff"] if rnd == "playoff"
            else matches["final"] if rnd == "FINAL"
            else matches["rounds"].get(rnd, [])
        )
        for pair, legs_raw in ko_grouped[rnd].items():
            target = next(
                (e for e in entries
                 if e.get("team_a") and e.get("team_b")
                 and frozenset((e["team_a"], e["team_b"])) == pair),
                None,
            )
            if target is None:
                first, second = sorted(pair)
                note_no_target(stats, logger, first, second)
                continue
            changed = _apply_final(target, legs_raw) if rnd == "FINAL" else _apply_legs(target, legs_raw)
            stats["ingested"] += len(legs_raw)
            if changed:
                if rnd == "playoff":
                    n_playoff_changed += 1
                    logger.info("[UCL] Playoff %s vs %s updated", target.get("team_a"), target.get("team_b"))
                else:
                    n_knockout_changed += 1
                    logger.info("[UCL] %s %s vs %s updated", rnd, target.get("team_a"), target.get("team_b"))
        slots_filled += _cascade_slots(matches)

    champion_changed = _update_champion(matches)

    ko_dirty = skeleton_created or n_playoff_changed or n_knockout_changed or slots_filled or champion_changed
    if ko_dirty:
        document["schema"] = 2
        document["meta"]["provider"] = provider_name or None
        document["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        written_files.append(write_knockout_store(dp, document))

    # ── report ────────────────────────────────────────────────────────
    summarize_ingestion(stats, logger, "UCL")

    report.finished = {
        "received": stats["finished_received"],
        "normalized": stats["normalized"],
        "ingested": stats["ingested"],
        "skipped_unmatchable": stats["skipped_unmatchable"],
        "skipped_no_target": stats["skipped_no_target"],
    }
    report.last_success_at = datetime.now(timezone.utc).isoformat()
    report.written_files = written_files

    resolved = stats["normalized"] == stats["finished_received"]
    report.stages = [
        {
            "key": "teams",
            "label": "Team/stage resolution",
            "state": "pending" if not stats["finished_received"] else ("ok" if resolved else "error"),
            "count": stats["normalized"],
            "detail": f"{stats['normalized']}/{stats['finished_received']} finished events resolved"
                      + (f"; skipped={stats['skipped_unmatchable'] + stats['skipped_no_target']}" if not resolved else ""),
        },
        {
            "key": "league",
            "label": "League ledger upsert",
            "state": "ok" if had_league_events else "pending",
            "count": n_league_changed,
            "detail": f"{n_league_changed} league rows changed" if had_league_events else "no league-stage events",
        },
        {
            "key": "playoff",
            "label": "Knockout playoffs",
            "state": "ok" if matches["playoff"] else "pending",
            "count": n_playoff_changed,
            "detail": f"{len(matches['playoff'])} ties tracked; {n_playoff_changed} updated"
                      + ("; skeleton created" if skeleton_created else ""),
        },
        {
            "key": "knockout",
            "label": "Knockout R16-QF-SF-FINAL",
            "state": "ok" if (matches["rounds"].get("R16") or matches["final"]) else "pending",
            "count": n_knockout_changed,
            "detail": f"{n_knockout_changed} entries updated; {slots_filled} slots filled by cascade",
        },
        {
            "key": "champion",
            "label": "Champion resolution",
            "state": "ok" if matches.get("champion") else "pending",
            "count": 1 if champion_changed else 0,
            "detail": str(matches.get("champion")) if matches.get("champion") else "final undecided",
        },
    ]
    return report


# ── multi-season ingestion ────────────────────────────────────────────────────


def _normalize_season_for_store(season: Any) -> str | None:
    """Normalize a season token to the canonical display id (e.g., '2025/26').

    Returns None for empty/unparseable input.
    """
    return normalize_season_token(season)


def _is_historical_season(season: str | None) -> bool:
    """Check if the season is the local historical 2025/26 season."""
    return season == LOCAL_HISTORICAL_SEASON


def _make_fixture_lookup_from_doc(doc: dict) -> dict[tuple[str, str], str]:
    """Build (home, away) -> match_id lookup from a fixtures document."""
    lookup: dict[tuple[str, str], str] = {}
    for md in doc.get("fixtures", []):
        pair = (md["team_a"], md["team_b"])
        lookup[pair] = md["match_id"]
        lookup[(md["team_b"], md["team_a"])] = md["match_id"]
    return lookup


def _load_league_rows_from_doc(doc: dict) -> list[dict]:
    """Extract league rows from a results document."""
    return doc.get("matches", []) if isinstance(doc, dict) else []


def _atomic_write_json_local(data: Any, path: Path) -> None:
    """Write *data* to *path* atomically (utf-8, indent=2, ensure_ascii=False)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.stem + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _upsert_season_fixtures(
    data_dir: Path,
    season: str,
    scheduled_events: list[dict],
    provider_name: str,
) -> tuple[int, int, int]:
    """Create/update fixtures.json for a season from SCHEDULED/timed events.

    Returns (fixtures_added, fixtures_updated, total_fixtures).
    """
    from competitions.ucl.src.seasons import SEASON_STORE_SCHEMA

    sd = season_dir(data_dir, season)
    sd.mkdir(parents=True, exist_ok=True)
    fx_path = sd / "fixtures.json"

    # Load existing
    existing = None
    if fx_path.exists():
        try:
            existing = json.loads(fx_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            existing = None

    if existing is None or not isinstance(existing, dict):
        doc = empty_fixtures_document(season)
        doc["meta"] = {"provider": provider_name}
    else:
        doc = existing
        if doc.get("meta", {}).get("provider") is None:
            doc["meta"] = {"provider": provider_name}

    # Build lookup of existing fixtures by match_id
    existing_by_id = {fx.get("match_id"): fx for fx in doc.get("fixtures", [])}
    fixtures_added = 0
    fixtures_updated = 0

    for ev in scheduled_events:
        home = ev.get("home_team", "").strip()
        away = ev.get("away_team", "").strip()
        event_date = ev.get("event_date", "")
        match_id = ev.get("match_id", "").strip()

        if not home or not away:
            continue

        # Determine stable fixture id
        if match_id:
            fid = match_id
        else:
            fid = derive_fixture_id(home, away, event_date)

        # Check if fixture exists
        existing_fx = existing_by_id.get(fid)
        fx_entry = {
            "match_id": fid,
            "team_a": home,
            "team_b": away,
            "event_date": event_date,
            "stage": ev.get("stage", "LEAGUE_STAGE"),
            "status": ev.get("status", "scheduled"),
        }
        if existing_fx:
            # Update mutable fields
            changed = False
            for k, v in fx_entry.items():
                if existing_fx.get(k) != v:
                    existing_fx[k] = v
                    changed = True
            if changed:
                fixtures_updated += 1
        else:
            doc["fixtures"].append(fx_entry)
            existing_by_id[fid] = fx_entry
            fixtures_added += 1

    # Update availability counts
    doc["availability"] = {
        "fixtures_count": len(doc["fixtures"]),
        "results_count": doc["availability"].get("results_count", 0),
        "partial": True,  # providers never declare a catalog complete
    }

    _atomic_write_json_local(doc, fx_path)
    return fixtures_added, fixtures_updated, len(doc["fixtures"])


def _upsert_season_results(
    data_dir: Path,
    season: str,
    finished_events: list[dict],
    provider_name: str,
) -> tuple[int, int, int]:
    """Append finished events into season's results.json, attaching to known fixtures.

    Returns (results_added, results_updated, skipped_no_target).
    """
    sd = season_dir(data_dir, season)
    sd.mkdir(parents=True, exist_ok=True)
    res_path = sd / "results.json"

    # Load existing fixtures for this season (for match_id lookup)
    fx_doc = read_season_fixtures(data_dir, season)
    fx_lookup = _make_fixture_lookup_from_doc(fx_doc) if fx_doc else {}

    # Load existing results
    res_doc = read_season_results(data_dir, season)
    if res_doc is None or not isinstance(res_doc, dict):
        res_doc = empty_results_document(season)
        res_doc["meta"] = {"provider": provider_name}
    else:
        if res_doc.get("meta", {}).get("provider") is None:
            res_doc["meta"] = {"provider": provider_name}

    existing_matches = res_doc.get("matches", [])
    existing_by_id = {m.get("match_id"): m for m in existing_matches}

    results_added = 0
    results_updated = 0
    skipped_no_target = 0

    for ev in finished_events:
        home = ev.get("home_team", "").strip()
        away = ev.get("away_team", "").strip()
        if not home or not away:
            continue

        match_id = ev.get("match_id", "").strip()
        fid = None

        # Match by source id first
        if match_id and match_id in existing_by_id:
            fid = match_id
        elif match_id and match_id in fx_lookup:
            fid = match_id
        else:
            # Fallback: match by (home, away) pair within this season's fixtures
            fid = fx_lookup.get((home, away)) or fx_lookup.get((away, home))

        if fid is None:
            skipped_no_target += 1
            logger.warning(
                "[UCL] Season %s: finished event %s vs %s skipped_no_target (no fixture match)",
                season, home, away
            )
            continue

        home_score = int(ev.get("home_score") or 0)
        away_score = int(ev.get("away_score") or 0)

        entry = {
            "match_id": fid,
            "team_a": home,
            "team_b": away,
            "home_score": home_score,
            "away_score": away_score,
        }

        if fid in existing_by_id:
            ex = existing_by_id[fid]
            if ex.get("home_score") != home_score or ex.get("away_score") != away_score:
                ex["home_score"] = home_score
                ex["away_score"] = away_score
                results_updated += 1
        else:
            existing_matches.append(entry)
            existing_by_id[fid] = entry
            results_added += 1

    res_doc["matches"] = existing_matches
    _atomic_write_json_local(res_doc, res_path)
    return results_added, results_updated, skipped_no_target


def ingest_ucl_events_multi_season(
    events: list[dict],
    data_dir: str | Path,
    provider_name: str,
) -> dict:
    """Ingest UCL events grouped by season into per-season stores.

    - Events with season == "2025/26" (local historical) route to legacy
      data/results.json + data/knockout_results.json (EXACTLY current behavior).
    - Events with a DIFFERENT season route to data/seasons/<id>/
      (fixtures.json + results.json). Historical 2025/26 is NEVER written
      under data/seasons/.
    - Idempotent: double ingestion produces zero diffs.
    - Unknown-season events never mutate another season's files.

    Returns a summary dict with per-season stats and a combined report.
    """
    dp = Path(data_dir) if isinstance(data_dir, str) else data_dir
    stats = new_ingestion_stats()

    # Group events by normalized season
    by_season: dict[str | None, list[dict]] = {}
    for event in events or []:
        season_raw = event.get("season")
        season = _normalize_season_for_store(season_raw)
        by_season.setdefault(season, []).append(event)

    per_season_summary: dict[str, dict] = {}
    total_skipped_no_target = 0
    written_files: list[str] = []

    for season, season_events in by_season.items():
        # Partition into scheduled (status != finished) and finished
        scheduled: list[dict] = []
        finished: list[dict] = []
        for ev in season_events:
            count_finished(stats)
            stats["normalized"] += 1
            if ev.get("status") == "finished":
                finished.append(ev)
            else:
                scheduled.append(ev)

        if _is_historical_season(season):
            # Route to legacy ingest (EXACTLY current behavior)
            # We need to call the original ingest logic for the historical season
            from competitions.ucl.src.ingest import ingest_ucl_events as legacy_ingest
            report = legacy_ingest(season_events, dp, provider_name)
            per_season_summary[LOCAL_HISTORICAL_SEASON] = {
                "legacy": True,
                "report": report.to_dict(),
                "fixtures_count": 0,  # legacy uses root fixtures.json
                "results_count": report.finished["ingested"],
                "skipped_no_target": report.finished["skipped_no_target"],
            }
            written_files.extend(report.written_files)
        else:
            # New season: route to season store
            season_display = season or "unknown"
            # Create fixtures from:
            # - All scheduled/timed events (with or without match_id)
            # - Finished events that have a provider match_id
            # Finished events without match_id don't create fixtures;
            # they can only attach via (home,away) pair matching.
            fixture_source_events = [
                ev for ev in season_events
                if ev.get("status") != "finished" or ev.get("match_id")
            ]
            fx_added, fx_updated, fx_total = _upsert_season_fixtures(
                dp, season_display, fixture_source_events, provider_name
            )
            res_added, res_updated, skipped = _upsert_season_results(
                dp, season_display, finished, provider_name
            )
            total_skipped_no_target += skipped

            # Record written files
            fx_path = season_dir(dp, season_display) / "fixtures.json"
            res_path = season_dir(dp, season_display) / "results.json"
            if fx_added or fx_updated:
                written_files.append(str(fx_path))
            if res_added or res_updated:
                written_files.append(str(res_path))

            per_season_summary[season_display] = {
                "legacy": False,
                "fixtures_added": fx_added,
                "fixtures_updated": fx_updated,
                "fixtures_total": fx_total,
                "results_added": res_added,
                "results_updated": res_updated,
                "skipped_no_target": skipped,
            }

    # Build combined report
    combined_report = IngestReport(
        provider=provider_name or "unknown", attempted=True, success=True, error=None
    )
    combined_report.finished = {
        "received": stats["finished_received"],
        "normalized": stats["normalized"],
        "ingested": sum(
            s.get("results_added", 0) + s.get("results_updated", 0)
            + (s.get("report", {}).get("finished", {}).get("ingested", 0) if s.get("legacy") else 0)
            for s in per_season_summary.values()
        ),
        "skipped_unmatchable": stats["skipped_unmatchable"],
        "skipped_no_target": total_skipped_no_target
            + sum(s.get("report", {}).get("finished", {}).get("skipped_no_target", 0) if s.get("legacy") else 0
                  for s in per_season_summary.values()),
    }
    combined_report.last_success_at = datetime.now(timezone.utc).isoformat()
    combined_report.written_files = written_files

    return {
        "per_season": per_season_summary,
        "report": combined_report.to_dict(),
    }
