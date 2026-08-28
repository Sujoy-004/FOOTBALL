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
    _load_league_played_pairs,
)
from competitions.ucl.src.pipeline import (
    load_results as _load_results_pipeline,
    load_knockout_results as _load_knockout_results_pipeline,
    ucl_form_trend as _ucl_form_trend_pipeline,
    ucl_head_to_head as _ucl_head_to_head_pipeline,
    ucl_outcome_dist as _ucl_outcome_dist_pipeline,
    ucl_insight_text as _ucl_insight_text_pipeline,
    run_mc_simulation as _run_mc_simulation_pipeline,
    run_calibration_task as _run_calibration_task_pipeline,
)
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
_mode: str = "results"

service = SimulationTaskService()


def _refresh_report_path() -> Path:
    """Seam for tests: location of the shared freshness ledger."""
    return Path(__file__).parent / "last_refresh.json"


def _store_refresh_report(ok: bool, error: str | None, provider_name: str | None,
                          n_matches: int | None = None, n_updated: int | None = None,
                          finished: dict | None = None,
                          stages: list | None = None) -> dict:
    """Record the UCL refresh outcome for the API surface + last_refresh.json.

    Single writer for the UCL entry: the ingestion itself never touches the
    ledger, it only returns the structured IngestReport payload.
    """
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
        **({"stages": stages} if stages is not None else {}),
    }
    try:
        refresh_path = _refresh_report_path()
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
    """Delegate acquisition to the UCL brain's ingestor.

    The web layer owns transport selection (shared get_data_provider) and
    the freshness ledger (single writer below); every normalization,
    skeleton-derivation and store-write decision lives in
    competitions.ucl.src.ingest.
    """
    import logging
    logger = logging.getLogger(__name__)

    from web.startup import is_snapshot_mode
    if is_snapshot_mode():
        logger.warning("[UCL] snapshot mode - live refresh skipped")
        boot_log_local.append({"step": "UCL live fetch", "status": "skip",
                               "elapsed": 0.0,
                               "output": f"[{ts()}] Snapshot mode - live refresh skipped"})
        # Parity with WC: record WHY no live fetch happened so the frontend
        # can disclose snapshot data instead of silently looking live-fresh.
        globals()["_refresh_report"] = {
            "provider": None, "attempted": False, "success": True,
            "stale": True,
            "skipped_reason": "snapshot mode selected at startup",
        }
        return

    from web.common import get_data_provider
    from competitions.ucl.src.pipeline import fetch_live_data as _brain_fetch

    provider = get_data_provider(BSD_API_KEY, FOOTBALL_DATA_ORG_KEY, UCL_LEAGUE_ID)
    if provider is None:
        logger.warning("[UCL] No data provider — skipping live fetch")
        boot_log_local.append({"step": "UCL live fetch", "status": "skip", "elapsed": 0.0, "output": f"[{ts()}] No data provider configured"})
        _store_refresh_report(False, "no data provider configured", None)
        return

    summary = _brain_fetch(
        str(DATA_DIR), BSD_API_KEY,
        football_data_org_key=FOOTBALL_DATA_ORG_KEY,
        ucl_league_id=UCL_LEAGUE_ID,
        provider=provider,
    )
    report = summary.get("report") or {}
    ok = summary.get("status") == "ok"
    provider_name = summary.get("provider_name") or type(provider).__name__
    n_raw = int(summary.get("n_raw") or 0)
    n_updated = int(summary.get("n_updated") or 0)
    error = report.get("error") if not ok else getattr(provider, "last_error", None)
    if not ok:
        logger.warning("[UCL] Refresh failed: %s — UCL data may be STALE",
                       error or "no ingestable matches")
    _store_refresh_report(ok, error, provider_name,
                          n_matches=n_raw, n_updated=n_updated,
                          finished=report.get("finished"),
                          stages=report.get("stages"))
    boot_log_local.append({
        "step": "UCL live fetch", "status": "ok" if ok else "skip", "elapsed": 0.0,
        "output": f"[{ts()}] {provider_name}: {n_raw} raw matches, {n_updated} updated",
    })
    # Exchange 5: if a new season was activated by the ingest, recompute
    # the cache so the API serves fresh data immediately.
    if ok:
        _maybe_recompute_cache_after_ingest(summary)


