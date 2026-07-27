"""UCL 2025/26 — FastAPI sub-app mounted under /ucl."""

from __future__ import annotations

import json
import os
import random
import re
import sys
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import fastapi
import requests
import uvicorn
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from competitions.ucl.src.orchestrator import build_simulation_result, build_signal_engine, load_calibration, run_validation
from competitions.ucl.src.pipeline import (
    fetch_ucl_managers as _fetch_ucl_managers_pipeline,
    compute_deterministic_standings as _compute_deterministic_standings_pipeline,
    build_deterministic_bracket as _build_deterministic_bracket_pipeline,
    compute_signal_eval as _compute_signal_eval_pipeline,
    load_results as _load_results_pipeline,
    load_knockout_results as _load_knockout_results_pipeline,
    build_league_matchdays as _build_league_matchdays_pipeline,
    ucl_form_trend as _ucl_form_trend_pipeline,
    ucl_head_to_head as _ucl_head_to_head_pipeline,
    ucl_outcome_dist as _ucl_outcome_dist_pipeline,
    ucl_insight_text as _ucl_insight_text_pipeline,
    run_mc_simulation as _run_mc_simulation_pipeline,
    run_calibration_task as _run_calibration_task_pipeline,
)
from competitions.ucl.src.analysis import run_validation_suite, run_calibrated_validation
from competitions.ucl.src.calibrate import run_calibration
from competitions.ucl.result import SimulationResult
from competitions.ucl.src.elo_fetcher import fetch_team_elos, get_clubelo_snapshot_date
from competitions.ucl.src.provider import RepoFixtureProvider
from competitions.ucl.src.groups import compute_swiss_standings
from football_core.blender import compute_signal_contributions
from football_core.constants import EXPECTED_GOALS_BASE_RATE
from football_core.elo import expected_score
from football_core.signal import PredictionContext

from web.common import ts, boot_step
from web.whatif_engine import handle_instant_scenario, parse_scenario

BSD_API_KEY: str = os.environ.get("BSD_API_KEY", "")
FOOTBALL_DATA_ORG_KEY: str = os.environ.get("FOOTBALL_DATA_ORG_KEY", "")
UCL_LEAGUE_ID: int = 7

_BSD_TEAM_ALIASES: dict[str, str] = {
    "Real Madrid": "Real Madrid",
    "FC Bayern M\u00fcnchen": "Bayern",
    "Liverpool FC": "Liverpool",
    "Inter": "Inter",
    "Chelsea": "Chelsea",
    "Borussia Dortmund": "Dortmund",
    "FC Barcelona": "Barcelona",
    "Arsenal": "Arsenal",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Benfica": "Benfica",
    "Atalanta": "Atalanta",
    "Villarreal": "Villarreal",
    "Juventus": "Juventus",
    "Eintracht Frankfurt": "Frankfurt",
    "Club Brugge KV": "Brugge",
    "Tottenham Hotspur": "Tottenham",
    "PSV Eindhoven": "PSV",
    "AFC Ajax": "Ajax",
    "SSC Napoli": "Napoli",
    "Sporting CP": "Sporting",
    "Olympiacos FC": "Olympiacos",
    "Olympique de Marseille": "Marseille",
    "AS Monaco": "Monaco",
    "Galatasaray": "Galatasaray",
    "Athletic Club": "Athletic",
    "Newcastle United": "Newcastle",
    "Pafos FC": "Pafos",
    "Kairat Almaty": "Kairat",
    "Paris Saint-Germain": "PSG",
    "Paris SG": "PSG",
    "Manchester City": "Man City",
    "Atl\u00e9tico Madrid": "Atletico",
    "SK Slavia Praha": "Slavia Prague",
    "Slavia Prague": "Slavia Prague",
    "Bodo/Glimt": "Bodoe Glimt",
    "FC K\u00f8benhavn": "Copenhagen",
    "FC Kobenhavn": "Copenhagen",
    "Royale Union Saint-Gilloise": "Union SG",
    "Qarabag FK": "Qarabag",
}

DATA_DIR = Path(__file__).parent.parent / "competitions" / "ucl" / "data"
UCL_DIR = Path(__file__).parent.parent / "competitions" / "ucl"

cache: dict = {}
sim_cache: dict = {}
boot_log_local: list[dict] = []
sim_result: SimulationResult | None = None
_mode: str = "results"

active_simulations: dict[str, dict] = {}
sim_lock = threading.Lock()


