import json, os, uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
import threading

import fastapi
from fastapi.responses import JSONResponse

from dotenv import load_dotenv

from competitions.worldcup.src import constants, elo
from competitions.worldcup.src.knockout import run_full_simulation, resolve_knockout_slot_teams
from competitions.worldcup.src.state import load_groups, load_annex_c
from competitions.worldcup.src.analysis import run_calibrated_validation
from football_core.groups import precompute_matchup_lambdas, simulate_group_matches
from competitions.worldcup.src.groups import (
    compute_standings, rank_third_placed,
)

from competitions.worldcup.src.insight import compute_ko_signal_probs, compute_match_insight
from competitions.worldcup.src.evaluation import compute_team_strengths_from_predictions
from web.common import boot_step, load_json
from web.simulation_service import (
    SimulationTaskService, build_simulation_meta,
)
from football_core.simulation import SimulationContractError
from typing import Optional

logger = logging.getLogger(__name__)

load_dotenv()
BSD_API_KEY = os.getenv("BSD_API_KEY", "")
FOOTBALL_DATA_ORG_KEY = os.getenv("FOOTBALL_DATA_ORG_KEY", "")

DATA_DIR = constants.DATA_DIR

cache: dict = {}
sim_cache: dict = {}
boot_log: list[dict] = []
service = SimulationTaskService()


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

    from competitions.worldcup.src.pipeline import bracket_stage_order
    rounds_order = bracket_stage_order()
    rounds_data = {r: [] for r in rounds_order}
    for data in resolved.values():
        r = data["round"]
        if r in rounds_data:
            rounds_data[r].append(data)
    return {"rounds": rounds_data, "n_matchups": len(resolved)}


def build_chronological_matches() -> dict:
    """Build chronological match listing grouped by round.

    Delegates to pipeline. Returns: {rounds: [{round_name, round_type, matches}]}
    """
    from competitions.worldcup.src.pipeline import build_chronological_matches as _pipeline_build
    return _pipeline_build(DATA_DIR)


def build_knockout_tree() -> dict:
    """Build knockout tree structure with resolved teams for all rounds.

    Delegates to pipeline. Returns: {round_name: [{match_id, team_a, team_b, ...}]}
    """
    from competitions.worldcup.src.pipeline import build_knockout_tree as _pipeline_build
    return _pipeline_build(DATA_DIR)


def compute_signal_eval(teams, played, played_groups, engine_predictions, all_matches):
    """Evaluate signals from engine predictions — no ledger dependency."""
    from competitions.worldcup.src.evaluation import compute_signal_eval as _eval
    return _eval(teams, played, played_groups, engine_predictions, all_matches)


def compute_real_standings(groups_data: dict, played_groups: dict) -> list[dict]:
    """Compute deterministic real standings from played group matches.

    Returns a flat list sorted by group, then position:
    [{group, position, team, pts, gd, gs, ga, played}, ...]
    """
    standings = []
    for group_letter in sorted(groups_data.keys()):
        group = groups_data[group_letter]
        team_stats: dict[str, dict] = {}
        for match in group.get("matches", []):
            mid = match["match_id"]
            if mid not in played_groups:
                continue
            m = played_groups[mid]
            ta, tb = m["team_a"], m["team_b"]
            hs = m.get("home_score", 0)
            aw = m.get("away_score", 0)
            for team, gs, ga in [(ta, hs, aw), (tb, aw, hs)]:
                if team not in team_stats:
                    team_stats[team] = {"team": team, "group": group_letter, "pts": 0, "gd": 0, "gs": 0, "ga": 0, "played": 0}
                team_stats[team]["gs"] += gs
                team_stats[team]["ga"] += ga
                team_stats[team]["gd"] += (gs - ga)
                team_stats[team]["played"] += 1
            if hs > aw:
                team_stats[ta]["pts"] += 3
            elif aw > hs:
                team_stats[tb]["pts"] += 3
            else:
                team_stats[ta]["pts"] += 1
                team_stats[tb]["pts"] += 1
        sorted_teams = sorted(team_stats.values(), key=lambda t: (-t["pts"], -t["gd"], -t["gs"]))
        for i, t in enumerate(sorted_teams, 1):
            t["position"] = i
            standings.append(t)
    return standings