def _maybe_recompute_cache_after_ingest(summary: dict) -> None:
    """Recompute cache if a new season was activated during ingest.

    Exchange 5: after a successful multi-season ingest, the active season
    may have changed (current.json updated).  Recompute the cache so
    subsequent API calls serve the new season's data.
    """
    import logging as _logging
    logger = _logging.getLogger(__name__)
    per_season = summary.get("per_season") or {}
    if not per_season:
        return
    try:
        old_mode = _mode
        old_cache_snapshot = cache.get("mode")
        new_result = compute_all()
        if new_result.get("error"):
            logger.warning("[UCL] Cache recomputation failed: %s", new_result["error"])
            return
        globals()["cache"] = new_result
        if new_result.get("mode") != old_mode:
            globals()["_mode"] = new_result.get("mode", old_mode)
            logger.info("[UCL] Cache recomputed: mode changed from %s to %s",
                        old_mode, _mode)
    except Exception as exc:
        logger.warning("[UCL] Cache recomputation failed: %s", exc)


def _load_results() -> list[dict]:
    """Load results from the active season's data directory."""
    from competitions.ucl.src.orchestrator import resolve_active_data_dir
    return _load_results_pipeline(resolve_active_data_dir(DATA_DIR))


def _load_knockout_results() -> dict | None:
    """Load knockout results — always from root (structural file)."""
    return _load_knockout_results_pipeline(DATA_DIR)


def _unplayed_match_count() -> int:
    """Count UCL matches that haven't been played yet."""
    return _match_counts()[0]


def _match_counts() -> tuple[int, int]:
    """Return (unplayed, total) match counts from fixtures + results.

    Exchange 5: reads fixtures from the active season's data directory.
    """
    from competitions.ucl.src.orchestrator import resolve_active_data_dir
    active_dir = Path(resolve_active_data_dir(DATA_DIR))
    fixtures_path = active_dir / "fixtures.json"
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


def deterministic_compute() -> dict:
    global boot_log_local, _mode
    boot_log_local = []
    _mode = "results"
    from competitions.ucl.src.orchestrator import run_deterministic_compute as _f
    result = _f(str(DATA_DIR), bsd_api_key=BSD_API_KEY)
    boot_log_local = result.get("boot", [])
    return result


def compute_all() -> dict:
    global boot_log_local, _mode
    from competitions.ucl.src.orchestrator import resolve_compute_mode
    mode, mode_reason = resolve_compute_mode(str(DATA_DIR))
    if mode == "results":
        return deterministic_compute()
    if mode == "error":
        # Real results exist but are unreadable: surface the failure instead
        # of fabricating a simulated season over them.
        _mode = "results"
        boot_log_local = [{"step": "Select data mode", "status": "error", "elapsed": 0.0,
                           "output": f"[error] {mode_reason}"}]
        return {"error": mode_reason, "boot": boot_log_local}
    _mode = "simulation"
    boot_log_local = []
    from competitions.ucl.src.orchestrator import run_compute_all as _f
    result = _f(str(DATA_DIR), bsd_api_key=BSD_API_KEY, team_aliases=_BSD_TEAM_ALIASES)
    boot_log_local = result.get("boot", [])
    return result


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    global cache
    # Zero provider calls during boot (Exchange 4 v2): caches come from
    # validated on-disk stores; acquisition is lazy and scoped to THIS
    # competition's first data request (try_lazy_refresh in api_data).
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
    # Lazy scoped acquisition (Exchange 4 v2): at most ONE fresh attempt
    # per process, on the first data request for THIS competition only.
    # Explicit offline sessions never attempt (the gate records the
    # wrapper's truthful snapshot-skipped report instead). Deferred import:
    # web.competitions builds the registry by importing this module.
    from web.competitions import try_lazy_refresh
    try_lazy_refresh("ucl")
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
        "lifecycle": _lifecycle_view(),
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
    payload = {
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
    }
    bracket = _simulation_bracket_state()
    if bracket is not None:
        payload["bracket"] = bracket
    return JSONResponse(payload)


def _competition_state() -> dict:
    """Authoritative factual competition state (built fresh from stores).

    Exchange 5: resolves the active season so the state builder reads
    from the correct season-dir store.
    """
    from competitions.ucl.src.state import build_competition_state
    from competitions.ucl.src.seasons import get_current_season
    current = get_current_season(DATA_DIR)
    active_season = current.get("season") if current and isinstance(current, dict) else None
    return build_competition_state(str(DATA_DIR), mode="results", active_season=active_season)


