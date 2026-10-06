import json, os
import logging
from pathlib import Path
from datetime import datetime, timezone

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
from competitions.worldcup.src.evaluation import (
    compute_signal_eval, compute_team_strengths_from_predictions,
)
# Bracket, overview and signal evaluation live in the World Cup brain;
# re-exported here because the golden fixture, the truth-payload tests and the
# endpoints import these names from web.wc_app. pipeline.py now imports the
# evaluation module directly instead of reaching into web (plan 01-06, D-13).
from competitions.worldcup.src.bracket import (
    _prob_availability,
    compute_full_bracket,
)
from competitions.worldcup.src.overview import compute_overview
from web.common import boot_step, error_response, load_json
from web.simulation_service import (
    SimulationTaskService, build_simulation_meta,
)
from football_core.simulation import SimulationContractError
from typing import Optional

logger = logging.getLogger(__name__)

load_dotenv()


# Credentials are read at CALL time, never frozen at import: os.environ can
# be populated (or overridden) long after this module was imported, and a
# frozen constant would keep resolving to the empty pre-import value.
def _bsd_key() -> str:
    return os.environ.get("BSD_API_KEY", "")


def _football_data_org_key() -> str:
    return os.environ.get("FOOTBALL_DATA_ORG_KEY", "")

DATA_DIR = constants.DATA_DIR

cache: dict = {}
sim_cache: dict = {}
service = SimulationTaskService()


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
        report = _pipeline_fetch(
            _bsd_key(), _football_data_org_key(), DATA_DIR)
    except Exception:  # never let a refresh crash boot; mark stale
        logger.exception("worldcup live fetch failed")
        report = {"provider": None, "attempted": True, "success": False,
                  "error": "live refresh failed", "stale": True,
                  "finished": {}}
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


@wc_app.get("/api/elo")
def api_elo():
    """Elo table for the Elo view.

    Reads the booted team cache only: no fetch, no recompute, never a 500.
    The cache carries no rating date, so ``as_of`` stays empty rather than
    inventing one.
    """
    ratings = {
        row["name"]: float(row["elo"])
        for row in (cache.get("teams") or [])
        if isinstance(row, dict) and row.get("name")
        and isinstance(row.get("elo"), (int, float))
    }
    if not ratings:
        return JSONResponse({"ratings": {}, "source": "empty", "as_of": ""})
    return JSONResponse({"ratings": ratings, "source": "teams", "as_of": ""})


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
        bsd_api_key=_bsd_key(), football_data_org_key=_football_data_org_key(),
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
        return error_response(e, context="worldcup validation")


@wc_app.get("/api/report")
def api_report():
    snapshot_path = DATA_DIR / "snapshot.json"
    if not snapshot_path.exists():
        return JSONResponse({"error": "no snapshot available — run a simulation first"})
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return error_response(e, context="worldcup report")


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
        return error_response(e, context="worldcup simulate-from-match")


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
        return error_response(e, context="worldcup match what-if")

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
        bsd_api_key=_bsd_key(),
        football_data_org_key=_football_data_org_key(),
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