def compute_signals_meta() -> dict:
    """Check on-disk signal cache files and return metadata."""
    cache_files: list[tuple[str, str]] = [
        ("odds_cache.json", "market_odds"),
        ("rolling_form_cache.json", "rolling_form"),
        ("squad_value_cache.json", "squad_value"),
        ("rest_days_cache.json", "rest_days"),
    ]
    signals = []
    for fname, sname in cache_files:
        path = DATA_DIR / fname
        exists = path.exists()
        mtime = None
        if exists:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        signals.append({"name": sname, "available": exists, "last_updated": mtime})
    return {"signals": signals, "n_total": len(signals)}


def compute_overview() -> dict:
    """Real-data-first overview — no simulation, no engine predictions.

    Loads teams, groups, bracket, played results from disk and computes
    deterministic standings and bracket display only.
    """
    global boot_log
    boot_log = []
    data = {"boot": []}

    ld = boot_step("Data Loading", lambda: {
        "teams": load_json(DATA_DIR, "teams.json"),
        "groups": load_groups(DATA_DIR, teams=load_json(DATA_DIR, "teams.json")),
        "bracket": json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8")),
        "annex_c": json.loads((DATA_DIR / "annex_c.json").read_text(encoding="utf-8")),
        "played": json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {},
        "played_groups": json.loads((DATA_DIR / "played_groups.json").read_text(encoding="utf-8")) if (DATA_DIR / "played_groups.json").exists() else {},
    }, boot_log)
    if not ld:
        return {"boot": boot_log, "error": "data load failed"}
    teams, groups_data = ld["teams"], ld["groups"]["groups"]
    bracket, annex_c = ld["bracket"], ld["annex_c"]
    played, played_groups = ld["played"], ld["played_groups"]

    total_played = sum(1 for m in played.values() if m.get("winner"))
    total_played += sum(1 for m in played_groups.values() if m.get("winner"))

    gs = boot_step("Group Standings", lambda:
        compute_real_standings(groups_data, played_groups)
    , boot_log) or []

    bracket_display = boot_step("Bracket Resolution", lambda:
        compute_bracket_display(ld["groups"], teams, bracket, annex_c, played, played_groups)
    , boot_log)

    signals_meta = compute_signals_meta()

    team_list = [{"name": name, "elo": round(d["elo"], 1)} for name, d in sorted(teams.items(), key=lambda t: t[1].get("elo", 1500), reverse=True)]

    full_bracket = compute_full_bracket(
        ld["groups"], teams, bracket, annex_c, played, played_groups,
    )

    data["boot"] = boot_log
    data["teams"] = team_list
    data["n_teams"] = len(team_list)
    data["n_played"] = total_played
    data["standings"] = gs
    data["bracket"] = bracket_display
    data["full_bracket"] = full_bracket
    data["signals_meta"] = signals_meta
    # Authoritative competition phase (competition brain owns derivation).
    from competitions.worldcup.src.pipeline import compute_competition_phase
    data["phase"] = boot_step("Competition Phase", lambda: compute_competition_phase(DATA_DIR), boot_log)
    # Season-lifecycle view (same key contract as the UCL discover output),
    # reusing the phase report just computed instead of re-deriving it.
    try:
        from competitions.worldcup.src.pipeline import season_lifecycle
        phase_report = data["phase"] if isinstance(data["phase"], dict) else None
        data["lifecycle"] = season_lifecycle(DATA_DIR, phase=phase_report)
    except Exception:
        data["lifecycle"] = {}
    # Freshness from the persisted refresh report (survives cache rebuilds).
    try:
        lr = json.loads(
            (Path(__file__).parent / "last_refresh.json").read_text(encoding="utf-8")
        )
        data["refresh"] = lr.get("worldcup", {})
    except Exception:
        data["refresh"] = {}
    return data