def _lifecycle_view() -> dict:
    """Season-lifecycle view (competitions.ucl.src.lifecycle.discover)."""
    from competitions.ucl.src.lifecycle import discover
    from competitions.ucl.src.seasons import resolve_active_view
    active_view = resolve_active_view(str(DATA_DIR))
    provider_season = active_view.get("current_season")
    return discover(str(DATA_DIR), provider_season=provider_season)


def _simulation_bracket_state() -> dict | None:
    """Simulated bracket in the same structural shape as the factual one."""
    sim_payload = sim_cache.get("sim_state_payload")
    if not sim_payload:
        return None
    from competitions.ucl.src.state import build_competition_state
    from competitions.ucl.src.seasons import get_current_season
    try:
        current = get_current_season(DATA_DIR)
        active_season = current.get("season") if current and isinstance(current, dict) else None
        return build_competition_state(str(DATA_DIR), mode="simulation",
                                       sim_payload=sim_payload, active_season=active_season)
    except Exception:
        return None


@ucl_app.get("/api/standings")
def api_standings():
    return JSONResponse({"standings": cache.get("standings", []), "mode": _mode})


@ucl_app.get("/api/bracket")
def api_bracket():
    payload = dict(_competition_state())
    # Compatibility alias for older consumers of the league matchday rows.
    payload["league_matchdays"] = (
        payload.get("stages", {}).get("league", {}).get("matchdays")
        or cache.get("league_matchdays", {}))
    # Same lifecycle view as /api/data (cheap reuse, one discover call each).
    payload["lifecycle"] = _lifecycle_view()
    return JSONResponse(payload)


@ucl_app.get("/api/odds")
def api_odds():
    return JSONResponse({
        "odds": cache.get("odds", []),
        "mode": _mode,
        # Results mode serves deterministic achieved-outcome indicators
        # (1.0/0.0), NOT model probabilities. Simulation runs surface their
        # projections through /api/simulation with SIMULATED provenance.
        "odds_semantics": (
            "achieved_outcome_indicators" if _mode == "results"
            else "monte_carlo_probabilities"),
    })


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
        # Completed factual seasons remain simulatable as an explicit
        # alternate-history analysis; _simulation_state_block exposes the
        # what_if flag so the UI labels it truthfully. Simulation results
        # never overwrite factual stores.
        return True, None, ""

    http_status, payload = service.start(
        competition_id="ucl",
        raw_count=raw_count,
        default_count=5000,
        seed=body.get("seed"),
        runner=_ucl_sim_runner,
        eligibility_fn=eligibility,
        on_result=_store_ucl_sim_result,
        options={"weights": weights, "show_ci": show_ci},
        extra_ack={"mode": "simulation", "n_unplayed": _unplayed_match_count(),
                   "what_if": not _season_outcome_undecided()},
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
    """Shared eligibility truth (adapter + handler both use this).

    Simulation is always offered; completed seasons are served as clearly
    labeled what-if analysis rather than being blocked.
    """
    return True, None, ""


def _simulation_state_block() -> dict:
    """Shared product contract: availability + request lifecycle.

    Completed-season honesty (Exchange 3): while the factual season still
    has undecided outcomes the season-wide simulation controls are offered
    ("available"); once every outcome is decided on disk they flip to
    "not_needed" and any run is labeled what-if. Server-side eligibility
    keeps allowing runs either way — per-tie what-if flows and legacy
    sessions depend on it; only the exposed availability flag changes.
    """
    undecided = _season_outcome_undecided()
    sim_status = sim_cache.get("status", "not_requested")
    request_state = {
        "running": "running",
        "completed": "completed",
        "failed": "failed",
    }.get(sim_status, "not_requested")
    if not undecided:
        return {
            "availability": "not_needed",
            "reason": None,
            "request_state": request_state,
            # A decided factual season makes every run an explicit alternate-
            # history analysis; the UI must label it accordingly.
            "what_if": True,
        }
    return {
        "availability": "available",
        "reason": None,
        "request_state": request_state,
        "what_if": False,
    }


def _ucl_sim_runner(progress_cb, count: int, seed):
    """Competition runner: offline Elo reuse + pipeline call.

    Deliberately does NOT flip the global _mode: canonical cache data stays
    factual ("results"); simulation provenance lives in simulation_meta.
    """
    global boot_log_local
    boot_log_local = []
    cached_elo = cache.get("elo_ratings") or None

    def _normalized_progress(value: int, total: int, stage: str = "") -> None:
        # Pre-MC stages report (percent, 100); the MC loop reports
        # (iteration, total_iterations). Map both onto the run count.
        if total == 100:
            progress_cb(int(value / 100 * count), count, stage)
        else:
            progress_cb(value, total, stage)

    result = _run_mc_simulation_pipeline(
        str(DATA_DIR), n_iterations=count, seed=seed,
        weights=None, show_ci="auto", bsd_api_key=BSD_API_KEY,
        team_aliases=_BSD_TEAM_ALIASES, progress_cb=_normalized_progress,
        elo_ratings_override=cached_elo,
    )
    return result


def _store_ucl_sim_result(result: dict, count: int, seed) -> dict:
    """Cache/snapshot side effects. Returns the public task summary."""
    global boot_log_local, _mode, sim_cache
    result["boot"] = boot_log_local
    meta_block = result.get("_meta") or {}
    sim_cache = result
    sim_cache["status"] = "completed"
    sim_cache["simulation_meta"] = build_simulation_meta(
        requested_count=count,
        actual_count=result.get("n_iterations"),
        seed=meta_block.get("seed"),
        provenance_extra=meta_block.get("provenance") or {},
        engine_version=meta_block.get("engine_version"),
    )
    snapshot_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": result.get("mode", "simulation"),
        "iterations": result.get("n_iterations"),
        "seed": meta_block.get("seed"),
        "requested_seed": seed,
        "n_teams": result.get("n_teams", 0),
        "champion": result.get("champion"),
        "snapshot_date": result.get("snapshot_date", ""),
        # Everything below is SIMULATED content; factual stores are never
        # touched by a run.
        "provenance": "simulated",
        "simulation_meta": sim_cache["simulation_meta"],
        "odds": result.get("odds", []),
        "standings": result.get("standings", []),
        "signals": result.get("signals", {}),
        "elo_ratings": result.get("elo_ratings", {}),
    }
    bracket = _simulation_bracket_state()
    if bracket is not None:
        snapshot_data["bracket"] = bracket
    snapshot_path = DATA_DIR / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(snapshot_data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"champion": result.get("champion"),
            "count": result.get("n_iterations")}


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


