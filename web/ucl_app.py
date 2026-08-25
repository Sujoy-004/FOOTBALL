"""UCL 2025/26 — FastAPI sub-app mounted under /ucl."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import fastapi
from fastapi.responses import JSONResponse

from competitions.ucl.src.orchestrator import (
    build_simulation_result,
    run_validation,
    _load_league_played_pairs,
)
from competitions.ucl.src.pipeline import (
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
from competitions.ucl.result import SimulationResult
from competitions.ucl.src.elo_fetcher import fetch_team_elos
from competitions.ucl.src.provider import RepoFixtureProvider
from football_core.elo import expected_score
from football_core.signal import PredictionContext

from typing import Optional

from web.common import ts
from web.simulation_service import SimulationTaskService, build_simulation_meta

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
service = SimulationTaskService()


def _store_refresh_report(ok: bool, error: str | None, provider_name: str | None,
                          n_matches: int | None = None, n_updated: int | None = None,
                          finished: dict | None = None) -> dict:
    """Record the UCL refresh outcome for the API surface + last_refresh.json."""
    global _refresh_report
    _refresh_report = {
        "provider": provider_name,
        "attempted": True,
        "success": ok,
        "error": error,
        "stale": not ok,
        "last_refresh": datetime.now(timezone.utc).isoformat(),
        **({"n_matches": n_matches} if n_matches is not None else {}),
        **({"n_updated": n_updated} if n_updated is not None else {}),
        **({"finished": finished} if finished is not None else {}),
    }
    try:
        refresh_path = Path(__file__).parent / "last_refresh.json"
        refresh_data = {}
        if refresh_path.exists():
            try:
                refresh_data = json.loads(refresh_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        entry = dict(_refresh_report)
        entry["mode"] = provider_name
        entry["n_matches"] = n_matches or 0
        entry["n_updated"] = n_updated or 0
        refresh_data["ucl"] = entry
        refresh_path.write_text(json.dumps(refresh_data, indent=2), encoding="utf-8")
    except Exception:
        pass
    return _refresh_report


_refresh_report: dict = {}


def _fetch_live_data() -> None:
    import logging
    logger = logging.getLogger(__name__)

    from web.startup import is_snapshot_mode
    if is_snapshot_mode():
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[UCL] snapshot mode - live refresh skipped")
        boot_log_local.append({"step": "UCL live fetch", "status": "skip",
                               "elapsed": 0.0,
                               "output": f"[{ts()}] Snapshot mode - live refresh skipped"})
        # Parity with WC (Exchange 4): record WHY no live fetch happened so
        # the frontend can disclose snapshot data instead of silently
        # looking live-fresh.
        globals()["_refresh_report"] = {
            "provider": None, "attempted": False, "success": True,
            "stale": True,
            "skipped_reason": "snapshot mode selected at startup",
        }
        return

    from web.common import get_data_provider
    provider = get_data_provider(BSD_API_KEY, FOOTBALL_DATA_ORG_KEY, UCL_LEAGUE_ID)
    if provider is None:
        logger.warning("[UCL] No data provider — skipping live fetch")
        boot_log_local.append({"step": "UCL live fetch", "status": "skip", "elapsed": 0.0, "output": f"[{ts()}] No data provider configured"})
        _store_refresh_report(False, "no data provider configured", None)
        return

    raw = provider.fetch_matches(competition_id="CL")
    if not raw:
        err = getattr(provider, "last_error", None) or "provider returned 0 matches"
        logger.warning("[UCL] Refresh failed: %s — UCL data may be STALE", err)
        boot_log_local.append({"step": "UCL live fetch", "status": "skip", "elapsed": 0.0, "output": f"[{ts()}] Provider returned 0 matches ({err})"})
        _store_refresh_report(False, err, type(provider).__name__)
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
    from football_core.fetcher import new_ingestion_stats, count_finished, note_unmatchable, note_no_target, summarize_ingestion
    ucl_stats = new_ingestion_stats()

    for event in raw:
        status = (event.get("status") or "").lower()
        if status != "finished":
            continue
        count_finished(ucl_stats)

        home_name = event.get("home_team", "")
        away_name = event.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            note_unmatchable(ucl_stats, logger, home_name, away_name,
                             (event.get("home_score"), event.get("away_score")))
            continue
        ucl_stats["normalized"] += 1

        home_score = event.get("home_score") or 0
        away_score = event.get("away_score") or 0
        stage = event.get("stage", "")

        if stage == "LEAGUE_STAGE":
            match_id = fixture_lookup.get((home_norm, away_norm))
            if match_id is None:
                note_no_target(ucl_stats, logger, home_norm, away_norm)
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
    summarize_ingestion(ucl_stats, logger, "UCL")
    provider_error = getattr(provider, "last_error", None)
    refresh_data["ucl"] = {
        "last_refresh": datetime.now(timezone.utc).isoformat(),
        "mode": type(provider).__name__,
        "ok": bool(raw),
        "error": provider_error,
        "stale": not bool(raw),
        "n_matches": len(raw),
        "n_updated": n_new,
        "finished": ucl_stats,
    }
    refresh_path.write_text(
        json.dumps(refresh_data, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    _store_refresh_report(True, None, type(provider).__name__,
                          n_matches=len(raw), n_updated=n_new,
                          finished=ucl_stats)
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
    return _match_counts()[0]


def _match_counts() -> tuple[int, int]:
    """Return (unplayed, total) match counts from fixtures + results."""
    fixtures_path = DATA_DIR / "fixtures.json"
    if not fixtures_path.exists():
        return 0, 0
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    all_ids = set()
    for md in fixtures.get("schedule", {}).get("matchdays", []):
        for m in md:
            if m.get("match_id"):
                all_ids.add(m["match_id"])
    results = _load_results() or []
    knockout = _load_knockout_results() or {}
    played_ids = set()
    for m in results:
        if not isinstance(m, dict) or not m.get("match_id"):
            continue
        if m.get("winner") or (m.get("home_score") is not None and m.get("away_score") is not None):
            played_ids.add(m["match_id"])
    for round_matches in knockout.get("rounds", {}).values():
        for m in round_matches:
            mid = m.get("match_id")
            if m.get("winner") and mid:
                played_ids.add(mid)
    for m in knockout.get("playoff", []):
        mid = m.get("match_id")
        if m.get("winner") and mid:
            played_ids.add(mid)
    return len(all_ids - played_ids), len(all_ids)


def _compute_deterministic_standings(results: list[dict]) -> list[dict]:
    return _compute_deterministic_standings_pipeline(results)


def _build_league_matchdays(results: list[dict]) -> dict[str, list[dict]]:
    return _build_league_matchdays_pipeline(results)


def _build_deterministic_bracket(knockout: dict, standings: list[dict]) -> dict:
    return _build_deterministic_bracket_pipeline(knockout, standings, DATA_DIR)


def _compute_signal_eval(results: list[dict], engine, elo_ratings: dict[str, float]) -> dict:
    return _compute_signal_eval_pipeline(results, engine, elo_ratings)


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
    global boot_log_local, sim_result, _mode
    from competitions.ucl.src.orchestrator import resolve_compute_mode
    mode, mode_reason = resolve_compute_mode(str(DATA_DIR))
    if mode == "results":
        return deterministic_compute()
    if mode == "error":
        # Real results exist but are unreadable: surface the failure instead
        # of fabricating a simulated season over them.
        _mode = "results"
        sim_result = None
        boot_log_local = [{"step": "Select data mode", "status": "error", "elapsed": 0.0,
                           "output": f"[error] {mode_reason}"}]
        return {"error": mode_reason, "boot": boot_log_local}
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

@ucl_app.exception_handler(Exception)
async def _json_error_handler(request, exc):
    """Never emit an empty/non-JSON body - the SPA parses every response."""
    import logging as _logging
    _logging.getLogger(__name__).error(
        "[UCL] unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse({"error": f"internal error: {exc.__class__.__name__}"},
                        status_code=500)


@ucl_app.get("/api/data")
def api_data():
    n_unplayed, n_total = _match_counts()
    return JSONResponse({
        "refresh": _refresh_report,
        "teams": cache.get("teams", []),
        "all_teams": cache.get("all_teams", []),
        "n_teams": cache.get("n_teams", 0),
        "n_iterations": cache.get("n_iterations", 0),
        "snapshot_date": cache.get("snapshot_date", ""),
        "champion": cache.get("champion"),
        "mode": _mode,
        "availability": cache.get("availability", {}),
        "phase": cache.get("phase", {}),
        "simulation": _simulation_state_block(),
        "n_unplayed": n_unplayed,
        "n_played": n_total - n_unplayed,
    })


@ucl_app.get("/api/boot")
def api_boot():
    return JSONResponse({
        "boot": cache.get("boot", []),
        "refresh": _refresh_report,
    })


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
        "status": sim_cache.get("status", "not_requested"),
        "simulation_meta": sim_cache.get("simulation_meta"),
        "bracket_rounds": sim_cache.get("bracket_rounds"),
        "playoff": sim_cache.get("playoff"),
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
    body = req or {}
    weights = body.get("weights")
    show_ci = str(body.get("show_ci", "auto"))
    raw_count = body.get("iterations")
    if raw_count is None:
        raw_count = body.get("n_iterations")

    def eligibility():
        if _season_outcome_undecided():
            return True, None, ""
        return False, "no_outstanding_outcomes", (
            "Every match has a real result and the season outcome is "
            "decided - nothing to simulate.")

    http_status, payload = service.start(
        competition_id="ucl",
        raw_count=raw_count,
        default_count=10000,
        seed=body.get("seed"),
        runner=_ucl_sim_runner,
        eligibility_fn=eligibility,
        on_result=_store_ucl_sim_result,
        options={"weights": weights, "show_ci": show_ci},
        extra_ack={"mode": "simulation", "n_unplayed": _unplayed_match_count()},
    )
    return JSONResponse(payload, status_code=http_status)


def _season_outcome_undecided() -> bool:
    """True when the real season still has undecided outcomes worth projecting.

    League matches unplayed, or knockout data missing/empty/unreadable with
    no recorded champion, both count as outstanding. A genuinely completed
    real season (champion on file) is decided.
    """
    if _unplayed_match_count() > 0:
        return True
    availability = cache.get("availability", {})
    ko_state = availability.get("knockout_results")
    if ko_state in ("missing", "empty", "unavailable"):
        return True
    return not cache.get("champion")


def simulation_eligibility() -> tuple[bool, Optional[str], str]:
    """Shared eligibility truth (adapter + handler both use this)."""
    if _season_outcome_undecided():
        return True, None, ""
    return False, "no_outstanding_outcomes", (
        "Every match has a real result and the season outcome is decided "
        "- nothing to simulate.")


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


def _ucl_sim_runner(progress_cb, count: int, seed):
    """Competition runner: offline Elo reuse + pipeline call.

    Deliberately does NOT flip the global _mode: canonical cache data stays
    factual ("results"); simulation provenance lives in simulation_meta.
    """
    global boot_log_local, sim_result
    boot_log_local = []
    cached_elo = cache.get("elo_ratings") or None
    result = _run_mc_simulation_pipeline(
        str(DATA_DIR), n_iterations=count, seed=seed,
        weights=None, show_ci="auto", bsd_api_key=BSD_API_KEY,
        team_aliases=_BSD_TEAM_ALIASES, progress_cb=progress_cb,
        elo_ratings_override=cached_elo,
    )
    return result


def _store_ucl_sim_result(result: dict, count: int, seed) -> dict:
    """Cache/snapshot side effects. Returns the public task summary."""
    global boot_log_local, sim_result, _mode, sim_cache
    sim_result = None
    result["boot"] = boot_log_local
    meta_block = result.get("_meta") or {}
    sim_cache = result
    sim_cache["simulation_meta"] = build_simulation_meta(
        requested_count=count,
        actual_count=result.get("n_iterations"),
        seed=meta_block.get("seed"),
        provenance_extra=meta_block.get("provenance") or {},
        engine_version=meta_block.get("engine_version"),
    )
    snapshot_path = DATA_DIR / "snapshot.json"
    snapshot_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": result.get("mode", "simulation"),
        "iterations": result.get("n_iterations"),
        "seed": meta_block.get("seed"),
        "requested_seed": seed,
        "n_teams": result.get("n_teams", 0),
        "champion": result.get("champion"),
        "snapshot_date": result.get("snapshot_date", ""),
        "odds": result.get("odds", []),
        "standings": result.get("standings", []),
        "signals": result.get("signals", {}),
        "elo_ratings": result.get("elo_ratings", {}),
    }
    snapshot_path.write_text(
        json.dumps(snapshot_data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"champion": result.get("champion"),
            "count": result.get("n_iterations")}


@ucl_app.post("/api/mode")
def api_set_mode(req: dict = None):
    global _mode
    body = req or {}
    mode = str(body.get("mode", "simulate")).lower()
    if mode not in ("simulate", "live"):
        return JSONResponse({"error": f"invalid mode: {mode}. Must be simulate or live"})
    _mode = mode
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
    from web.startup import is_snapshot_mode
    if is_snapshot_mode():
        return JSONResponse({"status": "skipped",
                             "reason": "snapshot mode selected at startup"})
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

        return JSONResponse({
            "validation": validation,
            "calibration_available": False,
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
    return JSONResponse(service.poll(task_id))


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
    match_round = ""
    for r, matches in br.items():
        for m in matches:
            if m["match_id"] == match_id:
                match_data = m
                match_round = r
                break
        if match_data:
            break

    # League-phase fallback: search results.json when not found in bracket
    if not match_data:
        for m in _load_results():
            if m["match_id"] == match_id:
                match_data = m
                match_round = "League Phase"
                break

    if not match_data:
        return JSONResponse({"error": "match not found"})
    ta = match_data.get("team_a", "")
    tb = match_data.get("team_b", "")
    if not ta or not tb:
        return JSONResponse({"error": "match teams not set"})

    # Truthful match state (Exchange 2): league-phase rows carry scores but no
    # winner key, so derive played-ness from the canonical evidence instead of
    # bool(winner) which reported false for every played league match.
    has_scores = (match_data.get("home_score") is not None
                  and match_data.get("away_score") is not None)
    score = match_data.get("score")
    if score is None and has_scores:
        score = {"home": match_data.get("home_score"), "away": match_data.get("away_score")}
    winner = match_data.get("winner") or ""
    played_flag = bool(winner) or has_scores

    elo_map = cache.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    elo_prob = expected_score(elo_a, elo_b)

    engine = cache.get("_signal_engine")
    signals_with_weights: dict = {}
    blended_prob: float | None = None
    prob_available = False
    prob_reason = "engine_unavailable"

    if engine:
        try:
            ctx = PredictionContext(
                fixtures=[{"team_a": ta, "team_b": tb, "match_id": match_id}],
                elo_ratings=elo_map,
                played_results=[],
            )
            bp = engine.evaluate({"team_a": ta, "team_b": tb, "match_id": match_id}, ctx)
            blended_prob = round(bp.home_prob, 4)
            prob_available = True
            prob_reason = None
            for sig, sd in bp.signal_breakdown.items():
                prob = sd.get("home", 0.5)
                weight = sd.get("weight", 0)
                signals_with_weights[sig] = {
                    "probability": round(prob, 4),
                    "weight": round(weight, 4),
                    "label": sig.replace("_", " ").title(),
                }
        except Exception:
            blended_prob = None
            prob_available = False
            prob_reason = "engine_evaluation_failed"

    # No fabricated distribution from a fallback probability: when the blend
    # is unavailable the outcome chart data is explicitly absent.
    outcome = _ucl_outcome_dist(blended_prob, elo_a, elo_b) if blended_prob is not None else None

    results = cache.get("_results", [])
    form_trends: dict = {}
    h2h: dict = {"a_wins": 0, "b_wins": 0, "draws": 0, "total": 0}
    if results:
        form_trends = {ta: _ucl_form_trend(ta, results), tb: _ucl_form_trend(tb, results)}
        h2h = _ucl_head_to_head(ta, tb, results)

    eval_data = cache.get("signals", {})
    insight = _ucl_insight_text(ta, tb, signals_with_weights, form_trends, h2h,
                                outcome or {}, eval_data)

    return JSONResponse({
        "match_id": match_id,
        "round": match_data.get("round"),
        "teams": {"a": ta, "b": tb},
        "played": played_flag,
        "score": score,
        "winner": winner or None,
        "match_status": "played" if played_flag else "scheduled",
        "provenance": "official",
        "signals": signals_with_weights,
        "blended_prob": blended_prob,
        "prob_available": prob_available,
        "prob_reason": prob_reason,
        "elo_prob": round(elo_prob, 4),
        "form_trends": form_trends,
        "head_to_head": h2h,
        "outcome_distribution": outcome,
        "insight": insight,
    })


@ucl_app.post("/api/what-if")
def api_what_if(req: dict = None):
    """Structured counterfactual: adjust one team's Elo by +-delta, re-run seeded MC.

    Body: {"match_id": str, "elo_delta": int (default 50, applied +to team_a / -to team_b),
           "iterations": int (default 10000, capped at 50000)}
    Returns baseline vs adjusted champion probabilities for both teams.
    """
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    if not match_id:
        return JSONResponse({"error": "match_id required"})
    try:
        elo_delta = int(req.get("elo_delta", 50))
        n_iterations = min(max(int(req.get("iterations", 10000)), 1000), 50000)
    except (TypeError, ValueError):
        return JSONResponse({"error": "elo_delta/iterations must be integers"})
    if elo_delta == 0:
        return JSONResponse({"error": "elo_delta must be non-zero"})
    elo_delta = max(-600, min(600, elo_delta))

    br = cache.get("bracket_rounds", {})
    match_data = None
    for r, matches in br.items():
        for m in matches:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break

    # League-phase fallback: mirror the insight handler so counterfactuals
    # work for every clickable match, not only knockout ties.
    if not match_data:
        for m in _load_results():
            if m["match_id"] == match_id:
                match_data = m
                break
    if not match_data:
        return JSONResponse({"error": "match not found"})

    ta = match_data.get("team_a", "") or ""
    tb = match_data.get("team_b", "") or ""
    if not ta or not tb:
        return JSONResponse({"error": "bracket slot unresolved"})

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

    baseline_elos = dict(elo_ratings)
    # Real played league matches are immutable facts in both scenarios.
    played_matches = _load_league_played_pairs(str(DATA_DIR))
    baseline = build_simulation_result(
        provider, baseline_elos, seed=42, n_iterations=n_iterations,
        played_matches=played_matches,
    )

    adjusted_elos = dict(baseline_elos)
    adjusted_elos[ta] = baseline_elos.get(ta, 1500.0) + elo_delta
    adjusted_elos[tb] = max(100.0, baseline_elos.get(tb, 1500.0) - elo_delta)
    adjusted = build_simulation_result(
        provider, adjusted_elos, seed=42, n_iterations=n_iterations,
        played_matches=played_matches,
    )

    def _entry(name):
        b = baseline.teams.get(name, {}).get("champion_prob", 0.0)
        a = adjusted.teams.get(name, {}).get("champion_prob", 0.0)
        return {"baseline": round(b, 4), "adjusted": round(a, 4),
                "delta": round(a - b, 4)}

    def _top5(result):
        ranked = sorted(result.teams.items(),
                        key=lambda kv: kv[1].get("champion_prob", 0), reverse=True)[:5]
        return [{"team": t, "champion": round(v.get("champion_prob", 0), 4)} for t, v in ranked]

    return JSONResponse({
        "mode": "structured",
        "match_id": match_id,
        "elo_changes": {ta: adjusted_elos[ta], tb: adjusted_elos[tb]},
        "iterations": n_iterations,
        "teams": {ta: _entry(ta), tb: _entry(tb)},
        "top5_baseline": _top5(baseline),
        "top5_adjusted": _top5(adjusted),
    })
