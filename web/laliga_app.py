"""LaLiga EA Sports — FastAPI sub-app mounted under /laliga.

Full parity with the UCL sub-app's product surface (league-only, no
bracket): data, seasons, standings, odds, signals, simulate, refresh,
reset, validation, report, match insight, and Elo what-if counterfactual.
All tournament logic stays in ``competitions.laliga.src``; this module
only wires transport, the freshness ledger, and the simulation task
service.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import fastapi
from fastapi.responses import JSONResponse

from competitions.laliga.src import seasons as season_store
from competitions.laliga.src.constants import (
    DATA_DIR,
    LALIGA_BSD_LEAGUE_ID,
    LALIGA_FDO_COMPETITION_ID,
    SHIPPED_SEASON,
)
from competitions.laliga.src.groups import played_map_from_rows
from competitions.laliga.src.pipeline import (
    compute_deterministic as _brain_compute_deterministic,
    laliga_form_trend as _laliga_form_trend_pipeline,
    laliga_head_to_head as _laliga_head_to_head_pipeline,
    laliga_insight_text as _laliga_insight_text_pipeline,
    laliga_outcome_dist as _laliga_outcome_dist_pipeline,
    load_elo_ratings,
    load_fixtures as _load_fixtures_pipeline,
    load_results as _load_results_pipeline,
)
from competitions.laliga.src.simulation import run_mc_simulation as _run_mc_simulation_pipeline
from competitions.laliga.src.state import build_competition_state as _build_state
from football_core.elo import expected_score
from football_core.signal import PredictionContext
from web.common import ts
from web.simulation_service import SimulationTaskService, build_simulation_meta

logger = logging.getLogger(__name__)

BSD_API_KEY: str = os.environ.get("BSD_API_KEY", "")
FOOTBALL_DATA_ORG_KEY: str = os.environ.get("FOOTBALL_DATA_ORG_KEY", "")

cache: dict = {}
sim_cache: dict = {}
boot_log_local: list[dict] = []
_mode: str = "results"

service = SimulationTaskService()


def _refresh_report_path() -> Path:
    return Path(__file__).parent / "last_refresh.json"


def _load_refresh_ledger(refresh_path: Path | None = None) -> dict:
    refresh_path = refresh_path if refresh_path is not None else _refresh_report_path()
    if not refresh_path.exists():
        return {}
    try:
        data = json.loads(refresh_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


_refresh_report: dict = {}
_refresh_reports_seeded: bool = False


def _season_refresh_reports() -> dict:
    global _refresh_reports_seeded
    if not _refresh_reports_seeded:
        _refresh_reports_seeded = True
        data = _load_refresh_ledger()
        seasons = data.get("laliga_seasons")
        if isinstance(seasons, dict):
            for season, report in seasons.items():
                if isinstance(report, dict):
                    cache_entry.setdefault(str(season), report)
        legacy = data.get("laliga")
        if isinstance(legacy, dict) and legacy.get("active_season"):
            cache_entry.setdefault(str(legacy["active_season"]), legacy)
    return cache_entry


cache_entry: dict[str, dict] = {}


def _active_season_token() -> str:
    return season_store.active_season(DATA_DIR)


def _synthesize_season_report(season: str) -> dict:
    fixtures = _load_fixtures_pipeline(DATA_DIR, season)
    results = _load_results_pipeline(DATA_DIR, season)
    return {
        "provider": None,
        "attempted": False,
        "success": True,
        "error": None,
        "stale": False,
        "deferred": False,
        "reason": None,
        "status": "ok",
        "active_season": season,
        "last_refresh": datetime.now(timezone.utc).isoformat(),
        "n_matches": len(results),
        "synth": True,
        "fixtures": len(fixtures),
    }


def _refresh_report_for(season: str) -> dict:
    if _refresh_report.get("skipped_reason"):
        return _refresh_report
    report = _season_refresh_reports().get(season)
    if report is not None:
        return report
    return _synthesize_season_report(season)


def _store_refresh_report(
    ok: bool, error: str | None, provider_name: str | None,
    n_matches: int | None = None, n_updated: int | None = None,
    active_season: str | None = None, deferred: bool = False,
    reason: str | None = None, status: str | None = None,
) -> dict:
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
        **({"active_season": active_season} if active_season is not None else {}),
        **({"deferred": deferred} if deferred else {}),
        **({"reason": reason} if reason is not None else {}),
        **({"status": status} if status is not None else {}),
    }
    if active_season:
        cache_entry[str(active_season)] = _refresh_report
    try:
        refresh_path = _refresh_report_path()
        refresh_data = _load_refresh_ledger(refresh_path)
        entry = dict(_refresh_report)
        entry["mode"] = provider_name
        entry["n_matches"] = n_matches or 0
        entry["n_updated"] = n_updated or 0
        refresh_data["laliga"] = entry
        if active_season:
            refresh_data.setdefault("laliga_seasons", {})[str(active_season)] = entry
        refresh_path.write_text(json.dumps(refresh_data, indent=2), encoding="utf-8")
    except Exception:
        pass
    return _refresh_report


def _fetch_live_data():
    """Delegate acquisition to the LaLiga brain; record the ledger entry."""
    from web.startup import is_snapshot_mode

    if is_snapshot_mode():
        logger.warning("[LaLiga] snapshot mode - live refresh skipped")
        globals()["_refresh_report"] = {
            "provider": None, "attempted": False, "success": True,
            "stale": True,
            "skipped_reason": "snapshot mode selected at startup",
        }
        return None

    active_season = _active_season_token()
    from web.common import get_data_provider
    from competitions.laliga.src.pipeline import fetch_live_data as _brain_fetch

    provider = get_data_provider(BSD_API_KEY, FOOTBALL_DATA_ORG_KEY, LALIGA_BSD_LEAGUE_ID)
    if provider is None:
        logger.warning(
            "[LaLiga] NOT_CONFIGURED - no data provider available "
            "(BSD key configured: %s, football-data key configured: %s, "
            "DATA_PROVIDER=%s); skipping live fetch",
            bool(BSD_API_KEY), bool(FOOTBALL_DATA_ORG_KEY),
            os.environ.get("DATA_PROVIDER", "") or "(unset)",
        )
        _store_refresh_report(False, "no data provider configured", None,
                              active_season=active_season)
        return None
    try:
        summary = _brain_fetch(
            str(DATA_DIR),
            bsd_api_key=BSD_API_KEY,
            provider=provider,
            football_data_org_key=FOOTBALL_DATA_ORG_KEY,
            league_id=LALIGA_BSD_LEAGUE_ID,
            fdo_competition_id=LALIGA_FDO_COMPETITION_ID,
        )
    except Exception as exc:
        logger.warning("[LaLiga] live fetch raised: %s", exc)
        _store_refresh_report(False, f"{exc.__class__.__name__}: {exc}",
                              type(provider).__name__, active_season=active_season)
        return None

    report = summary.get("report") or {}
    status = summary.get("status")
    ok = status == "ok"
    deferred = status == "deferred"
    reason = summary.get("reason")
    provider_name = summary.get("provider_name") or type(provider).__name__
    n_raw = int(summary.get("n_raw") or 0)
    n_updated = int(summary.get("n_updated") or 0)
    error = report.get("error") if not (ok or deferred) else getattr(provider, "last_error", None)
    if deferred:
        logger.info("[LaLiga] CONFIGURED_BUT_UNAVAILABLE - no published "
                    "match data yet (deferred)")
    elif not ok:
        logger.warning("[LaLiga] CONFIGURED_BUT_UNAVAILABLE - refresh failed: %s",
                       error or "no ingestable matches")
    _store_refresh_report(ok or deferred, error, provider_name,
                          n_matches=n_raw, n_updated=n_updated,
                          active_season=active_season,
                          deferred=deferred, reason=reason, status=status)
    boot_log_local.append({
        "step": "LaLiga live fetch", "status": "deferred" if deferred else ("ok" if ok else "skip"),
        "elapsed": 0.0,
        "output": f"[{ts()}] {provider_name}: {n_raw} raw matches, {n_updated} updated",
    })
    if ok:
        logger.info("[LaLiga] CONNECTED via %s: %s raw matches, %s updated",
                    provider_name, n_raw, n_updated)
        _recompute_cache()
    return summary


def _recompute_cache() -> None:
    global cache, _mode
    try:
        result = compute_all()
        if result.get("error"):
            logger.warning("[LaLiga] Cache recomputation failed: %s", result["error"])
            return
        cache = result
        _mode = result.get("mode", _mode)
    except Exception as exc:
        logger.warning("[LaLiga] Cache recomputation failed: %s", exc)


def _match_counts() -> tuple[int, int]:
    fixtures = _load_fixtures_pipeline(DATA_DIR)
    total = len(fixtures)
    played = len(played_map_from_rows(_load_results_pipeline(DATA_DIR)))
    return total - played, total


def _unplayed_match_count() -> int:
    return _match_counts()[0]


def compute_all() -> dict:
    global boot_log_local, _mode
    boot_log_local = []
    from competitions.laliga.src.pipeline import compute_deterministic
    result = compute_deterministic()
    if result.get("error"):
        _mode = "results"
        boot_log_local.append({"step": "LaLiga compute", "status": "error", "elapsed": 0.0,
                               "output": f"[error] {result['error']}"})
        return result
    _mode = "results"
    from competitions.laliga.src.pipeline import build_signal_engine
    result["_signal_engine"] = build_signal_engine(result.get("elo_ratings", {}))
    return result


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    global cache
    cache = compute_all()
    _ensure_signal_engine()
    yield


def build_signal_engine_for_cache() -> None:
    """Attach the signal engine to the cache for match-insight endpoint."""
    from competitions.laliga.src.pipeline import build_signal_engine
    elo_ratings = cache.get("elo_ratings", {}) or load_elo_ratings(DATA_DIR)
    cache["_signal_engine"] = build_signal_engine(elo_ratings)


def _ensure_signal_engine() -> None:
    if cache.get("_signal_engine") is None:
        build_signal_engine_for_cache()


laliga_app = fastapi.FastAPI(lifespan=lifespan)


@laliga_app.exception_handler(Exception)
async def _json_error_handler(request, exc):
    logging.getLogger(__name__).error(
        "[LaLiga] unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse({"error": f"internal error: {exc.__class__.__name__}"},
                        status_code=500)


@laliga_app.get("/api/data")
def api_data():
    from web.competitions import try_lazy_refresh
    try_lazy_refresh("laliga")
    n_unplayed, n_total = _match_counts()
    return JSONResponse({
        "refresh": _refresh_report_for(_active_season_token()),
        "teams": cache.get("teams", []),
        "all_teams": cache.get("all_teams", []),
        "standings": cache.get("standings", []),
        "n_teams": cache.get("n_teams", 0),
        "n_iterations": cache.get("n_iterations", 0),
        "snapshot_date": cache.get("snapshot_date", ""),
        "champion": cache.get("champion"),
        "mode": _mode,
        "availability": cache.get("availability", {}),
        "phase": cache.get("phase", {}),
        "season": _active_season_token(),
        "n_total_fixtures": n_total,
        "simulation": _simulation_state_block(),
        "n_unplayed": n_unplayed,
        "n_played": n_total - n_unplayed,
    })


@laliga_app.get("/api/seasons")
def api_seasons():
    candidates = {SHIPPED_SEASON}
    for token in season_store.list_seasons(DATA_DIR):
        candidates.add(token.replace("_", "/") if token.count("_") == 1 else token)
    active = _active_season_token()
    seasons = []
    for season in sorted(candidates, reverse=True):
        fixtures = season_store.read_fixtures(DATA_DIR, season)
        results = season_store.read_results(DATA_DIR, season)
        seasons.append({
            "season": season,
            "active": season == active,
            "historical": False,
            "fixtures": len(fixtures.get("fixtures", [])) if isinstance(fixtures, dict) else 0,
            "results": len(results.get("matches", [])) if isinstance(results, dict) else 0,
        })
    return JSONResponse({"active_season": active, "seasons": seasons})


@laliga_app.post("/api/season")
def api_set_season(req: dict = None):
    season = str((req or {}).get("season") or "").strip()
    if not season:
        return JSONResponse({"error": "season required"}, status_code=400)
    if season != SHIPPED_SEASON and not season_store.season_dir(DATA_DIR, season).is_dir():
        return JSONResponse({"error": "unknown season"}, status_code=404)
    pointer = season_store.set_current_season(
        DATA_DIR, season, basis="shipped" if season == SHIPPED_SEASON else "catalog",
        provider=(None if season == SHIPPED_SEASON else f"laliga.{season.replace('/', '_')}"),
    )
    global cache, sim_cache
    sim_cache = {}
    _recompute_cache()
    return JSONResponse({"status": "ok", "current": pointer, "mode": _mode})


@laliga_app.get("/api/boot")
def api_boot():
    return JSONResponse({
        "boot": cache.get("boot", boot_log_local),
        "refresh": _refresh_report,
    })


@laliga_app.get("/api/simulation")
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
    })


def _competition_state() -> dict:
    current = season_store.get_current_season(DATA_DIR)
    active_season = current.get("season") if isinstance(current, dict) else None
    return _build_state(str(DATA_DIR), mode="results", active_season=active_season,
                        standings=cache.get("standings"))


@laliga_app.get("/api/standings")
def api_standings():
    return JSONResponse({
        "standings": cache.get("standings", []),
        "mode": _mode,
        "season": _active_season_token(),
    })


@laliga_app.get("/api/fixtures")
def api_fixtures():
    return JSONResponse({
        "season": _active_season_token(),
        "matchdays": _competition_state().get("stages", {}).get("league", {}).get("matchdays", []),
    })


@laliga_app.get("/api/odds")
def api_odds():
    return JSONResponse({
        "odds": cache.get("odds", []),
        "mode": _mode,
        "season": _active_season_token(),
        "odds_semantics": (
            "achieved_outcome_indicators" if _mode == "results"
            else "monte_carlo_probabilities"),
    })


@laliga_app.get("/api/signals")
def api_signals():
    return JSONResponse({
        "signals": cache.get("signals", {}),
        "mode": _mode,
        "season": _active_season_token(),
    })


def _season_outcome_undecided() -> bool:
    return _unplayed_match_count() > 0


def _simulation_state_block() -> dict:
    undecided = _season_outcome_undecided()
    request_state = {
        "running": "running", "completed": "completed", "failed": "failed",
    }.get(sim_cache.get("status", "not_requested"), "not_requested")
    if not undecided:
        return {"availability": "not_needed", "reason": None,
                "request_state": request_state, "what_if": True}
    return {"availability": "available", "reason": None,
            "request_state": request_state, "what_if": False}


@laliga_app.post("/api/simulate")
def api_simulate(req: dict = None):
    body = req or {}
    weights = body.get("weights")
    show_ci = str(body.get("show_ci", "auto"))
    raw_count = body.get("iterations") or body.get("n_iterations")

    http_status, payload = service.start(
        competition_id="laliga",
        raw_count=raw_count,
        default_count=5000,
        seed=body.get("seed"),
        runner=_laliga_sim_runner,
        eligibility_fn=lambda: (True, None, ""),
        on_result=_store_laliga_sim_result,
        options={"weights": weights, "show_ci": show_ci},
        extra_ack={"mode": "simulation", "n_unplayed": _unplayed_match_count(),
                   "what_if": not _season_outcome_undecided()},
    )
    return JSONResponse(payload, status_code=http_status)


def _laliga_sim_runner(progress_cb, count: int, seed):
    global boot_log_local
    boot_log_local = []
    cached_elo = cache.get("elo_ratings") or None

    def _normalized_progress(value: int, total: int, stage: str = "") -> None:
        if total == 100:
            progress_cb(int(value / 100 * count), count, stage)
        else:
            progress_cb(value, total, stage)

    return _run_mc_simulation_pipeline(
        str(DATA_DIR), n_iterations=count, seed=seed,
        weights=None, show_ci="auto", progress_cb=_normalized_progress,
        elo_ratings_override=cached_elo,
    )


def _store_laliga_sim_result(result: dict, count: int, seed) -> dict:
    global boot_log_local, sim_cache
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
        "provenance": "simulated",
        "simulation_meta": sim_cache["simulation_meta"],
        "odds": result.get("odds", []),
        "standings": result.get("standings", []),
        "signals": result.get("signals", {}),
        "elo_ratings": result.get("elo_ratings", {}),
    }
    snapshot_path = DATA_DIR / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(snapshot_data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"champion": result.get("champion"),
            "count": result.get("n_iterations")}


@laliga_app.post("/api/reset")
def api_reset():
    global cache, _mode
    try:
        cache = compute_all()
        return JSONResponse({"status": "ok", "mode": _mode})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)})


@laliga_app.post("/api/refresh")
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


@laliga_app.get("/api/validation")
def api_validation():
    """Pure-Elo validation against the real results ledger (UCL parity)."""
    try:
        results = _load_results_pipeline(DATA_DIR)
        if not results:
            return JSONResponse({"error": "no results data available", "validation": None})

        elo_ratings = cache.get("elo_ratings", {})
        if not elo_ratings:
            elo_ratings = load_elo_ratings(DATA_DIR)

        from football_core.evaluation import compute_metrics

        predictions: list[float] = []
        actuals: list[float] = []
        for m in results:
            ta, tb = m["home_team"], m["away_team"]
            pred = expected_score(elo_ratings.get(ta, 1500.0), elo_ratings.get(tb, 1500.0))
            if m.get("winner") == ta:
                actual = 1.0
            elif m.get("winner") == tb:
                actual = 0.0
            else:
                actual = 0.5
            predictions.append(pred)
            actuals.append(actual)
        metrics = compute_metrics(predictions, actuals)
        return JSONResponse({
            "validation": {
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "n_matches_fetched": len(results),
                "n_matches_matched": len(predictions),
                "prediction_metrics": {
                    "brier": round(metrics["brier"], 6),
                    "log_loss": round(metrics["log_loss"], 6),
                    "accuracy": round(metrics["accuracy"], 6),
                    "n": metrics["n"],
                },
            },
            "calibration_available": False,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@laliga_app.get("/api/report")
def api_report():
    snapshot_path = DATA_DIR / "snapshot.json"
    if not snapshot_path.exists():
        return JSONResponse({"error": "no snapshot available — run a simulation first"})
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@laliga_app.get("/api/simulation/progress/{task_id}")
def api_simulation_progress(task_id: str):
    return JSONResponse(service.poll(task_id))


@laliga_app.get("/api/state")
def api_state():
    return JSONResponse(_competition_state())


# ── Match insight ─────────────────────────────────────────────────────────


def _find_match(match_id: str) -> dict | None:
    for m in _load_results_pipeline(DATA_DIR):
        if m.get("match_id") == match_id:
            return {**m, "round": "Regular Season"}
    for f in _load_fixtures_pipeline(DATA_DIR):
        if f.get("match_id") == match_id:
            return {**f, "round": "Regular Season",
                    "home_score": None, "away_score": None}
    return None


@laliga_app.get("/api/match/insight")
def api_match_insight(match_id: str = "", context: str = ""):
    if not match_id:
        return JSONResponse({"error": "match_id parameter required"})
    match_data = _find_match(match_id)
    if not match_data:
        return JSONResponse({"error": "match not found"})

    ta = match_data.get("team_a") or match_data.get("home_team") or ""
    tb = match_data.get("team_b") or match_data.get("away_team") or ""
    round_label = match_data.get("round", "Regular Season")

    has_scores = (
        match_data.get("home_score") is not None
        and match_data.get("away_score") is not None
    )
    winner = match_data.get("winner") or ""
    score = (
        {"home": match_data["home_score"], "away": match_data["away_score"]}
        if has_scores else None
    )
    played_flag = bool(winner) or has_scores

    provenance = "official"
    if context == "simulated":
        provenance = "simulated"

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
                elo_ratings=elo_map, played_results=[],
            )
            bp = engine.evaluate({"team_a": ta, "team_b": tb, "match_id": match_id}, ctx)
            blended_prob = round(bp.home_prob, 4)
            prob_available = True
            prob_reason = None
            for sig, sd in bp.signal_breakdown.items():
                signals_with_weights[sig] = {
                    "probability": round(sd.get("home", 0.5), 4),
                    "weight": round(sd.get("weight", 0), 4),
                    "label": sig.replace("_", " ").title(),
                }
        except Exception:
            blended_prob = None
            prob_available = False
            prob_reason = "engine_evaluation_failed"

    outcome = laliga_outcome_dist_blend(blended_prob, elo_a, elo_b)

    results = cache.get("_results", [])
    form_trends: dict = {}
    h2h = {"a_wins": 0, "b_wins": 0, "draws": 0, "total": 0}
    if results:
        form_trends = {ta: _laliga_form_trend_pipeline(ta, results),
                       tb: _laliga_form_trend_pipeline(tb, results)}
        h2h = _laliga_head_to_head_pipeline(ta, tb, results)

    insight = _laliga_insight_text_pipeline(ta, tb, signals_with_weights, form_trends,
                                            h2h, outcome or {}, cache.get("signals", {}))

    return JSONResponse({
        "match_id": match_id,
        "round": round_label,
        "teams": {"a": ta, "b": tb},
        "kind": "match",
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


def laliga_outcome_dist_blend(blended_prob: float | None, elo_a: float, elo_b: float):
    if blended_prob is None:
        return None
    return _laliga_outcome_dist_pipeline(blended_prob, elo_a, elo_b)


@laliga_app.post("/api/what-if")
def api_what_if(req: dict = None):
    """Counterfactual: shift one match's teams Elo +-delta, re-run seeded MC."""
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

    match_data = _find_match(match_id)
    if not match_data:
        return JSONResponse({"error": "match not found"})
    ta = match_data.get("team_a") or match_data.get("home_team") or ""
    tb = match_data.get("team_b") or match_data.get("away_team") or ""

    baseline_elos = dict(cache.get("elo_ratings", {})) or load_elo_ratings(DATA_DIR)

    baseline = _run_mc_simulation_pipeline(
        str(DATA_DIR), n_iterations=n_iterations, seed=42,
        elo_ratings_override=dict(baseline_elos),
    )
    adjusted_elos = dict(baseline_elos)
    adjusted_elos[ta] = baseline_elos.get(ta, 1500.0) + elo_delta
    adjusted_elos[tb] = max(100.0, baseline_elos.get(tb, 1500.0) - elo_delta)
    adjusted = _run_mc_simulation_pipeline(
        str(DATA_DIR), n_iterations=n_iterations, seed=42,
        elo_ratings_override=adjusted_elos,
    )

    def _entry(bprob: float, aprob: float) -> dict:
        return {"baseline": round(bprob, 4), "adjusted": round(aprob, 4),
                "delta": round(aprob - bprob, 4)}

    all_teams = sorted(baseline["elo_ratings"].keys())
    bprobs_raw = {o["team"]: o["champion_prob"] for o in baseline["odds"]}
    aprobs_raw = {o["team"]: o["champion_prob"] for o in adjusted["odds"]}
    bprobs = {t: bprobs_raw.get(t, 0.0) for t in all_teams}
    aprobs = {t: aprobs_raw.get(t, 0.0) for t in all_teams}

    def _top5(probs: dict) -> list[dict]:
        ranked = sorted(probs, key=lambda t: probs[t], reverse=True)[:5]
        return [{"team": t, "champion": round(probs[t], 4)} for t in ranked]

    return JSONResponse({
        "mode": "structured",
        "match_id": match_id,
        "elo_changes": {ta: adjusted_elos[ta], tb: adjusted_elos[tb]},
        "iterations": n_iterations,
        "teams": {ta: _entry(bprobs.get(ta, 0), aprobs.get(ta, 0)),
                  tb: _entry(bprobs.get(tb, 0), aprobs.get(tb, 0))},
        "top5_baseline": _top5(bprobs),
        "top5_adjusted": _top5(aprobs),
    })