def unplayed_match_count() -> int:
    """Count matches that have neither played nor played_groups results."""
    teams_raw = load_json(DATA_DIR, "teams.json")
    groups_raw = load_groups(DATA_DIR, teams=teams_raw)
    bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
    played_raw = json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {}
    played_groups_raw = json.loads((DATA_DIR / "played_groups.json").read_text(encoding="utf-8")) if (DATA_DIR / "played_groups.json").exists() else {}
    played_ids = set(played_raw.keys()) | set(played_groups_raw.keys())
    all_ids = set()
    groups_data = groups_raw.get("groups", groups_raw) if isinstance(groups_raw, dict) else groups_raw
    for g in groups_data.values():
        for m in g.get("matches", []):
            if m.get("match_id"):
                all_ids.add(m["match_id"])
    for m in bracket_raw:
        if m.get("match_id"):
            all_ids.add(m["match_id"])
    return len(all_ids - played_ids)


def compute_signal_stats():
    """Signal statistics from on-disk caches — no ledger dependency."""
    from competitions.worldcup.src.evaluation import compute_signal_stats as _eval
    return _eval(constants.DATA_DIR)


def compute_signal_detail(name: str):
    from competitions.worldcup.src.evaluation import compute_signal_detail as _eval
    return _eval(name, constants.DATA_DIR, cache.get("evaluation", {}))


def compute_blend_info():
    """Blend info from in-memory cache evaluation + backtest — no cached file."""
    from competitions.worldcup.src.evaluation import compute_blend_info as _eval
    return _eval(constants.DATA_DIR, cache.get("evaluation", {}), {})


def _fetch_live_data() -> dict:
    """Fetch live match data + signal caches — delegates to pipeline.

    Returns the refresh report (provider/success/error/staleness/ingestion
    counters) and stores it in cache["refresh"] for the API surface.
    """
    from competitions.worldcup.src.pipeline import fetch_live_data as _pipeline_fetch
    try:
        report = _pipeline_fetch(BSD_API_KEY, FOOTBALL_DATA_ORG_KEY, DATA_DIR)
    except Exception as e:  # never let a refresh crash boot; mark stale
        report = {"provider": None, "attempted": True, "success": False,
                  "error": str(e), "stale": True, "finished": {}}
    cache["refresh"] = report
    return report



wc_app = fastapi.FastAPI()


@wc_app.get("/api/data")
def api_data():
    return JSONResponse({
        "refresh": _current_refresh_report(),
        "teams": cache.get("teams", []),
        "n_teams": cache.get("n_teams", 0),
        "n_played": cache.get("n_played", 0),
        "phase": cache.get("phase", {}),
        "simulation": _simulation_state_block(),
        "n_unplayed": unplayed_match_count(),
    })


def _simulation_state_block() -> dict:
    """Shared product contract: availability + request lifecycle."""
    eligible, reason, _msg = simulation_eligibility()
    sim_status = sim_cache.get("status", "not_requested")
    request_state = {
        "running": "running",
        "completed": "completed",
        "failed": "failed",
    }.get(sim_status, "not_requested")
    return {
        "availability": "available" if eligible else "not_needed",
        "reason": reason,
        "request_state": request_state,
    }


def _current_refresh_report() -> dict:
    try:
        lr = json.loads(
            (Path(__file__).parent / "last_refresh.json").read_text(encoding="utf-8")
        )
        return lr.get("worldcup", {})
    except Exception:
        return {}


@wc_app.get("/api/overview")
def api_overview():
    has_sim = has_simulation()
    return JSONResponse({
        "refresh": _current_refresh_report(),
        "standings": cache.get("standings", []),
        "teams": cache.get("teams", []),
        "n_teams": cache.get("n_teams", 0),
        "n_played": cache.get("n_played", 0),
        "signals_meta": cache.get("signals_meta", {"signals": [], "n_total": 0}),
        "phase": cache.get("phase", {}),

        "has_simulation": has_sim,
        "n_unplayed": unplayed_match_count(),
        "lifecycle": cache.get("lifecycle", {}),
    })