def _ucl_calibration_runner(progress_cb, count, seed):
    from competitions.ucl.src.pipeline import run_calibration_task
    return run_calibration_task(str(DATA_DIR), progress_cb=progress_cb)


def _store_ucl_calibration_result(result, count, seed) -> dict:
    if result.get("status") != "ok":
        raise SimulationContractError(result.get("error", "calibration failed"))
    return {"weights": result.get("weights"),
            "n_matches": result.get("n_matches")}


@ucl_app.post("/api/calibrate")
def api_calibrate(req: dict = None):
    http_status, payload = service.start(
        competition_id="ucl",
        raw_count=100,
        default_count=100,
        seed=None,
        runner=_ucl_calibration_runner,
        eligibility_fn=lambda: (True, None, ""),
        on_result=_store_ucl_calibration_result,
        extra_ack={"kind": "calibration"},
    )
    payload.pop("count", None)
    payload.pop("requested_count", None)
    return JSONResponse(payload, status_code=http_status)


@ucl_app.get("/api/validation")
def api_validation():
    """Pure-Elo validation against the real results ledger.

    (Exchange 5 cleanup: the simulated-result branch was unreachable —
    ``sim_result`` was permanently None — so only the factual path remains.)
    """
    try:
        results = _load_results()
        if not results:
            return JSONResponse({"error": "no results data available", "validation": None})

        elo_ratings = cache.get("elo_ratings", {})
        if not elo_ratings:
            team_names = list({m["team_a"] for m in results} | {m["team_b"] for m in results})
            elo_ratings = fetch_team_elos(team_names) or {}

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


def _find_state_match(match_id: str) -> dict | None:
    """Locate a knockout tie/match by canonical id in the competition state."""
    stages = _competition_state().get("stages", {})
    for key in ("playoff", "R16", "QF", "SF", "FINAL"):
        for m in stages.get(key, {}).get("matches", []):
            if m.get("id") == match_id:
                out = dict(m)
                out["round"] = key
                if out.get("score") is None and out.get("aggregate_a") is not None:
                    out["score"] = {"home": out["aggregate_a"],
                                    "away": out.get("aggregate_b")}
                return out
    return None


def _ucl_form_trend(team: str, results: list[dict]) -> list[dict]:
    return _ucl_form_trend_pipeline(team, results)


def _ucl_head_to_head(ta: str, tb: str, results: list[dict]) -> dict:
    return _ucl_head_to_head_pipeline(ta, tb, results)


