"""World Cup bracket computation.

Format rules live here, not in the web layer; ``web/wc_app.py`` re-exports
``compute_full_bracket`` for transport.
"""

from __future__ import annotations

from competitions.worldcup.src import elo
from competitions.worldcup.src.insight import compute_ko_signal_probs
from competitions.worldcup.src.knockout import resolve_knockout_slot_teams


def _build_match_score(played_m):
    if not played_m:
        return None
    hs = played_m.get("home_score")
    as_ = played_m.get("away_score")
    if hs is not None and as_ is not None:
        return {"home": hs, "away": as_}
    return played_m.get("score")


def compute_bracket_display(groups, teams, bracket, annex_c, played, played_groups):
    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    known_winners = {mid: data["winner"] for mid, data in played.items() if data.get("winner")}
    slot_teams = resolve_knockout_slot_teams(groups, teams, played_groups, bracket, annex_c, known_winners)
    matchups = []
    for mid, st in sorted(slot_teams.items()):
        ta, tb = st["team_a"], st["team_b"]
        prob_a = round(elo.expected_score(elo_ratings.get(ta, 1500), elo_ratings.get(tb, 1500)), 4) if ta in elo_ratings and tb in elo_ratings else 0.5
        played_m = played.get(mid)
        matchups.append({
            "match_id": mid,
            "team_a": ta,
            "team_b": tb,
            "prob_a": prob_a,
            "winner": played_m.get("winner") if played_m else None,
            "score": _build_match_score(played_m),
            "played": mid in played,
        })
    return {"rounds": {"R32": matchups}, "n_matchups": len(matchups)}


def _match_truth_fields(match_id, played_m, ta, tb):
    """Explicit canonical state + probability availability (Exchange 2)."""
    from football_core.domain import canonical_from_result_entry
    if played_m:
        cm = canonical_from_result_entry({**played_m, "match_id": match_id}, "worldcup")
        return cm.status.value, cm.provenance.value
    return "scheduled", "official"


def _prob_availability(ta, tb, elo_ratings):
    """(available, reason) for the Elo-based prob_a on a bracket node."""
    if not ta or not tb:
        return False, "slot_unresolved"
    if ta not in elo_ratings or tb not in elo_ratings:
        return False, "no_elo_rating"
    return True, None


def compute_full_bracket(groups, teams, bracket, annex_c, played, played_groups, engine_predictions=None):
    from competitions.worldcup.src.evaluation import compute_team_strengths_from_predictions
    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    known_winners = {mid: data["winner"] for mid, data in played.items() if data.get("winner")}
    slot_teams = resolve_knockout_slot_teams(groups, teams, played_groups, bracket, annex_c, known_winners)
    resolved = {}

    def _entry_for(mid):
        for b in bracket:
            if b["match_id"] == mid:
                return b
        return None

    team_strengths = {}
    all_matches = []
    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        all_matches.append(m)

    if engine_predictions and len(engine_predictions) == len(all_matches):
        team_strengths = compute_team_strengths_from_predictions(engine_predictions, all_matches)
    else:
        team_strengths = {}

    def _signal_probs(ta, tb):
        if team_strengths:
            sigs, elo_p = compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings)
            return sigs, elo_p
        return {}, 0.5

    for mid, st in slot_teams.items():
        ta, tb = st["team_a"], st["team_b"]
        be = _entry_for(mid)
        rnd = be["round"] if be else "R32"
        prob_a = round(elo.expected_score(elo_ratings.get(ta, 1500), elo_ratings.get(tb, 1500)), 4) \
            if ta in elo_ratings and tb in elo_ratings else 0.5
        played_m = played.get(mid)
        status, provenance = _match_truth_fields(mid, played_m, ta, tb)
        p_avail, p_reason = _prob_availability(ta, tb, elo_ratings)
        sigs, elo_p = _signal_probs(ta, tb)
        resolved[mid] = {
            "match_id": mid, "round": rnd,
            "team_a": ta, "team_b": tb,
            "prob_a": prob_a,
            "winner": played_m.get("winner") if played_m else None,
            "score": _build_match_score(played_m),
            "played": mid in played,
            "status": status,
            "provenance": provenance,
            "prob_available": p_avail,
            "prob_reason": p_reason,
            "source_matches": be.get("source_matches") if be else None,
            "signals": sigs,
        }

    def _resolve_teams_from_source(entry):
        sms = entry.get("source_matches", [])
        if not sms:
            return None, None
        if entry["round"] == "TPP":
            teams_ab = []
            for sm in sms:
                src = resolved.get(sm)
                if src and src["winner"] and src["team_a"] and src["team_b"]:
                    teams_ab.append(src["team_b"] if src["winner"] == src["team_a"] else src["team_a"])
                else:
                    teams_ab.append(None)
            return teams_ab[0] if len(teams_ab) > 0 else None, \
                   teams_ab[1] if len(teams_ab) > 1 else None
        ta_src = resolved.get(sms[0])
        tb_src = resolved.get(sms[1]) if len(sms) > 1 else None
        return (ta_src.get("winner") if ta_src else None,
                tb_src.get("winner") if tb_src else None)

    for entry in bracket:
        mid = entry["match_id"]
        if mid in resolved:
            if not resolved[mid].get("source_matches") and entry.get("source_matches"):
                resolved[mid]["source_matches"] = entry["source_matches"]
            continue
        ta, tb = _resolve_teams_from_source(entry)
        prob_a = round(elo.expected_score(elo_ratings.get(ta, 1500), elo_ratings.get(tb, 1500)), 4) \
            if ta and tb and ta in elo_ratings and tb in elo_ratings else 0.5
        played_m = played.get(mid)
        status, provenance = _match_truth_fields(mid, played_m, ta, tb)
        p_avail, p_reason = _prob_availability(ta or "", tb or "", elo_ratings)
        sigs, elo_p = _signal_probs(ta or "", tb or "")
        resolved[mid] = {
            "match_id": mid, "round": entry["round"],
            "team_a": ta, "team_b": tb,
            "prob_a": prob_a,
            "winner": played_m.get("winner") if played_m else None,
            "score": _build_match_score(played_m),
            "played": mid in played,
            "status": status,
            "provenance": provenance,
            "prob_available": p_avail,
            "prob_reason": p_reason,
            "source_matches": entry.get("source_matches"),
            "signals": sigs,
        }

    # Resolved at CALL time, never module scope: this module is imported by
    # pipeline.py, so a module-scope `from ...pipeline import` would close an
    # import cycle. Call-time resolution also keeps a test that patches
    # pipeline.bracket_stage_order effective.
    from competitions.worldcup.src.pipeline import bracket_stage_order
    rounds_order = bracket_stage_order()
    rounds_data = {r: [] for r in rounds_order}
    for data in resolved.values():
        r = data["round"]
        if r in rounds_data:
            rounds_data[r].append(data)
    return {"rounds": rounds_data, "n_matchups": len(resolved)}