@wc_app.get("/api/simulation")
def api_simulation():
    return JSONResponse({
        "top_teams": sim_cache.get("top_teams", []),
        "signal_eval": sim_cache.get("signal_eval", {}),
        "simulation_meta": sim_cache.get("simulation_meta"),
        "status": sim_cache.get("status", "not_requested"),
        "message": sim_cache.get("message"),
        "n_unplayed": sim_cache.get("n_unplayed", unplayed_match_count()),
        "full_bracket": sim_cache.get("full_bracket"),
    })


@wc_app.get("/api/boot")
def api_boot():
    return JSONResponse(cache.get("boot", []))


@wc_app.get("/api/standings")
def api_standings():
    return JSONResponse({"standings": cache.get("standings", {}), "third_place": cache.get("third_place", [])})


@wc_app.get("/api/bracket")
def api_bracket():
    return JSONResponse(cache.get("bracket", {}))


@wc_app.get("/api/bracket/full")
def api_bracket_full():
    return JSONResponse(cache.get("full_bracket", {}))


@wc_app.get("/api/bracket/data")
def api_bracket_data():
    from competitions.worldcup.src.pipeline import (
        bracket_stage_labels, bracket_stage_order)
    return JSONResponse({
        "chronological_rounds": build_chronological_matches().get("rounds", []),
        "knockout_tree": build_knockout_tree(),
        "stage_order": bracket_stage_order(),
        "stage_labels": bracket_stage_labels(),
    })


@wc_app.get("/api/evaluation")
def api_evaluation():
    return JSONResponse(cache.get("evaluation", {}))


@wc_app.get("/api/signals")
def api_signals():
    return JSONResponse(compute_signal_stats())


@wc_app.get("/api/signal/{name}")
def api_signal_detail(name: str):
    return JSONResponse(compute_signal_detail(name))


@wc_app.get("/api/blend")
def api_blend():
    return JSONResponse(compute_blend_info())



def simulation_eligibility() -> tuple[bool, Optional[str], str]:
    """Shared eligibility truth (adapter + handler both use this)."""
    remaining = unplayed_match_count()
    if remaining == 0:
        return False, "no_unplayed_matches", (
            "All competition results are already known from real match "
            "data. Simulation is not needed.")
    return True, None, ""


def has_simulation() -> bool:
    return bool(sim_cache.get("status") == "completed")


def _run_wc_simulation(progress_cb, count: int, seed: Optional[int],
                       weights=None, show_ci: str = "auto") -> dict:
    from competitions.worldcup.src.pipeline import run_simulation_compute
    return run_simulation_compute(
        DATA_DIR, iterations=count, seed=seed, weights=weights,
        bsd_api_key=BSD_API_KEY, football_data_org_key=FOOTBALL_DATA_ORG_KEY,
        progress_cb=progress_cb,
    )


def _store_wc_sim_result(result: dict, count: int, seed: Optional[int],
                         weights=None, show_ci: str = "auto") -> dict:
    """Cache/snapshot side effects. Returns the public task summary."""
    global sim_cache
    remaining = unplayed_match_count()
    sim_meta = result.get("simulation_meta", {})
    overview = result["overview"]
    sim_cache = {
        "top_teams": result["top_teams"][:20],
        "signal_eval": result["eval_metrics"],
        "simulation_meta": build_simulation_meta(
            requested_count=count,
            actual_count=sim_meta.get("n_simulations", count),
            seed=sim_meta.get("seed"),
            provenance_extra=sim_meta.get("provenance") or {},
            engine_version=sim_meta.get("engine_version"),
            extra={
                "weights": weights,
                "show_ci": show_ci,
                "n_top_teams": len(result["top_teams"]),
                "n_signals_evaluated": len(result["eval_metrics"]),
                "unplayed_matches": remaining,
            },
        ),
        "full_bracket": result["full_bracket"],
        "sim_result": result.get("sim_result"),
        "n_unplayed": remaining,
        "status": "completed",
    }
    snapshot = result["snapshot"]
    snapshot["show_ci"] = show_ci
    (DATA_DIR / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"n_unplayed": remaining}