def _parse_what_if_scenario(scenario: str, match: dict) -> dict | None:
    ta = match.get("team_a", "")
    tb = match.get("team_b", "")
    text = scenario.lower()
    deltas: dict[str, float] = {}
    for team, direction, base_delta in [
        (ta, ["stronger", "boosted", "improved", "better", "upgraded", "advantage", "favorite"], 50),
        (ta, ["weaker", "injured", "suspended", "down", "struggling", "worse", "underdog"], -50),
        (tb, ["stronger", "boosted", "improved", "better", "upgraded", "advantage", "favorite"], 50),
        (tb, ["weaker", "injured", "suspended", "down", "struggling", "worse", "underdog"], -50),
    ]:
        for kw in direction:
            if kw in text:
                name_key = team.lower().replace(" ", "")
                text_key = text.replace(" ", "")
                if name_key in text_key:
                    delta = base_delta
                    if "very" in text or "significantly" in text or "major" in text:
                        delta = int(delta * 2)
                    if "slightly" in text or "somewhat" in text or "a bit" in text:
                        delta = int(delta * 0.5)
                    deltas[team] = deltas.get(team, 0) + delta
    return deltas if deltas else None


def _get_ucl_data_provider():
    """Select UCL data provider — BSD or football-data.org."""
    from football_core.data_providers.bsd_provider import BSDDataProvider
    from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider

    mode = os.environ.get("DATA_PROVIDER", "").lower()

    if mode == "bsd" and BSD_API_KEY:
        return BSDDataProvider(BSD_API_KEY, league_id=UCL_LEAGUE_ID)
    if mode == "football-data" and FOOTBALL_DATA_ORG_KEY:
        return FootballDataOrgProvider(FOOTBALL_DATA_ORG_KEY)

    if BSD_API_KEY:
        return BSDDataProvider(BSD_API_KEY, league_id=UCL_LEAGUE_ID)
    if FOOTBALL_DATA_ORG_KEY:
        return FootballDataOrgProvider(FOOTBALL_DATA_ORG_KEY)
    return None


def _fetch_ucl_managers() -> dict[str, dict]:
    return _fetch_ucl_managers_pipeline(BSD_API_KEY, team_aliases=_BSD_TEAM_ALIASES)