def _ucl_outcome_dist(blended_prob: float, elo_a: float, elo_b: float) -> dict:
    return _ucl_outcome_dist_pipeline(blended_prob, elo_a, elo_b)


def _ucl_insight_text(ta: str, tb: str, signals: dict, form_trends: dict, h2h: dict, outcome: dict, eval_data: dict) -> str:
    return _ucl_insight_text_pipeline(ta, tb, signals, form_trends, h2h, outcome, eval_data)


_AGGREGATE_ONLY_NOTE = (
    "Aggregate-only historical record; per-leg scores not available.")


@ucl_app.get("/api/match/insight")
def api_match_insight(match_id: str = "", context: str = ""):
    if not match_id:
        return JSONResponse({"error": "match_id parameter required"})
    match_data = _find_state_match(match_id)
    match_round = (match_data or {}).get("round", "")
    from_state = match_data is not None

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

    # ── Frozen wave-3 tie/match enrichment (additive) ────────────────────
    # Knockout nodes carry their real provenance and per-leg detail; the
    # FINAL is a single match, every other knockout round is a two-legged
    # tie. League rows keep the plain "match" shape.
    if from_state:
        kind = "match" if match_round == "FINAL" else "tie"
        legs = match_data.get("legs") or None
        if kind == "match":
            sc = match_data.get("score") or {}
            home, away = sc.get("home"), sc.get("away")
            aggregate = (
                {"a": int(home), "b": int(away)}
                if home is not None and away is not None else None)
        else:
            agg_a = match_data.get("aggregate_a")
            agg_b = match_data.get("aggregate_b")
            aggregate = (
                {"a": int(agg_a), "b": int(agg_b)}
                if agg_a is not None and agg_b is not None else None)
        raw_pen_score = match_data.get("penalty_score")
        pens = {
            "played": bool(match_data.get("penalties_played")),
            "winner": match_data.get("penalty_winner") or None,
            "score": str(raw_pen_score) if raw_pen_score else None,
        }
        et = {
            "played": bool(match_data.get("et_played")),
            "a": int(match_data.get("et_a") or 0),
            "b": int(match_data.get("et_b") or 0),
        }
        provenance = match_data.get("provenance") or "official"
    else:
        kind = "match"
        legs = None
        aggregate = None
        pens = None
        et = None
        # League rows: reuse whatever canonical classification the row
        # carries; results-ledger rows are official by domain rule.
        provenance = match_data.get("provenance") or "official"

    availability_note = (
        _AGGREGATE_ONLY_NOTE
        if kind == "tie" and legs is None and aggregate is not None
        else None)

    teams_resolved = bool(ta and tb)
    what_if = {
        "eligible": teams_resolved,
        "reason": None if teams_resolved else "slot_unresolved",
    }

    # Simulated-context guard: a SIM-overlaid card asks for the same payload
    # with simulated provenance; no backend state changes.
    if context == "simulated":
        provenance = "simulated"

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
        "kind": kind,
        "legs": legs,
        "aggregate": aggregate,
        "pens": pens,
        "et": et,
        "availability_note": availability_note,
        "what_if": what_if,
        "played": played_flag,
        "score": score,
        "winner": winner or None,
        "match_status": "played" if played_flag else "scheduled",
        "provenance": provenance,
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

    match_data = _find_state_match(match_id)

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

    from competitions.ucl.src.orchestrator import resolve_active_data_dir
    fixtures_path = str(Path(resolve_active_data_dir(DATA_DIR)) / "fixtures.json")
    provider = RepoFixtureProvider(fixtures_path=fixtures_path).load()
    team_names = [t.name for t in provider.teams]

    def _coefficient_elos() -> dict:
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        return {t: 1400.0 + (coefficients.get(t, 50) / max_coeff) * 400.0
                for t in team_names}

    # Elo resolution mirrors the season runner: reuse the boot-time ratings
    # when present; only reach for ClubElo as a live fallback, and degrade
    # to coefficient-derived ratings offline instead of failing the request.
    elo_ratings = cache.get("elo_ratings") or {}
    if not elo_ratings:
        try:
            elo_ratings = fetch_team_elos(team_names) or {}
        except Exception:
            elo_ratings = {}
    if not elo_ratings:
        elo_ratings = _coefficient_elos()

    baseline_elos = dict(elo_ratings)
    # Real played league matches are immutable facts in both scenarios.
    from competitions.ucl.src.orchestrator import resolve_active_data_dir
    played_matches = _load_league_played_pairs(resolve_active_data_dir(DATA_DIR))
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
