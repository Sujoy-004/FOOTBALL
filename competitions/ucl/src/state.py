"""Build the unified UCL competition state document for results and simulation modes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from football_core.domain import DataAvailability, load_json_store

SEASON = "2025/26"

MODE_RESULTS = "results"
MODE_SIMULATION = "simulation"

STAGE_ORDER = ["league", "playoff", "R16", "QF", "SF", "FINAL"]

_STAGE_LABELS = {
    "league": "League Phase",
    "playoff": "Knockout Playoffs",
    "R16": "Round of 16",
    "QF": "Quarter-finals",
    "SF": "Semi-finals",
    "FINAL": "Final",
}

_KO_ROUNDS = ["R16", "QF", "SF"]

_VALID_STATUS = {"scheduled", "played", "played_pens", "unknown"}
_VALID_PROVENANCE = {"official", "manual", "replay", "simulated"}

_PHASE_LABELS = {
    "not_started": "Not Started",
    "league_stage": "League Phase",
    "league_stage_complete": "League Phase Complete",
    "knockout_playoffs": "Knockout Playoffs",
    "knockout": "Knockout",
    "completed": "Completed",
}

_TOTAL_LEAGUE_MATCHES = 144
_DEFAULT_PLAYOFF_TIE_COUNT = 8

_RESULT_BLOB_KEYS = (
    "team_a", "team_b", "score", "aggregate_a", "aggregate_b",
    "agg_a_full", "agg_b_full", "et_played", "et_a", "et_b",
    "penalties_played", "penalty_a", "penalty_b", "penalty_winner",
    "penalty_score", "winner", "status",
)


def _empty_ko_store() -> dict:
    return {
        "playoff": [],
        "rounds": {rnd: [] for rnd in _KO_ROUNDS},
        "final": [],
        "champion": None,
    }


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    return bool(value)


def _normalise_legs(entry: dict) -> Optional[list]:
    legs = entry.get("legs")
    if not isinstance(legs, list) or not legs:
        return None
    out = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        out.append({
            "leg": _as_int(leg.get("leg")) or (len(out) + 1),
            "home": leg.get("home"),
            "away": leg.get("away"),
            "home_score": _as_int(leg.get("home_score")),
            "away_score": _as_int(leg.get("away_score")),
        })
    return out or None


def _aggregate_from_legs(legs, team_a, team_b):
    if not legs or team_a is None or team_b is None:
        return None, None
    totals = {team_a: 0, team_b: 0}
    for leg in legs:
        home, away = leg.get("home"), leg.get("away")
        home_score, away_score = leg.get("home_score"), leg.get("away_score")
        if home_score is None or away_score is None:
            return None, None
        if home in totals:
            totals[home] += home_score
        if away in totals:
            totals[away] += away_score
    return totals[team_a], totals[team_b]


def _tie_penalty_fields(entry: dict):
    pens = entry.get("penalties")
    played = _as_bool(entry.get("penalties_played"))
    pen_a = _as_int(entry.get("penalty_a"))
    pen_b = _as_int(entry.get("penalty_b"))
    pen_winner = entry.get("penalty_winner")
    if isinstance(pens, dict):
        played = True
        pen_winner = pen_winner or pens.get("winner")
        parts = str(pens.get("score") or "").split("-")
        if len(parts) == 2:
            if pen_a is None:
                pen_a = _as_int(parts[0])
            if pen_b is None:
                pen_b = _as_int(parts[1])
    if pen_winner:
        played = True
    return played, pen_a, pen_b, (pen_winner or None)


def _final_penalty_fields(entry: dict):
    pens = entry.get("penalties")
    played = _as_bool(entry.get("penalties_played"))
    pen_winner = entry.get("penalty_winner")
    pen_score = entry.get("penalty_score")
    if isinstance(pens, dict):
        played = True
        pen_winner = pen_winner or pens.get("winner")
        pen_score = pen_score or pens.get("score")
        home_pen = _as_int(pens.get("home"))
        away_pen = _as_int(pens.get("away"))
        if pen_score is None and home_pen is not None and away_pen is not None:
            pen_score = f"{home_pen}-{away_pen}"
    if pen_winner or pen_score:
        played = True
    return played, (pen_winner or None), (str(pen_score) if pen_score else None)


def _flatten_result_blob(entry: dict) -> dict:
    flat = {k: v for k, v in entry.items() if k != "result"}
    blob = entry.get("result")
    if isinstance(blob, dict):
        for key in _RESULT_BLOB_KEYS:
            if key in blob and flat.get(key) is None:
                flat[key] = blob[key]
        legs = []
        for idx in (1, 2):
            leg = blob.get(f"leg{idx}")
            if isinstance(leg, dict):
                legs.append({
                    "leg": idx,
                    "home": leg.get("team_a"),
                    "away": leg.get("team_b"),
                    "home_score": _as_int(leg.get("score_a")),
                    "away_score": _as_int(leg.get("score_b")),
                })
        if legs:
            flat.setdefault("legs", legs)
    return flat


def _load_bracket_rules(data_dir: Path) -> list:
    payload, availability, _ = load_json_store(data_dir / "bracket_rules.json")
    if availability is not DataAvailability.AVAILABLE or not isinstance(payload, dict):
        raise ValueError(
            "bracket_rules.json is unavailable: canonical match ids cannot be minted")
    matches = payload.get("matches")
    if not isinstance(matches, list) or not matches:
        raise ValueError("bracket_rules.json contains no matches")
    return matches


def _round_templates(rules_matches: list):
    templates = {rnd: [] for rnd in _KO_ROUNDS}
    templates["FINAL"] = []
    source_map: dict = {}
    quarters: dict = {}
    slot_sources: dict = {}
    for match in rules_matches:
        match_id = match.get("match_id")
        round_name = match.get("round")
        if not isinstance(match_id, str) or not match_id or round_name not in templates:
            continue
        templates[round_name].append(match_id)
        if isinstance(match.get("source_matches"), list) and match["source_matches"]:
            source_map[match_id] = list(match["source_matches"])
        if match.get("quarter") is not None:
            quarters[match_id] = _as_int(match["quarter"])
        slots = {}
        if match.get("home_seed") is not None:
            slots["home_seed"] = match["home_seed"]
        if match.get("away_playoff_tie") is not None:
            slots["away_playoff_tie"] = match["away_playoff_tie"]
        slot_sources[match_id] = slots or None
    return templates, source_map, quarters, slot_sources


def _playoff_templates(data_dir: Path):
    payload, availability, _ = load_json_store(data_dir / "playoff_pairings.json")
    templates = []
    slot_sources: dict = {}
    if availability is DataAvailability.AVAILABLE and isinstance(payload, dict):
        for pairing in payload.get("pairings") or []:
            tie = _as_int(pairing.get("tie")) if isinstance(pairing, dict) else None
            if tie is None:
                continue
            tie_id = f"playoff_t{tie}"
            if tie_id in slot_sources:
                continue
            templates.append(tie_id)
            slot_sources[tie_id] = {
                "position_a": pairing.get("position_a"),
                "position_b": pairing.get("position_b"),
            }
    templates.sort(key=lambda t: int(t.rsplit("t", 1)[-1]))
    if not templates:
        templates = [f"playoff_t{i}" for i in range(1, _DEFAULT_PLAYOFF_TIE_COUNT + 1)]
        for tie_id in templates:
            slot_sources[tie_id] = None
    return templates, slot_sources


def _normalise_ko_store(payload: Any) -> dict:
    matches = payload.get("matches") if isinstance(payload, dict) else None
    if not isinstance(matches, dict):
        return _empty_ko_store()
    is_v2 = payload.get("schema") == 2 or isinstance(matches.get("final"), list)
    rounds_raw = matches.get("rounds") if isinstance(matches.get("rounds"), dict) else {}
    rounds = {
        rnd: [e for e in (rounds_raw.get(rnd) or []) if isinstance(e, dict)]
        for rnd in _KO_ROUNDS
    }
    if is_v2:
        final_raw = matches.get("final")
        if not isinstance(final_raw, list) or not final_raw:
            final_raw = rounds_raw.get("FINAL") or []
    else:
        final_raw = rounds_raw.get("FINAL") or []
    final = [e for e in final_raw if isinstance(e, dict)]
    playoff = [e for e in (matches.get("playoff") or []) if isinstance(e, dict)]
    champion = matches.get("champion") or None
    return {"playoff": playoff, "rounds": rounds, "final": final, "champion": champion}


def _assign_entries(template_ids: list, template_keys: list, entries: list, entry_key) -> dict:
    by_key: dict = {}
    queue: list = []
    for entry in entries:
        key = entry_key(entry)
        if key is not None and key not in by_key:
            by_key[key] = entry
        else:
            queue.append(entry)
    assigned: dict = {}
    remaining: list = []
    for tie_id, key in zip(template_ids, template_keys):
        if key in by_key:
            assigned[tie_id] = by_key[key]
        else:
            remaining.append(tie_id)
    for tie_id, entry in zip(remaining, queue):
        assigned[tie_id] = entry
    return assigned


def _build_tie(
    tie_id: str,
    round_name: str,
    quarter,
    template_slots,
    template_sources,
    entry,
    default_provenance,
    force_provenance=None,
) -> dict:
    entry = entry if isinstance(entry, dict) else None
    safe_entry = entry or {}
    team_a = safe_entry.get("team_a") or None
    team_b = safe_entry.get("team_b") or None
    legs = _normalise_legs(safe_entry)
    agg_a = _as_int(safe_entry.get("aggregate_a"))
    agg_b = _as_int(safe_entry.get("aggregate_b"))
    if agg_a is None and agg_b is None:
        agg_a = _as_int(safe_entry.get("score_a"))
        agg_b = _as_int(safe_entry.get("score_b"))
    if agg_a is None and agg_b is None:
        agg_a, agg_b = _aggregate_from_legs(legs, team_a, team_b)
    et_played = _as_bool(safe_entry.get("et_played"))
    et_a = _as_int(safe_entry.get("et_a")) or 0
    et_b = _as_int(safe_entry.get("et_b")) or 0
    pens_played, pen_a, pen_b, pen_winner = _tie_penalty_fields(safe_entry)
    agg_a_full = _as_int(safe_entry.get("agg_a_full"))
    agg_b_full = _as_int(safe_entry.get("agg_b_full"))
    if agg_a_full is None:
        agg_a_full = agg_a + et_a if agg_a is not None else None
    if agg_b_full is None:
        agg_b_full = agg_b + et_b if agg_b is not None else None
    winner = safe_entry.get("winner") or None
    if winner is None and agg_a_full is not None and agg_b_full is not None:
        if agg_a_full > agg_b_full:
            winner = team_a
        elif agg_b_full > agg_a_full:
            winner = team_b
    if winner is None and pen_winner:
        winner = pen_winner
    raw_status = safe_entry.get("status")
    if isinstance(raw_status, str) and raw_status in _VALID_STATUS:
        status = raw_status
    elif entry is None:
        status = "scheduled"
    elif pens_played and pen_winner:
        status = "played_pens"
    elif winner is not None or agg_a_full is not None:
        status = "played"
    else:
        status = "scheduled"
    if force_provenance is not None:
        provenance = force_provenance
    elif entry is None:
        provenance = None
    else:
        raw_prov = safe_entry.get("provenance")
        if isinstance(raw_prov, str) and raw_prov in _VALID_PROVENANCE:
            provenance = raw_prov
        else:
            provenance = default_provenance
    slot_sources = dict(template_slots) if template_slots else None
    stored_slots = safe_entry.get("slot_sources")
    if isinstance(stored_slots, dict):
        merged = dict(slot_sources) if slot_sources else {}
        merged.update({k: v for k, v in stored_slots.items() if v is not None})
        slot_sources = merged
    stored_sources = safe_entry.get("source_matches")
    if isinstance(stored_sources, list):
        source_matches = list(stored_sources)
    elif template_sources:
        source_matches = list(template_sources)
    else:
        source_matches = None
    node: dict = {"id": tie_id, "round": round_name}
    if round_name == "playoff":
        node["tie_num"] = _as_int(tie_id.rsplit("t", 1)[-1])
    if quarter is not None:
        node["quarter"] = quarter
    node.update({
        "team_a": team_a,
        "team_b": team_b,
        "legs": legs,
        "aggregate_a": agg_a,
        "aggregate_b": agg_b,
        "agg_a_full": agg_a_full,
        "agg_b_full": agg_b_full,
        "et_played": et_played,
        "et_a": et_a,
        "et_b": et_b,
        "penalties_played": pens_played,
        "penalty_a": pen_a if pen_a is not None else 0,
        "penalty_b": pen_b if pen_b is not None else 0,
        "penalty_winner": pen_winner,
        "winner": winner,
        "status": status,
        "provenance": provenance,
        "slot_sources": slot_sources,
        "source_matches": source_matches,
    })
    return node


def _build_final_node(entry, default_provenance, force_provenance=None,
                      source_matches=None) -> dict:
    entry = entry if isinstance(entry, dict) else None
    safe_entry = entry or {}
    team_a = safe_entry.get("team_a") or None
    team_b = safe_entry.get("team_b") or None
    raw_score = safe_entry.get("score")
    if isinstance(raw_score, dict):
        home = _as_int(raw_score.get("home"))
        away = _as_int(raw_score.get("away"))
    else:
        home = _as_int(safe_entry.get("score_a"))
        away = _as_int(safe_entry.get("score_b"))
    et_played = _as_bool(safe_entry.get("et_played"))
    et_a = _as_int(safe_entry.get("et_a")) or 0
    et_b = _as_int(safe_entry.get("et_b")) or 0
    pens_played, pen_winner, pen_score = _final_penalty_fields(safe_entry)
    winner = safe_entry.get("winner") or None
    if winner is None and pen_winner:
        winner = pen_winner
    elif winner is None and home is not None and away is not None and home != away:
        winner = team_a if home > away else team_b
    raw_status = safe_entry.get("status")
    if isinstance(raw_status, str) and raw_status in _VALID_STATUS:
        status = raw_status
    elif pens_played:
        status = "played_pens"
    elif winner is not None or home is not None:
        status = "played"
    else:
        status = "scheduled"
    if force_provenance is not None:
        provenance = force_provenance
    elif entry is None:
        provenance = None
    else:
        raw_prov = safe_entry.get("provenance")
        if isinstance(raw_prov, str) and raw_prov in _VALID_PROVENANCE:
            provenance = raw_prov
        else:
            provenance = default_provenance
    return {
        "id": "final_01",
        "team_a": team_a,
        "team_b": team_b,
        "score": {"home": home, "away": away},
        "et_played": et_played,
        "et_a": et_a,
        "et_b": et_b,
        "penalties_played": pens_played,
        "penalty_winner": pen_winner,
        "penalty_score": pen_score,
        "winner": winner,
        "status": status,
        "provenance": provenance,
        # Declared by bracket_rules.json (sf_01/sf_02) so the shared tree
        # renderer can draw the SF -> FINAL progression edges.
        "source_matches": list(source_matches) if source_matches else None,
    }


def _competition_phase(data_dir: Path) -> dict:
    try:
        from competitions.ucl.src.orchestrator import compute_competition_phase
        return compute_competition_phase(data_dir)
    except Exception:
        return _fallback_phase(data_dir)


def _fallback_phase(data_dir: Path) -> dict:
    _, league_availability, _ = load_json_store(data_dir / "results.json")
    league_rows: list = []
    if league_availability is DataAvailability.AVAILABLE:
        payload, _, _ = load_json_store(data_dir / "results.json")
        league_rows = payload.get("matches", payload) if isinstance(payload, dict) else payload
        if not isinstance(league_rows, list):
            league_rows = []
    n_league = sum(
        1 for m in league_rows
        if isinstance(m, dict) and m.get("home_score") is not None
    )
    _, ko_availability, _ = load_json_store(data_dir / "knockout_results.json")
    ko_state: dict = {}
    if ko_availability is DataAvailability.AVAILABLE:
        payload, _, _ = load_json_store(data_dir / "knockout_results.json")
        ko_state = payload.get("matches", {}) if isinstance(payload, dict) else {}
        if not isinstance(ko_state, dict):
            ko_state = {}
    ko_rounds = ko_state.get("rounds", {}) or {}
    n_playoff = len(ko_state.get("playoff", []) or [])
    n_ko_matches = sum(len(v or []) for v in ko_rounds.values())
    champion = ko_state.get("champion") or None
    if champion:
        phase = "completed"
    elif n_ko_matches > 0:
        phase = "knockout"
    elif n_playoff > 0:
        phase = "knockout_playoffs"
    elif n_league >= _TOTAL_LEAGUE_MATCHES:
        phase = "league_stage_complete"
    elif n_league > 0:
        phase = "league_stage"
    else:
        phase = "not_started"
    return {
        "phase": phase,
        "label": _PHASE_LABELS[phase],
        "champion": champion,
        "progress": {"played": n_league, "total": _TOTAL_LEAGUE_MATCHES},
        "stores": {
            "league_results": league_availability.value,
            "knockout_results": ko_availability.value,
        },
    }


def _league_stage(data_dir: Path, league_availability: DataAvailability) -> dict:
    matchdays: dict = {}
    if league_availability is DataAvailability.AVAILABLE:
        try:
            from competitions.ucl.src.pipeline import build_league_matchdays, load_results
            matchdays = build_league_matchdays(load_results(data_dir))
        except Exception:
            matchdays = _fallback_matchdays(data_dir)
    return {
        "id": "league",
        "label": _STAGE_LABELS["league"],
        "layout": "list",
        "matchdays": matchdays,
    }


def _fallback_matchdays(data_dir: Path) -> dict:
    from football_core.domain import canonical_from_result_entry
    rows: list = []
    payload, availability, _ = load_json_store(data_dir / "results.json")
    if availability is DataAvailability.AVAILABLE and isinstance(payload, dict):
        candidates = payload.get("matches", payload)
        if isinstance(candidates, list):
            rows = [m for m in candidates if isinstance(m, dict)]
    grouped: dict = {}
    for m in rows:
        prefix = m.get("match_id", "").split("_")[0]
        row = dict(m)
        cm = canonical_from_result_entry(m, "ucl")
        row.setdefault("winner", cm.winner)
        row["status"] = cm.status.value
        row["provenance"] = "official"
        grouped.setdefault(prefix, []).append(row)
    return {k: grouped[k] for k in sorted(grouped)}


def _simulation_store(sim_payload: dict, playoff_templates: list, round_templates: dict):
    playoff_index: dict = {}
    playoff_queue: list = []
    sim_playoff = sim_payload.get("playoff")
    if isinstance(sim_playoff, list):
        for entry in sim_playoff:
            if not isinstance(entry, dict):
                continue
            flat = _flatten_result_blob(entry)
            tie_num = _as_int(flat.get("tie_num"))
            tie_id = f"playoff_t{tie_num}" if tie_num is not None else None
            if tie_id is not None and tie_id in playoff_templates and tie_id not in playoff_index:
                playoff_index[tie_id] = flat
            else:
                playoff_queue.append(flat)
    winners = sim_payload.get("playoff_winners")
    if isinstance(winners, dict):
        for tie_num, name in winners.items():
            num = _as_int(tie_num)
            if num is None:
                continue
            tie_id = f"playoff_t{num}"
            if tie_id in playoff_templates and tie_id not in playoff_index:
                playoff_index[tie_id] = {"tie_num": num, "team_a": name, "winner": name}
    remaining = [t for t in playoff_templates if t not in playoff_index]
    for tie_id, flat in zip(remaining, playoff_queue):
        playoff_index[tie_id] = flat
    rounds_index: dict = {}
    final_list: list = []
    bracket = sim_payload.get("bracket_rounds")
    bracket = bracket if isinstance(bracket, dict) else {}
    for round_name in _KO_ROUNDS + ["FINAL"]:
        entries = bracket.get(round_name) or []
        by_id: dict = {}
        queue: list = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            flat = _flatten_result_blob(entry)
            match_id = flat.get("match_id")
            if isinstance(match_id, str) and match_id and match_id not in by_id:
                by_id[match_id] = flat
            else:
                queue.append(flat)
        if round_name == "FINAL":
            final_list = list(by_id.values()) + queue
            continue
        tids = round_templates.get(round_name, [])
        assigned = {tid: by_id[tid] for tid in tids if tid in by_id}
        remaining = [tid for tid in tids if tid not in assigned]
        for tid, flat in zip(remaining, queue):
            assigned[tid] = flat
        rounds_index[round_name] = assigned
    for round_name in _KO_ROUNDS:
        rounds_index.setdefault(round_name, {})
    return playoff_index, rounds_index, final_list


def _validate_graph(rules_matches: list, playoff_templates: list, emitted_nodes: list) -> None:
    from football_core.state import validate_bracket
    nodes = []
    allowed = set(playoff_templates)
    for match in rules_matches:
        match_id = match.get("match_id")
        if not isinstance(match_id, str) or not match_id:
            continue
        nodes.append({
            "match_id": match_id,
            "source_matches": match.get("source_matches"),
        })
        allowed.add(match_id)
    validate_bracket(nodes)
    for node in emitted_nodes:
        for src in node.get("source_matches") or []:
            if src not in allowed:
                raise ValueError(
                    f"source_matches reference '{src}' does not resolve "
                    f"within the produced bracket state")


def build_competition_state(data_dir, mode: str = MODE_RESULTS, sim_payload: Optional[dict] = None, active_season: str | None = None) -> dict:
    """Build the canonical competition state document.

    mode="results" reads the on-disk stores factually; mode="simulation"
    consumes a sim_payload shaped like the Monte Carlo enrichment output and
    marks every knockout node with provenance "simulated".

    Exchange 5: ``active_season`` — when a non-historical season is active,
    results and fixtures are read from ``data/seasons/<id>/`` instead of the
    root stores.  Structural files (bracket_rules, playoff_pairings) are
    always read from root.
    """
    dp = Path(data_dir) if isinstance(data_dir, str) else data_dir
    if mode not in (MODE_RESULTS, MODE_SIMULATION):
        raise ValueError(f"unknown mode: {mode!r}")
    if mode == MODE_SIMULATION:
        if sim_payload is None:
            raise ValueError("mode='simulation' requires sim_payload")
        if not isinstance(sim_payload, dict):
            raise ValueError("sim_payload must be a dict")
    else:
        sim_payload = None

    # Exchange 5: resolve the active data directory for results/fixtures.
    from competitions.ucl.src.seasons import LOCAL_HISTORICAL_SEASON, season_dir
    _active_dp = dp
    _is_new_season = False
    if active_season and active_season != LOCAL_HISTORICAL_SEASON:
        candidate = season_dir(dp, active_season)
        if candidate.is_dir():
            _active_dp = candidate
            _is_new_season = True

    _, league_availability, _ = load_json_store(_active_dp / "results.json")
    _, fixtures_availability, _ = load_json_store(_active_dp / "fixtures.json")
    ko_payload, ko_availability, _ = load_json_store(dp / "knockout_results.json")

    # Exchange 5: phase computation uses the active data dir for results,
    # but structural files from root.
    phase = _competition_phase(_active_dp) if _is_new_season else _competition_phase(dp)

    rules_matches = _load_bracket_rules(dp)
    templates, source_map, quarters, round_slots = _round_templates(rules_matches)
    playoff_templates, playoff_slots = _playoff_templates(dp)

    if ko_availability is DataAvailability.AVAILABLE:
        ko_store = _normalise_ko_store(ko_payload)
    else:
        ko_store = _empty_ko_store()

    stages: dict = {"league": _league_stage(_active_dp, league_availability) if _is_new_season else _league_stage(dp, league_availability)}

    if mode == MODE_RESULTS:
        default_provenance = "manual"
        force_provenance = None
        champion = ko_store["champion"]
        playoff_assigned = _assign_entries(
            playoff_templates,
            [_as_int(t.rsplit("t", 1)[-1]) for t in playoff_templates],
            ko_store["playoff"],
            lambda e: _as_int(e.get("tie_num")),
        )
        rounds_assigned = {}
        for rnd in _KO_ROUNDS:
            rounds_assigned[rnd] = _assign_entries(
                templates[rnd],
                list(templates[rnd]),
                ko_store["rounds"].get(rnd, []),
                _entry_match_id,
            )
        final_entry = ko_store["final"][0] if ko_store["final"] else None
    else:
        default_provenance = "manual"
        force_provenance = "simulated"
        champion = None
        playoff_assigned, rounds_assigned, final_list = _simulation_store(
            sim_payload, playoff_templates, templates)
        final_entry = final_list[0] if final_list else None

    stages["playoff"] = {
        "id": "playoff",
        "label": _STAGE_LABELS["playoff"],
        "layout": "list",
        "matches": [
            _build_tie(tie_id, "playoff", None, playoff_slots.get(tie_id), None,
                       playoff_assigned.get(tie_id), default_provenance, force_provenance)
            for tie_id in playoff_templates
        ],
    }
    for round_name in _KO_ROUNDS:
        stages[round_name] = {
            "id": round_name,
            "label": _STAGE_LABELS[round_name],
            "layout": "tree",
            "matches": [
                _build_tie(tie_id, round_name, quarters.get(tie_id),
                           round_slots.get(tie_id), source_map.get(tie_id),
                           rounds_assigned[round_name].get(tie_id),
                           default_provenance, force_provenance)
                for tie_id in templates[round_name]
            ],
        }
    stages["FINAL"] = {
        "id": "FINAL",
        "label": _STAGE_LABELS["FINAL"],
        "layout": "tree",
        "matches": [_build_final_node(
            final_entry, default_provenance, force_provenance,
            source_matches=source_map.get("final_01"))],
    }

    emitted_nodes = [m for sid in ("playoff", "R16", "QF", "SF", "FINAL")
                     for m in stages[sid]["matches"]]
    _validate_graph(rules_matches, playoff_templates, emitted_nodes)

    state: dict = {
        "competition": "ucl",
        "season": active_season or SEASON,
        "mode": mode,
        "phase": phase,
        "availability": {
            "league_results": league_availability.value,
            "fixtures": fixtures_availability.value,
            "knockout_results": ko_availability.value,
        },
        "champion": champion,
        "stage_order": list(STAGE_ORDER),
        "stages": stages,
    }
    if mode == MODE_SIMULATION:
        probs = sim_payload.get("champion_probs")
        if probs:
            state["champion_probs"] = probs
    return state


def _entry_match_id(entry: dict):
    value = entry.get("match_id")
    return value if isinstance(value, str) and value else None