@wc_app.post("/api/simulate")
def api_simulate(req: dict = None):
    if not req:
        return JSONResponse({"error": "request body required"})
    # Validate BEFORE the eligibility short-circuit: an invalid request is
    # invalid regardless of competition state (no silent clamping).
    weights = req.get("weights")
    show_ci = str(req.get("show_ci", "auto"))
    http_status, payload = service.start(
        competition_id="worldcup",
        raw_count=req.get("iterations"),
        default_count=50000,
        seed=req.get("seed"),
        runner=lambda pcb, count, seed_: _run_wc_simulation(
            pcb, count, seed_, weights, show_ci),
        eligibility_fn=simulation_eligibility,
        on_result=lambda res, count, seed_: _store_wc_sim_result(
            res, count, seed_, weights, show_ci),
        options={"weights": weights, "show_ci": show_ci},
        extra_ack={"n_unplayed": unplayed_match_count()},
    )
    return JSONResponse(payload, status_code=http_status)


@wc_app.get("/api/validation")
def api_validation():
    try:
        teams_raw = load_json(DATA_DIR, "teams.json")
        groups_raw = load_groups(DATA_DIR, teams=teams_raw)
        bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
        annex_c = load_annex_c(DATA_DIR)
        played_raw = json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {}
        played_groups_raw = (DATA_DIR / "played_groups.json").read_text(encoding="utf-8")
        played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}

        result = run_calibrated_validation(
            teams_raw, groups_raw, bracket_raw, annex_c,
            played_raw, played_groups, str(DATA_DIR),
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@wc_app.get("/api/report")
def api_report():
    snapshot_path = DATA_DIR / "snapshot.json"
    if not snapshot_path.exists():
        return JSONResponse({"error": "no snapshot available — run a simulation first"})
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _simulate_from_match_sync(match_id: str, iterations: int = 10000) -> dict:
    """Run a full simulation and extract probabilities for target + downstream matches."""
    from competitions.worldcup.src.pipeline import simulate_from_match as _pipeline_sim
    return _pipeline_sim(match_id, DATA_DIR, iterations=iterations)


def _collect_downstream_matches(target_id: str, bracket_raw: list) -> list[str]:
    """Collect all downstream matches reachable from target_id via source_matches."""
    from competitions.worldcup.src.pipeline import collect_downstream_matches as _pipeline_collect
    return _pipeline_collect(target_id, bracket_raw)


@wc_app.post("/api/simulate-from-match")
def api_simulate_from_match(req: dict = None):
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    raw_iterations = req.get("iterations", 10000)
    if raw_iterations is None:
        raw_iterations = 10000
    try:
        from football_core.simulation import (
            SimulationContractError,
            validate_n_simulations,
        )
        iterations = validate_n_simulations(int(raw_iterations))
    except SimulationContractError as exc:
        return JSONResponse({"status": "validation_error",
                             "error": str(exc)}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"status": "validation_error",
                             "error": f"iterations must be an integer: {raw_iterations!r}"},
                            status_code=400)
    if not match_id:
        return JSONResponse({"error": "match_id required"})

    try:
        result = _simulate_from_match_sync(match_id, iterations)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@wc_app.get("/api/match/insight")
def api_match_insight(match_id: str = ""):
    if not match_id:
        return JSONResponse({"error": "match_id parameter required"})
    fb = cache.get("full_bracket", {})
    ev = cache.get("evaluation", {})
    bl = cache.get("blend_data")
    if not bl:
        bl_info = compute_blend_info()
        blend_weights = bl_info.get("blend_weights", {})
    else:
        blend_weights = bl.get("blend_weights", {})
    insight = compute_match_insight(match_id, fb, ev, blend_weights)
    return JSONResponse(insight)