def _fetch_live_data() -> None:
    import logging
    logger = logging.getLogger(__name__)

    provider = _get_ucl_data_provider()
    if provider is None:
        logger.warning("[UCL] No data provider — skipping live fetch")
        boot_log_local.append({"step": "UCL live fetch", "status": "skip", "elapsed": 0.0, "output": f"[{ts()}] No data provider configured"})
        return

    raw = provider.fetch_matches(competition_id="CL")
    if not raw:
        logger.warning("[UCL] No matches returned from provider")
        boot_log_local.append({"step": "UCL live fetch", "status": "skip", "elapsed": 0.0, "output": f"[{ts()}] Provider returned 0 matches"})
        return

    logger.info("[UCL] Fetched %d raw matches from %s", len(raw), type(provider).__name__)

    # Build alias lookup
    from football_core.fetcher import _build_alias_lookup, normalize_team
    aliases_path = DATA_DIR / "team_aliases.json"
    aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    alias_lookup = _build_alias_lookup(aliases, bracket=[])

    fixtures_path = DATA_DIR / "fixtures.json"
    if not fixtures_path.exists():
        logger.warning("[UCL] No fixtures.json — cannot process matches")
        return
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    for team in fixtures.get("schedule", {}).get("teams", []):
        alias_lookup[team["name"].strip().lower()] = team["name"]

    # Build fixture lookup for league phase
    fixture_lookup: dict[tuple[str, str], str] = {}
    for md in fixtures.get("schedule", {}).get("matchdays", []):
        for match in md:
            pair = (match["team_a"], match["team_b"])
            fixture_lookup[pair] = match["match_id"]
            fixture_lookup[(match["team_b"], match["team_a"])] = match["match_id"]

    KO_STAGE_MAP = {
        "PLAYOFFS": "playoff",
        "LAST_16": "R16",
        "QUARTER_FINALS": "QF",
        "SEMI_FINALS": "SF",
        "FINAL": "FINAL",
    }

    results_path = DATA_DIR / "results.json"
    existing_results = _load_results()
    existing_by_id = {m["match_id"]: m for m in existing_results}

    ko_path = DATA_DIR / "knockout_results.json"
    knockout_raw = _load_knockout_results() or {}
    knockout = {
        "playoff": knockout_raw.get("playoff", []),
        "rounds": knockout_raw.get("rounds", {"R16": [], "QF": [], "SF": [], "FINAL": []}),
    }

    ko_legs: dict[str, dict[frozenset, list[dict]]] = {s: {} for s in KO_STAGE_MAP}
    n_new = 0

    for event in raw:
        status = (event.get("status") or "").lower()
        if status != "finished":
            continue

        home_name = event.get("home_team", "")
        away_name = event.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.debug("[UCL] Unmatchable teams: %r vs %r", home_name, away_name)
            continue

        home_score = event.get("home_score") or 0
        away_score = event.get("away_score") or 0
        stage = event.get("stage", "")

        if stage == "LEAGUE_STAGE":
            match_id = fixture_lookup.get((home_norm, away_norm))
            if match_id is None:
                logger.debug("[UCL] No league fixture for %s vs %s", home_norm, away_norm)
                continue
            updated = False
            if match_id in existing_by_id:
                entry = existing_by_id[match_id]
                if entry["home_score"] != home_score or entry["away_score"] != away_score:
                    entry["home_score"] = home_score
                    entry["away_score"] = away_score
                    updated = True
            else:
                existing_results.append({
                    "match_id": match_id, "team_a": home_norm, "team_b": away_norm,
                    "home_score": home_score, "away_score": away_score,
                })
                updated = True
            if updated:
                n_new += 1
                logger.info("[UCL] League %s: %s %d-%d %s", match_id, home_norm, home_score, away_score, away_norm)
        elif stage in KO_STAGE_MAP:
            ko_legs[stage].setdefault(frozenset([home_norm, away_norm]), []).append({
                "home": home_norm, "away": away_norm,
                "home_score": home_score, "away_score": away_score,
            })

    # Process knockout legs — aggregate per team pair
    for api_stage, ties in ko_legs.items():
        internal_round = KO_STAGE_MAP[api_stage]
        for pair, legs in ties.items():
            scores: dict[str, int] = {}
            for leg in legs:
                scores[leg["home"]] = scores.get(leg["home"], 0) + leg["home_score"]
                scores[leg["away"]] = scores.get(leg["away"], 0) + leg["away_score"]

            if internal_round == "playoff":
                for entry in knockout["playoff"]:
                    if {entry["team_a"], entry["team_b"]} == pair:
                        agg_a = scores.get(entry["team_a"], 0)
                        agg_b = scores.get(entry["team_b"], 0)
                        w = entry["team_a"] if agg_a > agg_b else (entry["team_b"] if agg_b > agg_a else None)
                        if entry.get("aggregate_a") != agg_a or entry.get("aggregate_b") != agg_b:
                            entry["aggregate_a"] = agg_a
                            entry["aggregate_b"] = agg_b
                            entry["winner"] = w or entry.get("winner", "")
                            n_new += 1
                            logger.info("[UCL] Playoff %s vs %s: %d-%d", entry["team_a"], entry["team_b"], agg_a, agg_b)
                        break
            else:
                for entry in knockout["rounds"].get(internal_round, []):
                    if {entry["team_a"], entry["team_b"]} == pair:
                        agg_a = scores.get(entry["team_a"], 0)
                        agg_b = scores.get(entry["team_b"], 0)
                        w = entry["team_a"] if agg_a > agg_b else (entry["team_b"] if agg_b > agg_a else None)
                        if entry.get("score_a") != agg_a or entry.get("score_b") != agg_b:
                            entry["score_a"] = agg_a
                            entry["score_b"] = agg_b
                            entry["winner"] = w or entry.get("winner", "")
                            n_new += 1
                            logger.info("[UCL] %s %s vs %s: %d-%d", internal_round, entry["team_a"], entry["team_b"], agg_a, agg_b)
                        break

    # Write updated files
    if n_new > 0:
        results_path.write_text(
            json.dumps({"matches": existing_results}, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        final_entries = knockout["rounds"].get("FINAL", [])
        if final_entries and final_entries[0].get("winner"):
            knockout_raw["champion"] = final_entries[0]["winner"]
        ko_path.write_text(
            json.dumps({"matches": knockout_raw}, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        logger.info("[UCL] Updated %d matches — files saved", n_new)

    # Update last_refresh.json
    refresh_path = Path(__file__).parent / "last_refresh.json"
    refresh_data = {}
    if refresh_path.exists():
        try:
            refresh_data = json.loads(refresh_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    refresh_data["ucl"] = {
        "last_refresh": datetime.now(timezone.utc).isoformat(),
        "mode": type(provider).__name__,
        "n_matches": len(raw),
        "n_updated": n_new,
    }
    refresh_path.write_text(
        json.dumps(refresh_data, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    boot_log_local.append({
        "step": "UCL live fetch", "status": "ok", "elapsed": 0.0,
        "output": f"[{ts()}] {type(provider).__name__}: {len(raw)} raw matches, {n_new} updated",
    })


def _load_results() -> list[dict]:
    return _load_results_pipeline(DATA_DIR)


def _load_knockout_results() -> dict | None:
    return _load_knockout_results_pipeline(DATA_DIR)


def _unplayed_match_count() -> int:
    """Count UCL matches that haven't been played yet."""
    fixtures_path = DATA_DIR / "fixtures.json"
    if not fixtures_path.exists():
        return 0
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    all_ids = set()
    for md in fixtures.get("schedule", {}).get("matchdays", []):
        for m in md:
            if m.get("match_id"):
                all_ids.add(m["match_id"])
    results = _load_results() or []
    knockout = _load_knockout_results() or {}
    played_ids = {m["match_id"] for m in results if m.get("winner") and m.get("match_id")}
    for round_matches in knockout.get("rounds", {}).values():
        for m in round_matches:
            mid = m.get("match_id")
            if m.get("winner") and mid:
                played_ids.add(mid)
    for m in knockout.get("playoff", []):
        mid = m.get("match_id")
        if m.get("winner") and mid:
            played_ids.add(mid)
    return len(all_ids - played_ids)


def _compute_deterministic_standings(results: list[dict]) -> list[dict]:
    return _compute_deterministic_standings_pipeline(results)


def _build_league_matchdays(results: list[dict]) -> dict[str, list[dict]]:
    return _build_league_matchdays_pipeline(results)


def _build_deterministic_bracket(knockout: dict, standings: list[dict]) -> dict:
    return _build_deterministic_bracket_pipeline(knockout, standings, DATA_DIR)


def _compute_signal_eval(results: list[dict], engine, elo_ratings: dict[str, float], bsd_manager_data: dict) -> dict:
    return _compute_signal_eval_pipeline(results, engine, elo_ratings, bsd_manager_data)


def deterministic_compute() -> dict:
    global boot_log_local, _mode
    boot_log_local = []
    _mode = "results"
    from competitions.ucl.src.orchestrator import run_deterministic_compute as _f
    result = _f(str(DATA_DIR), bsd_api_key=BSD_API_KEY)
    boot_log_local = result.get("boot", [])
    return result


def _was_in_semis(team: str, knockout: dict) -> bool:
    for m in knockout.get("rounds", {}).get("SF", []):
        if team in (m.get("team_a"), m.get("team_b")):
            return True
    return False


def _was_in_qf(team: str, knockout: dict) -> bool:
    for m in knockout.get("rounds", {}).get("QF", []):
        if team in (m.get("team_a"), m.get("team_b")):
            return True
    return False


def compute_all() -> dict:
    results_path = DATA_DIR / "results.json"
    ko_path = DATA_DIR / "knockout_results.json"
    if results_path.exists() and ko_path.exists():
        return deterministic_compute()
    global boot_log_local, sim_result, _mode
    _mode = "simulation"
    boot_log_local = []
    from competitions.ucl.src.orchestrator import run_compute_all as _f
    result = _f(str(DATA_DIR), bsd_api_key=BSD_API_KEY, team_aliases=_BSD_TEAM_ALIASES)
    boot_log_local = result.get("boot", [])
    sim_result = None
    return result


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    global cache
    _fetch_live_data()
    cache = compute_all()
    yield


ucl_app = fastapi.FastAPI(lifespan=lifespan)


@ucl_app.get("/api/data")
def api_data():
    return JSONResponse({
        "teams": cache.get("teams", []),
        "all_teams": cache.get("all_teams", []),
        "n_teams": cache.get("n_teams", 0),
        "n_iterations": cache.get("n_iterations", 0),
        "snapshot_date": cache.get("snapshot_date", ""),
        "champion": cache.get("champion"),
        "mode": _mode,
        "n_unplayed": _unplayed_match_count(),
    })


@ucl_app.get("/api/boot")
def api_boot():
    return JSONResponse(cache.get("boot", []))


@ucl_app.get("/api/simulation")
def api_simulation():
    return JSONResponse({
        "odds": sim_cache.get("odds", []),
        "standings": sim_cache.get("standings", []),
        "signals": sim_cache.get("signals", {}),
        "elo_ratings": sim_cache.get("elo_ratings", {}),
        "champion": sim_cache.get("champion"),
        "mode": sim_cache.get("mode", _mode),
        "n_iterations": sim_cache.get("n_iterations", 0),
        "snapshot_date": sim_cache.get("snapshot_date", ""),
        "status": sim_cache.get("status", "none"),
    })


@ucl_app.get("/api/standings")
def api_standings():
    return JSONResponse({"standings": cache.get("standings", []), "mode": _mode})


@ucl_app.get("/api/bracket")
def api_bracket():
    return JSONResponse({
        "playoff": cache.get("playoff", []),
        "bracket_rounds": cache.get("bracket_rounds", {}),
        "league_matchdays": cache.get("league_matchdays", {}),
        "champion": cache.get("champion"),
        "mode": _mode,
    })


@ucl_app.get("/api/odds")
def api_odds():
    return JSONResponse({"odds": cache.get("odds", []), "mode": _mode})


@ucl_app.get("/api/signals")
def api_signals():
    return JSONResponse({"signals": cache.get("signals", {}), "mode": _mode})


@ucl_app.post("/api/simulate")
def api_simulate(req: dict = None):
    global _mode
    remaining = _unplayed_match_count()
    if remaining == 0:
        global sim_cache
        sim_cache = {"status": "no_unplayed_matches", "message": "All matches have been played. Nothing to simulate."}
        return JSONResponse({
            "status": "no_unplayed_matches",
            "message": "All matches have been played. Nothing to simulate.",
            "n_unplayed": 0,
        })
    _mode = "simulation"
    task_id = str(uuid.uuid4())
    body = req or {}
    n_iterations = max(10, min(1000000, int(body.get("iterations") or body.get("n_iterations") or 10000)))
    seed = body.get("seed")
    if seed is not None:
        seed = int(seed)
    weights = body.get("weights")
    show_ci = str(body.get("show_ci", "auto"))
    with sim_lock:
        active_simulations[task_id] = {
            "status": "starting", "progress": 0, "iteration": 0,
            "total_iterations": n_iterations, "error": None, "result": None,
        }

    def _task(tid):
        try:
            def on_progress(pct, iteration):
                with sim_lock:
                    s = active_simulations.get(tid)
                    if s:
                        s["status"] = "running"
                        s["progress"] = pct
                        if iteration:
                            s["iteration"] = iteration
            _run_mc_simulation(progress_cb=on_progress, n_iterations=n_iterations, seed=seed, weights=weights, show_ci=show_ci)
            with sim_lock:
                s = active_simulations.get(tid)
                if s:
                    s["status"] = "complete"
                    s["progress"] = 100.0
                    s["iteration"] = n_iterations
        except Exception as e:
            with sim_lock:
                s = active_simulations.get(tid)
                if s:
                    s["status"] = "error"
                    s["error"] = str(e)

    t = threading.Thread(target=_task, args=(task_id,), daemon=True)
    t.start()
    return JSONResponse({
        "status": "ok", "task_id": task_id, "mode": _mode,
        "seed": seed, "weights": weights, "show_ci": show_ci,
        "n_unplayed": remaining,
    })



def _run_mc_simulation(
    progress_cb=None,
    n_iterations=10000,
    seed: int | None = None,
    weights: dict[str, float] | None = None,
    show_ci: str = "auto",
):
    global boot_log_local, sim_result, _mode, sim_cache
    _mode = "simulation"
    boot_log_local = []
    result = _run_mc_simulation_pipeline(
        str(DATA_DIR), n_iterations=n_iterations, seed=seed,
        weights=weights, show_ci=show_ci, bsd_api_key=BSD_API_KEY,
        team_aliases=_BSD_TEAM_ALIASES, progress_cb=progress_cb,
    )
    sim_result = None
    result["boot"] = boot_log_local
    sim_cache = result
    # Write snapshot
    snapshot_path = DATA_DIR / "snapshot.json"
    snapshot_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": result.get("mode", "simulation"),
        "iterations": n_iterations,
        "seed": seed,
        "weights": weights,
        "show_ci": show_ci,
        "n_teams": result.get("n_teams", 0),
        "champion": result.get("champion"),
        "snapshot_date": result.get("snapshot_date", ""),
        "odds": result.get("odds", []),
        "standings": result.get("standings", []),
        "signals": result.get("signals", {}),
        "elo_ratings": result.get("elo_ratings", {}),
        "calibration": load_calibration(),
    }
    snapshot_path.write_text(
        json.dumps(snapshot_data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )


@ucl_app.post("/api/mode")
def api_set_mode(req: dict = None):
    global _mode
    body = req or {}
    mode = str(body.get("mode", "simulate")).lower()
    if mode not in ("simulate", "replay", "live"):
        return JSONResponse({"error": f"invalid mode: {mode}. Must be simulate, replay, or live"})
    _mode = mode
    if mode == "replay":
        replay_data = body.get("replay_data")
        if replay_data:
            cache["_replay_data"] = replay_data
    if mode == "live":
        api_key = body.get("api_key")
        if api_key:
            cache["_bsd_api_key"] = api_key
    return JSONResponse({"status": "ok", "mode": _mode})


@ucl_app.get("/api/mode")
def api_get_mode():
    return JSONResponse({"mode": _mode})


@ucl_app.post("/api/reset")
def api_reset():
    global cache, _mode
    try:
        cache = compute_all()
        return JSONResponse({"status": "ok", "mode": _mode})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)})


@ucl_app.post("/api/refresh")
def api_refresh():
    global cache, _mode
    try:
        _fetch_live_data()
        cache = compute_all()
        return JSONResponse({"status": "ok", "mode": _mode, "refreshed": True})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)})


def _run_calibration_task(task_id: str, replay_data: str | None = None):
    """Background calibration: run run_calibration and save weights."""
    try:
        t0 = time.time()
        with sim_lock:
            active_simulations[task_id] = {
                "status": "running", "progress": 0, "stage": "Loading replay data...",
                "t0": t0, "elapsed": 0, "total_iterations": 100,
            }

        def _progress(pct, stage):
            with sim_lock:
                s = active_simulations.get(task_id)
                if s:
                    s["progress"] = pct
                    s["stage"] = stage
                    s["elapsed"] = time.time() - t0

        result = _run_calibration_task_pipeline(
            str(DATA_DIR), replay_data=replay_data, progress_cb=_progress,
        )

        calib = load_calibration()
        with sim_lock:
            s = active_simulations.get(task_id)
            if s:
                s["status"] = "complete"
                s["progress"] = 100
                s["elapsed"] = time.time() - t0
                s["result"] = {
                    "status": "ok",
                    "n_matches": result.get("n_matches", 0),
                    "weights": result.get("weights", {}),
                    "per_signal": result.get("per_signal", {}),
                    "calibration": calib,
                }
    except Exception as e:
        with sim_lock:
            s = active_simulations.get(task_id)
            if s:
                s["status"] = "error"
                s["error"] = str(e)
                s["elapsed"] = time.time() - t0


@ucl_app.post("/api/calibrate")
def api_calibrate(req: dict = None):
    body = req or {}
    replay_data = body.get("replay_data")
    task_id = str(uuid.uuid4())
    t = threading.Thread(target=_run_calibration_task, args=(task_id, replay_data), daemon=True)
    t.start()
    return JSONResponse({"task_id": task_id, "status": "started"})


@ucl_app.get("/api/validation")
def api_validation():
    try:
        results = _load_results()
        if not results:
            return JSONResponse({"error": "no results data available", "validation": None})

        elo_ratings = cache.get("elo_ratings", {})
        if not elo_ratings:
            team_names = list({m["team_a"] for m in results} | {m["team_b"] for m in results})
            elo_ratings = fetch_team_elos(team_names) or {}

        sim_result_obj = sim_result
        if sim_result_obj:
            validation = run_validation(sim_result_obj, results, elo_ratings)
        else:
            from football_core.evaluation import compute_metrics
            from football_core.elo import expected_score
            predictions: list[float] = []
            actuals: list[float] = []
            for m in results:
                ta, tb = m["team_a"], m["team_b"]
                elo_a = elo_ratings.get(ta, 1500)
                elo_b = elo_ratings.get(tb, 1500)
                pred = expected_score(elo_a, elo_b)
                if m.get("winner") == ta:
                    actual = 1.0
                elif m.get("winner") == tb:
                    actual = 0.0
                else:
                    actual = 0.5
                predictions.append(pred)
                actuals.append(actual)
            metrics = compute_metrics(predictions, actuals)
            validation = {
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "n_matches_fetched": len(results),
                "n_matches_matched": len(predictions),
                "prediction_metrics": {
                    "brier": round(metrics["brier"], 6),
                    "log_loss": round(metrics["log_loss"], 6),
                    "accuracy": round(metrics["accuracy"], 6),
                    "n": metrics["n"],
                },
            }

        calib = load_calibration()
        return JSONResponse({
            "validation": validation,
            "calibration_available": calib is not None,
            "calibration": calib,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@ucl_app.get("/api/report")
def api_report():
    snapshot_path = DATA_DIR / "snapshot.json"
    if not snapshot_path.exists():
        return JSONResponse({"error": "no snapshot available — run a simulation first"})
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@ucl_app.get("/api/simulation/progress/{task_id}")
def api_simulation_progress(task_id: str):
    with sim_lock:
        sim = active_simulations.get(task_id)
    if not sim:
        return JSONResponse({"error": "task not found"})
    response = {
        "status": sim["status"],
        "progress": sim.get("progress", 0),
        "iteration": sim.get("iteration", 0),
        "total_iterations": sim.get("total_iterations", 0),
    }
    if sim["status"] == "complete" and sim.get("result"):
        response["result"] = sim["result"]
        if sim.get("insight"):
            response["insight"] = sim["insight"]
        with sim_lock:
            del active_simulations[task_id]
    if sim["status"] == "error":
        response["error"] = sim.get("error")
        with sim_lock:
            del active_simulations[task_id]
    return JSONResponse(response)


# ── Match insight helpers ──


def _ucl_form_trend(team: str, results: list[dict]) -> list[dict]:
    return _ucl_form_trend_pipeline(team, results)


def _ucl_head_to_head(ta: str, tb: str, results: list[dict]) -> dict:
    return _ucl_head_to_head_pipeline(ta, tb, results)


def _ucl_outcome_dist(blended_prob: float, elo_a: float, elo_b: float) -> dict:
    return _ucl_outcome_dist_pipeline(blended_prob, elo_a, elo_b)


def _ucl_insight_text(ta: str, tb: str, signals: dict, form_trends: dict, h2h: dict, outcome: dict, eval_data: dict) -> str:
    return _ucl_insight_text_pipeline(ta, tb, signals, form_trends, h2h, outcome, eval_data)


@ucl_app.get("/api/match/insight")
def api_match_insight(match_id: str = ""):
    if not match_id:
        return JSONResponse({"error": "match_id parameter required"})
    br = cache.get("bracket_rounds", {})
    match_data = None
    for r, matches in br.items():
        for m in matches:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break
    if not match_data:
        return JSONResponse({"error": "match not found"})
    ta = match_data.get("team_a", "")
    tb = match_data.get("team_b", "")
    if not ta or not tb:
        return JSONResponse({"error": "match teams not set"})

    elo_map = cache.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    elo_prob = expected_score(elo_a, elo_b)

    engine = cache.get("_signal_engine")
    signals_with_weights: dict = {}
    blended_prob = 0.5

    if engine:
        try:
            ctx = PredictionContext(
                fixtures=[{"team_a": ta, "team_b": tb, "match_id": match_id}],
                elo_ratings=elo_map,
                played_results=[],
                manager_data=cache.get("bsd_manager_data", {}),
            )
            bp = engine.evaluate({"team_a": ta, "team_b": tb, "match_id": match_id}, ctx)
            blended_prob = bp.home_prob
            for sig, sd in bp.signal_breakdown.items():
                prob = sd.get("home", 0.5)
                weight = sd.get("weight", 0)
                signals_with_weights[sig] = {
                    "probability": round(prob, 4),
                    "weight": round(weight, 4),
                    "label": sig.replace("_", " ").title(),
                }
        except Exception:
            pass

    results = cache.get("_results", [])
    form_trends: dict = {}
    h2h: dict = {"a_wins": 0, "b_wins": 0, "draws": 0, "total": 0}
    if results:
        form_trends = {ta: _ucl_form_trend(ta, results), tb: _ucl_form_trend(tb, results)}
        h2h = _ucl_head_to_head(ta, tb, results)

    outcome = _ucl_outcome_dist(blended_prob, elo_a, elo_b)
    eval_data = cache.get("signals", {})
    insight = _ucl_insight_text(ta, tb, signals_with_weights, form_trends, h2h, outcome, eval_data)

    return JSONResponse({
        "match_id": match_id,
        "round": match_data.get("round"),
        "teams": {"a": ta, "b": tb},
        "played": bool(match_data.get("winner")),
        "score": match_data.get("score"),
        "winner": match_data.get("winner"),
        "signals": signals_with_weights,
        "blended_prob": round(blended_prob, 4),
        "elo_prob": round(elo_prob, 4),
        "form_trends": form_trends,
        "head_to_head": h2h,
        "outcome_distribution": outcome,
        "insight": insight,
    })


@ucl_app.post("/api/what-if")
def api_what_if(req: dict = None):
    """What-if with instant AND simulate modes (mirrors WC pattern)."""
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    scenario = req.get("scenario", "")
    mode = req.get("mode", "instant")

    if not match_id or not scenario:
        return JSONResponse({"error": "match_id and scenario required"})

    br = cache.get("bracket_rounds", {})
    match_data = None
    for r, matches in br.items():
        for m in matches:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break

    if not match_data:
        return JSONResponse({"error": "match not found"})

    ta = match_data.get("team_a", "") or "?"
    tb = match_data.get("team_b", "") or "?"

    # Use the whatif_engine for rich response — same as WC
    elo_map = cache.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    elo_p = expected_score(elo_a, elo_b)
    elo_p = round(max(0.01, min(0.99, elo_p)), 4)

    # Build original signals from cache data
    sigs = cache.get("signals", {})
    original_signals = {}
    for sk, sv in sigs.items():
        w = sv.get("weight", 0)
        p = sv.get("avg_probability", 0.5)
        original_signals[sk] = {"probability": p, "weight": w}
    if "elo" not in original_signals:
        original_signals["elo"] = {"probability": elo_p, "weight": 0.1874}

    parsed = parse_scenario(scenario, ta, tb, {})
    if parsed.confidence == 0.0:
        return JSONResponse({"mode": mode, "error": "No meaningful scenario detected. Try describing a specific condition (e.g., 'injury', 'strong form', 'weak defense')."})
    if mode == "instant":
        result = handle_instant_scenario(scenario, ta, tb, original_signals, {}, elo_prob=elo_p)
        return JSONResponse({"mode": "instant", **result})

    elif mode == "simulate":
        task_id = str(uuid.uuid4())
        with sim_lock:
            active_simulations[task_id] = {
                "status": "starting", "progress": 0, "iteration": 0,
                "total_iterations": 0, "error": None, "result": None,
            }

        def _run_sim(task_id, scenario, match_id, ta, tb):
            try:
                with sim_lock:
                    active_simulations[task_id]["status"] = "running"
                fixtures_path = str(DATA_DIR / "fixtures.json")
                provider = RepoFixtureProvider(fixtures_path=fixtures_path).load()
                team_names = [t.name for t in provider.teams]
                elo_ratings = fetch_team_elos(team_names)
                if not elo_ratings:
                    elo_ratings = {}
                    coefficients = {t.name: t.coefficient for t in provider.teams}
                    max_coeff = max(coefficients.values()) if coefficients else 100
                    for t in team_names:
                        c = coefficients.get(t, 50)
                        elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0

                n_iterations = 10000
                with sim_lock:
                    active_simulations[task_id]["total_iterations"] = n_iterations

                def _on_progress(current, total):
                    with sim_lock:
                        pct = round(current / total * 100, 1)
                        active_simulations[task_id]["progress"] = pct
                        active_simulations[task_id]["iteration"] = current

                baseline_elos = dict(elo_ratings)
                result = build_simulation_result(
                    provider, baseline_elos, seed=42, n_iterations=n_iterations,
                    progress_cb=_on_progress,
                )

                baseline_champ_probs = {
                    t: td.get("champion_prob", 0)
                    for t, td in result.teams.items()
                }

                adjustments = handle_instant_scenario(
                    scenario, ta, tb, original_signals, {}, elo_prob=elo_p
                ).get("adjusted_signals", {})

                adj_factor = 1.0
                for sk, sv in adjustments.items():
                    if sv.get("was_adjusted"):
                        orig = original_signals.get(sk, {}).get("probability", 0.5)
                        if orig > 0:
                            adj_factor *= sv["probability"] / orig

                adjusted_elos = dict(baseline_elos)
                if ta in adjusted_elos:
                    adjusted_elos[ta] = adjusted_elos[ta] * (1.0 + 0.1 * (adj_factor - 1.0))
                if tb in adjusted_elos:
                    adjusted_elos[tb] = adjusted_elos[tb] * (1.0 - 0.1 * (adj_factor - 1.0))

                adj_result = build_simulation_result(
                    provider, adjusted_elos, seed=42, n_iterations=n_iterations,
                    progress_cb=_on_progress,
                )

                insight_parts = [f"Scenario: {scenario}"]
                for t in [ta, tb]:
                    base = baseline_champ_probs.get(t, 0)
                    adj = adj_result.teams.get(t, {}).get("champion_prob", 0)
                    delta_str = f"+{adj-base:.1%}" if adj >= base else f"{adj-base:.1%}"
                    insight_parts.append(f"{t}: {base:.1%} → {adj:.1%} ({delta_str})")

                with sim_lock:
                    active_simulations[task_id]["status"] = "complete"
                    active_simulations[task_id]["progress"] = 100.0
                    active_simulations[task_id]["iteration"] = n_iterations
                    active_simulations[task_id]["result"] = {
                        "baseline": {t: baseline_champ_probs.get(t, 0) for t in [ta, tb]},
                        "adjusted": {t: adj_result.teams.get(t, {}).get("champion_prob", 0) for t in [ta, tb]},
                    }
                    active_simulations[task_id]["insight"] = "\n>> ".join(insight_parts)
            except Exception as e:
                with sim_lock:
                    active_simulations[task_id]["status"] = "error"
                    active_simulations[task_id]["error"] = str(e)

        t = threading.Thread(target=_run_sim, args=(task_id, scenario, match_id, ta, tb), daemon=True)
        t.start()
        return JSONResponse({"mode": "simulate", "task_id": task_id, "status": "started"})

    return JSONResponse({"error": f"unknown mode: {mode}"})