@wc_app.post("/api/match/what-if")
def api_match_what_if(req: dict = None):
    """Match/tie-level What-If: adjust one team's Elo by +-delta and re-evaluate
    the single-match ensemble blend (base Elo + cache-backed refinement signals).

    Deterministic single-match prediction path — NO tournament Monte Carlo,
    no persisted state. Allowed regardless of season completion (hypothetical
    analysis on resolved pairings; factual history is never modified).

    Body: {"match_id": str, "elo_delta": int (default 50, applied +to team_a /
    -to team_b, clamped to [-600, 600], non-zero)}
    Returns baseline vs adjusted win probabilities for both teams.
    """
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    if not match_id:
        return JSONResponse({"error": "match_id required"})
    try:
        elo_delta = int(req.get("elo_delta", 50))
    except (TypeError, ValueError):
        return JSONResponse({"error": "elo_delta must be an integer"})
    if elo_delta == 0:
        return JSONResponse({"error": "elo_delta must be non-zero"})
    elo_delta = max(-600, min(600, elo_delta))

    fb = cache.get("full_bracket", {})
    match_data = None
    for r, ms in fb.get("rounds", {}).items():
        for m in ms:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break
    if not match_data:
        return JSONResponse({"error": "match not found in bracket"})
    ta = match_data.get("team_a", "")
    tb = match_data.get("team_b", "")
    if not ta or not tb:
        return JSONResponse({"error": "bracket slot unresolved"})

    try:
        from football_core.signal import PredictionContext
        from competitions.worldcup.src.engine import build_engine_from_caches

        teams_raw = load_json(DATA_DIR, "teams.json")
        baseline_elos = {n: float(d.get("elo", 1500)) for n, d in teams_raw.items()}
        adjusted_elos = dict(baseline_elos)
        adjusted_elos[ta] = baseline_elos.get(ta, 1500.0) + elo_delta
        adjusted_elos[tb] = max(100.0, baseline_elos.get(tb, 1500.0) - elo_delta)

        engine = build_engine_from_caches()
        fixture = {"team_a": ta, "team_b": tb, "match_id": match_id}

        def _evaluate(elo_ratings):
            ctx = PredictionContext(fixtures=[fixture], elo_ratings=elo_ratings)
            return engine.evaluate(fixture, ctx)

        base_bp = _evaluate(baseline_elos)
        adj_bp = _evaluate(adjusted_elos)
    except Exception as e:
        return JSONResponse({"error": f"what-if evaluation failed: {e}"})

    def _entry(base_p, adj_p):
        return {"baseline": round(base_p, 4), "adjusted": round(adj_p, 4),
                "delta": round(adj_p - base_p, 4)}

    def _outcome(bp):
        return {"a_win": round(bp.home_prob, 4),
                "draw": round(bp.draw_prob, 4),
                "b_win": round(bp.away_prob, 4)}

    return JSONResponse({
        "mode": "match",
        "match_id": match_id,
        "round": match_data.get("round"),
        "teams": {ta: _entry(base_bp.home_prob, adj_bp.home_prob),
                  tb: _entry(base_bp.away_prob, adj_bp.away_prob)},
        "outcome_baseline": _outcome(base_bp),
        "outcome_adjusted": _outcome(adj_bp),
        "elo_changes": {ta: round(adjusted_elos[ta], 1),
                        tb: round(adjusted_elos[tb], 1)},
        "note": ("Deterministic single-match ensemble blend (Elo + refinement "
                 "signals). No tournament Monte Carlo was run."),
    })


@wc_app.post("/api/what-if")
def api_what_if(req: dict = None):
    """Structured counterfactual: adjust one team's Elo by +-delta, re-run seeded MC.

    Body: {"match_id": str, "elo_delta": int (default 50, applied +to team_a / -to team_b),
           "iterations": int (default 10000, capped at 50000)}
    Returns baseline vs adjusted champion probabilities.
    """
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    if not match_id:
        return JSONResponse({"error": "match_id required"})
    try:
        from football_core.simulation import (
            SimulationContractError,
            validate_n_simulations,
        )
        elo_delta = int(req.get("elo_delta", 50))
        iterations = validate_n_simulations(int(req.get("iterations") or 10000))
    except SimulationContractError as exc:
        return JSONResponse({"status": "validation_error", "error": str(exc)},
                            status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "elo_delta/iterations must be integers"})
    if elo_delta == 0:
        return JSONResponse({"error": "elo_delta must be non-zero"})
    elo_delta = max(-600, min(600, elo_delta))

    fb = cache.get("full_bracket", {})
    match_data = None
    for r, ms in fb.get("rounds", {}).items():
        for m in ms:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break
    if not match_data:
        return JSONResponse({"error": "match not found in bracket"})
    ta = match_data.get("team_a", "")
    tb = match_data.get("team_b", "")
    if not ta or not tb:
        return JSONResponse({"error": "bracket slot unresolved"})

    teams_raw = load_json(DATA_DIR, "teams.json")
    groups_raw = load_groups(DATA_DIR, teams=teams_raw)
    bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
    annex_c = load_annex_c(DATA_DIR)
    played_raw = json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {}
    played_groups_raw = (DATA_DIR / "played_groups.json").read_text(encoding="utf-8")
    played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}

    def _sim(teams):
        return run_full_simulation(
            teams, groups_raw, bracket_raw, annex_c, played_raw,
            iterations=iterations, seed=42, played_groups=played_groups,
        )

    baseline = _sim(teams_raw)
    adjusted_teams = json.loads(json.dumps(teams_raw))
    adjusted_teams[ta]["elo"] = adjusted_teams[ta]["elo"] + elo_delta
    adjusted_teams[tb]["elo"] = max(100.0, adjusted_teams[tb]["elo"] - elo_delta)
    adjusted = _sim(adjusted_teams)

    def _entry(name):
        b = baseline.get(name, {}).get("champion", 0.0)
        a = adjusted.get(name, {}).get("champion", 0.0)
        return {"baseline": round(b, 4), "adjusted": round(a, 4),
                "delta": round(a - b, 4)}

    def _top5(result):
        ranked = sorted(result.items(), key=lambda kv: kv[1].get("champion", 0), reverse=True)[:5]
        return [{"team": t, "champion": round(v.get("champion", 0), 4)} for t, v in ranked]

    return JSONResponse({
        "mode": "structured",
        "match_id": match_id,
        "elo_changes": {ta: adjusted_teams[ta]["elo"], tb: adjusted_teams[tb]["elo"]},
        "iterations": iterations,
        "teams": {ta: _entry(ta), tb: _entry(tb)},
        "top5_baseline": _top5(baseline),
        "top5_adjusted": _top5(adjusted),
    })


def _run_calibration_runner(progress_cb, count, seed):
    from competitions.worldcup.src.pipeline import run_calibration_compute
    return run_calibration_compute(
        DATA_DIR,
        bsd_api_key=BSD_API_KEY,
        football_data_org_key=FOOTBALL_DATA_ORG_KEY,
        progress_cb=progress_cb,
    )


def _store_calibration_result(result, count, seed) -> dict:
    blend_params = result.get("blend_params")
    if not blend_params:
        raise SimulationContractError(
            "insufficient labeled history to fit weights")
    return {"weights": (blend_params or {}).get("weights")}


@wc_app.post("/api/calibrate")
def api_calibrate(req: dict = None):
    http_status, payload = service.start(
        competition_id="worldcup",
        raw_count=100,
        default_count=100,
        seed=None,
        runner=_run_calibration_runner,
        eligibility_fn=lambda: (True, None, ""),
        on_result=_store_calibration_result,
        extra_ack={"kind": "calibration"},
    )
    payload.pop("count", None)
    payload.pop("requested_count", None)
    return JSONResponse(payload, status_code=http_status)


@wc_app.get("/api/simulation/progress/{task_id}")
def api_simulation_progress(task_id: str):
    return JSONResponse(service.poll(task_id))
