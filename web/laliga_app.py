"""LaLiga EA Sports — FastAPI sub-app mounted under /laliga.

Full parity with the UCL sub-app's product surface (league-only, no
bracket): data, seasons, standings, odds, signals, simulate, refresh,
reset, validation, report, match insight, and Elo what-if counterfactual.
All tournament logic stays in ``competitions.laliga.src``; this module
only wires transport, the freshness ledger, and the simulation task
service.

State lives in the race-free holder (``web.derived.holder``): one frozen
snapshot per competition, rebound in ONE assignment, with the store
stamp folded in — reads go through ``_snap()``, writes through
``holder.publish_data`` / ``publish_sim`` / ``clear_sim``. No mutable
module globals.
"""
from __future__ import annotations

from football_core.freshness import (
    UNREADABLE,
    read_ledger,
    served_stale,
    store_mtime,
    update_ledger,
)
from football_core.state import atomic_write_text
from football_core.store_stamp import StoreStamp, stamp_store

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import fastapi

from competitions.laliga.src import seasons as season_store
from competitions.laliga.src.constants import (
    BLEND_CALIBRATION_PATH,
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
from competitions.laliga.src.state import build_competition_state
from football_core.elo import expected_score
from football_core.fetcher import derive_success
from football_core.signal import PredictionContext
from web.common import (
    RobustJSONResponse as JSONResponse,
    error_response,
    offline_refresh_report,
    refresh_response_body,
    ts,
)
from web.derived import holder
from web.derived.stamps import LALIGA_ROLES
from web.simulation_service import SimulationTaskService, build_simulation_meta

logger = logging.getLogger(__name__)

_CALIBRATION_THRESHOLD = 30

# Credentials are read at CALL time, never frozen at import: os.environ can
# be populated (or overridden) long after this module was imported, and a
# frozen constant would keep resolving to the empty pre-import value.
def _bsd_key() -> str:
    return os.environ.get("BSD_API_KEY", "")


def _football_data_org_key() -> str:
    return os.environ.get("FOOTBALL_DATA_ORG_KEY", "")


service = SimulationTaskService()


def _active_dir() -> Path:
    """The ACTIVE season's store dir (LaLiga stores are season-routed)."""
    return Path(season_store.resolve_active_data_dir(DATA_DIR))


def _observed_stamp() -> StoreStamp:
    return stamp_store(_active_dir(), LALIGA_ROLES)


def _build_state() -> tuple[dict, str]:
    data = compute_all()          # global-free; returns dict with "mode" key
    return data, data.get("mode", "results")


def _snap():
    return holder.get_or_rebuild("laliga", _observed_stamp(), _build_state)


def _refresh_report_path() -> Path:
    return Path(__file__).parent / "last_refresh.json"


def _load_refresh_ledger(refresh_path: Path | None = None) -> dict:
    """Read the shared freshness ledger — one definition of "unreadable".

    ``{}`` still means "the file has never been written"; a corrupt or
    unreadable ledger returns the explicit ``{"ledger": "unreadable",
    "detail": ...}`` marker instead (D-11).
    """
    refresh_path = refresh_path if refresh_path is not None else _refresh_report_path()
    return read_ledger(refresh_path)


#: Truthful default when this process has never recorded a refresh
#: (plan 02-06): a first-ever plain read must not read as fresh/success
#: without evidence. ``_refresh_report_for`` still serves the
#: season-scoped store-truthful entry; this is the umbrella/boot default.
_NOT_ATTEMPTED: dict = {
    "provider": None,
    "attempted": False,
    "success": False,
    "error": None,
    "stale": True,
    "reason": "not_attempted",
}

_refresh_report: dict = dict(_NOT_ATTEMPTED)
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


#: Store→file mapping for the availability map the LaLiga payloads serve.
_LALIGA_STORE_FILES = {
    "fixtures": "fixtures.json",
    "results": "results.json",
}
_LALIGA_ELO_FILE = "elo_seed.json"


def _live_availability() -> tuple[dict, dict]:
    """``(map, reasons)`` from ``load_json_store`` over the active season dir."""
    from football_core.domain import DataAvailability, load_json_store

    adir = Path(season_store.season_dir(DATA_DIR, _active_season_token()))
    mapping: dict = {}
    reasons: dict = {}
    for key, fname in _LALIGA_STORE_FILES.items():
        _payload, state, detail = load_json_store(adir / fname)
        mapping[key] = state.value
        if state in (DataAvailability.MISSING, DataAvailability.UNAVAILABLE):
            reasons[key] = detail or f"store file missing: {adir / fname}"
    _payload, elo_state, elo_detail = load_json_store(DATA_DIR / _LALIGA_ELO_FILE)
    mapping["elo_ratings"] = elo_state.value
    if elo_state in (DataAvailability.MISSING, DataAvailability.UNAVAILABLE):
        reasons["elo_ratings"] = (
            elo_detail or f"store file missing: {DATA_DIR / _LALIGA_ELO_FILE}")
    return mapping, reasons


def _synthesize_season_report(season: str) -> dict:
    fixtures = _load_fixtures_pipeline(DATA_DIR, season)
    results = _load_results_pipeline(DATA_DIR, season)
    # D-13: success is DERIVED from the store's own counts — the shipped
    # store is the evidence. No provider was asked in this process, so a
    # non-success verdict is never "provider-empty".
    n_played = len(results)
    counters = {"received": n_played, "normalized": n_played,
                "ingested": n_played, "skipped_unmatchable": 0,
                "skipped_no_target": 0, "skipped_missing_score": 0}
    success, reason = derive_success(None, bool(fixtures), counters)
    if not success:
        reason = "deferred"
    return {
        "provider": None,
        "attempted": False,
        "success": success,
        "error": None,
        "stale": False,
        "deferred": False,
        "reason": reason,
        "status": "ok",
        "active_season": season,
        "last_refresh": datetime.now(timezone.utc).isoformat(),
        "n_matches": n_played,
        "synth": True,
        "fixtures": len(fixtures),
    }


def _refresh_report_for(season: str) -> dict:
    """Season-scoped refresh report served to the API surface (see D-12).

    Snapshot-skipped process truth is served as-is; every other branch goes
    through :func:`_freshness` so a "fresh" ledger claim the store has
    outgrown is served as stale.
    """
    if _refresh_report.get("skipped_reason"):
        return _refresh_report
    # Session truth: an explicit offline session attempted NOTHING, so no
    # recorded or synthesized "ok" entry may imply a live fetch happened
    # (plan 02-06). Season context survives on the synthesized entry.
    from web.common import not_attempted_report

    offline = not_attempted_report()
    if offline.get("skipped_reason"):
        return {**_synthesize_season_report(season), **offline}
    report = _season_refresh_reports().get(season)
    if report is not None:
        return _freshness(report, _freshness_store_paths(season))
    return _freshness(_synthesize_season_report(season),
                      _freshness_store_paths(season))


def _freshness_store_paths(season: str) -> list[Path]:
    """Which LaLiga stores D-12 compares against (path knowledge: the app).

    Root ``results.json`` is the legacy layout, season files the current one;
    an absent store contributes no mtime. ``odds.json`` and ``snapshot.json``
    are deliberately excluded — the odds layer refetches on demand and the
    snapshot is simulated (02-04), so neither may age the ledger.
    """
    sd = season_store.season_dir(DATA_DIR, season)
    return [
        DATA_DIR / "results.json",
        sd / "results.json",
        sd / "fixtures.json",
    ]


def _freshness(entry: dict, store_paths: list[Path]) -> dict:
    """Serve D-12: a "fresh" claim the store has outgrown becomes stale.

    :func:`football_core.freshness.served_stale` holds the rule (shared,
    unit-tested); this is only the store-path wiring. The returned dict is a
    *served* copy — the ledger file is not rewritten — and the unreadable
    marker keeps its exact shape.
    """
    if not entry or entry.get("stale") or entry.get("ledger") == UNREADABLE:
        return entry
    if served_stale(entry, [store_mtime(p) for p in store_paths]):
        return {**entry, "stale": True}
    return entry


def _store_refresh_report(
    ok: bool, error: str | None, provider_name: str | None,
    n_matches: int | None = None, n_updated: int | None = None,
    finished: dict | None = None, stages: list | None = None,
    active_season: str | None = None, deferred: bool = False,
    reason: str | None = None, status: str | None = None,
    odds_status: dict | None = None,
) -> dict:
    """Record the LaLiga refresh outcome for the API surface + ledger.

    ``finished``/``stages`` mirror ``web.ucl_app._store_refresh_report``:
    the brain's IngestReport counters and OQ7 stage rows must survive into
    the entry, otherwise ``POST /laliga/api/refresh`` (plan 02-06, INGEST-02)
    cannot serve the full report contract.
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
        **({"active_season": active_season} if active_season is not None else {}),
        **({"deferred": deferred} if deferred else {}),
        **({"reason": reason} if reason is not None else {}),
        **({"status": status} if status is not None else {}),
        **({"odds_status": odds_status} if odds_status is not None else {}),
    }
    if active_season:
        cache_entry[str(active_season)] = _refresh_report
    try:
        refresh_path = _refresh_report_path()
        entry = dict(_refresh_report)
        entry["mode"] = provider_name
        entry["n_matches"] = n_matches or 0
        entry["n_updated"] = n_updated or 0
        # Single-writer ledger (D-18): football_core.freshness owns the lock,
        # the atomic write and the loud failure — no hand-rolled RMW here.
        update_ledger(refresh_path, "laliga", entry)
        if active_season:
            update_ledger(refresh_path, ("laliga_seasons", str(active_season)), entry)
    except Exception:
        logger.exception(
            "[LaLiga] refresh outcome could NOT be persisted to the freshness ledger"
        )
    return _refresh_report


def _fetch_live_data():
    """Delegate acquisition to the LaLiga brain; record the ledger entry."""
    from web.startup import is_snapshot_mode

    if is_snapshot_mode():
        logger.warning("[LaLiga] snapshot mode - live refresh skipped")
        # D-13: nothing was attempted, so nothing succeeded (reclassify).
        # Full IngestReport schema (plan 02-06): the offline outcome must
        # answer an explicit refresh with the SAME key set as a real run.
        globals()["_refresh_report"] = offline_refresh_report()
        return None

    active_season = _active_season_token()
    from web.common import get_data_provider
    from competitions.laliga.src.pipeline import fetch_live_data as _brain_fetch

    provider = get_data_provider(
        _bsd_key(), _football_data_org_key(), LALIGA_BSD_LEAGUE_ID)
    if provider is None:
        logger.warning(
            "[LaLiga] NOT_CONFIGURED - no data provider available "
            "(BSD key configured: %s, football-data key configured: %s, "
            "DATA_PROVIDER=%s); skipping live fetch",
            bool(_bsd_key()), bool(_football_data_org_key()),
            os.environ.get("DATA_PROVIDER", "") or "(unset)",
        )
        _store_refresh_report(False, "no data provider configured", None,
                               active_season=active_season)
        return None
    try:
        summary = _brain_fetch(
            str(DATA_DIR),
            bsd_api_key=_bsd_key(),
            provider=provider,
            football_data_org_key=_football_data_org_key(),
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
    # D-13: the ledger verdict comes from the report's DERIVED success, not
    # the transport status — a run that completed (status "ok") while
    # ingesting nothing is not success (mirrors web/ucl_app.py).
    ok = bool(report.get("success")) if isinstance(report, dict) else status == "ok"
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
    # D-13: the ledger verdict is `ok` alone — a deferred fetch is NOT
    # recorded as success (decision 1/2 of 02-02); `reason` still travels
    # through so the UI can present "not published yet".
    _store_refresh_report(ok, error, provider_name,
                           n_matches=n_raw, n_updated=n_updated,
                           finished=report.get("finished"),
                           stages=report.get("stages"),
                           active_season=active_season,
                           deferred=deferred, reason=reason, status=status,
                           odds_status=summary.get("odds"))
    holder.append_boot("laliga", {
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
    try:
        # STAMP-BEFORE-BUILD: sample the stamp BEFORE the build. A store write that lands
        # during the build then publishes the OLDER stamp, and the next
        # request sees a mismatch and rebuilds. Sampling after the build
        # would publish (older data, newer stamp) — stale data served as
        # current, permanently.
        stamp = _observed_stamp()
        result = compute_all()
        if result.get("error"):
            logger.warning("[LaLiga] Cache recomputation failed: %s", result["error"])
            return
        holder.publish_data("laliga", result, result.get("mode", "results"), stamp)
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
    from competitions.laliga.src.pipeline import compute_deterministic
    result = compute_deterministic(data_dir=DATA_DIR)
    result["mode"] = "results"
    if result.get("error"):
        result["boot"] = [{"step": "LaLiga compute", "status": "error", "elapsed": 0.0,
                           "output": f"[error] {result['error']}"}]
        return result
    result["boot"] = result.get("boot", [])
    from competitions.laliga.src.pipeline import build_signal_engine
    result["_signal_engine"] = build_signal_engine(result.get("elo_ratings", {}))
    return result


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    # Zero provider calls during boot (Exchange 4 v2): caches come from
    # validated on-disk stores; reads stay pure and ingestion happens only
    # via the explicit refresh endpoint, FOOTBALL_PRELOAD_ALL preload or a
    # test (plan 02-06).
    # STAMP-BEFORE-BUILD: the stamp is sampled BEFORE the build (see _recompute_cache).
    stamp = _observed_stamp()
    data, mode = _build_state()
    holder.publish_data("laliga", data, mode, stamp)
    yield


laliga_app = fastapi.FastAPI(lifespan=lifespan)


@laliga_app.exception_handler(Exception)
async def _json_error_handler(request, exc):
    logging.getLogger(__name__).error(
        "[LaLiga] unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse({"error": f"internal error: {exc.__class__.__name__}"},
                        status_code=500)


@laliga_app.get("/api/data")
def api_data():
    # Reads are pure (plan 02-06): no acquisition fires here. Ingestion
    # happens only through the explicit POST /api/refresh endpoint, the
    # FOOTBALL_PRELOAD_ALL preload, or a test driving adapter.refresh().
    n_unplayed, n_total = _match_counts()
    snap = _snap()
    live_map, reasons = _live_availability()
    availability = snap.get("availability") or live_map
    payload = {
        "refresh": _refresh_report_for(_active_season_token()),
        "teams": snap.get("teams", []),
        "all_teams": snap.get("all_teams", []),
        "standings": snap.get("standings", []),
        "n_teams": snap.get("n_teams", 0),
        "n_iterations": snap.get("n_iterations", 0),
        "snapshot_date": snap.get("snapshot_date", ""),
        "champion": snap.get("champion"),
        "mode": snap.get("mode"),
        "availability": availability,
        "phase": snap.get("phase", {}),
        "season": _active_season_token(),
        "n_total_fixtures": n_total,
        "odds_status": (_refresh_report.get("odds_status")
                        or snap.get("odds_status") or {}),
        "simulation": _simulation_state_block(),
        "n_unplayed": n_unplayed,
        "n_played": n_total - n_unplayed,
    }
    if reasons:
        payload["availability_reason"] = reasons
    return JSONResponse(payload)


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
    holder.clear_sim("laliga")
    _recompute_cache()
    return JSONResponse({"status": "ok", "current": pointer,
                         "mode": holder.read_mode("laliga")})


@laliga_app.get("/api/boot")
def api_boot():
    season = _active_season_token()
    # The deterministic compute contributes no boot steps of its own, so the
    # acquisition ledger (the holder's boot slot) is the ONLY source of boot
    # diagnostics. Serve the ledger together with whatever the snapshot
    # carries (e.g. the compute-error entry) so this endpoint never answers
    # with an empty list where real entries exist.
    entries = list(holder.read_boot("laliga")) + list(_snap().get("boot", []))
    return JSONResponse({
        "boot": entries,
        "refresh": _freshness(_refresh_report, _freshness_store_paths(season)),
    })


@laliga_app.get("/api/simulation")
def api_simulation():
    sim = holder.read_sim("laliga")
    return JSONResponse({
        "odds": sim.get("odds", []),
        "standings": sim.get("standings", []),
        "signals": sim.get("signals", {}),
        "elo_ratings": sim.get("elo_ratings", {}),
        "champion": sim.get("champion"),
        "mode": sim.get("mode", _snap().get("mode")),
        "n_iterations": sim.get("n_iterations", 0),
        "snapshot_date": sim.get("snapshot_date", ""),
        "status": sim.get("status", "not_requested"),
        "simulation_meta": sim.get("simulation_meta"),
    })


def _competition_state() -> dict:
    current = season_store.get_current_season(DATA_DIR)
    active_season = current.get("season") if isinstance(current, dict) else None
    return build_competition_state(str(DATA_DIR), mode="results", active_season=active_season,
                                   standings=_snap().get("standings"))


@laliga_app.get("/api/standings")
def api_standings():
    snap = _snap()
    return JSONResponse({
        "standings": snap.get("standings", []),
        "mode": snap.get("mode"),
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
    snap = _snap()
    mode = snap.get("mode")
    return JSONResponse({
        "odds": snap.get("odds", []),
        "mode": mode,
        "season": _active_season_token(),
        "odds_semantics": (
            "achieved_outcome_indicators" if mode == "results"
            else "monte_carlo_probabilities"),
    })


@laliga_app.get("/api/signals")
def api_signals():
    snap = _snap()
    return JSONResponse({
        "signals": snap.get("signals", {}),
        "mode": snap.get("mode"),
        "season": _active_season_token(),
    })


def _season_outcome_undecided() -> bool:
    return _unplayed_match_count() > 0


def _simulation_state_block() -> dict:
    undecided = _season_outcome_undecided()
    sim_status = holder.read_sim("laliga").get("status", "not_requested")
    request_state = {
        "running": "running", "completed": "completed", "failed": "failed",
    }.get(sim_status, "not_requested")
    if not undecided:
        return {"availability": "not_needed", "reason": None,
                "request_state": request_state, "what_if": True}
    return {"availability": "available", "reason": None,
            "request_state": request_state, "what_if": False}


def _seed_as_of() -> str:
    """The shipped seed file's own snapshot date, or "" when unreadable."""
    try:
        payload = json.loads((DATA_DIR / "elo_seed.json").read_text(encoding="utf-8"))
        value = payload.get("snapshot_date") if isinstance(payload, dict) else None
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


@laliga_app.get("/api/elo")
def api_elo():
    """Elo ratings for the Elo view: the loaded cache first, else the shipped
    seed file. No fetch, no recompute, never a 500.
    """
    ratings = {
        team: float(value)
        for team, value in (_snap().get("elo_ratings") or {}).items()
        if isinstance(value, (int, float))
    } or load_elo_ratings(DATA_DIR)
    if not ratings:
        return JSONResponse({"ratings": {}, "source": "empty", "as_of": ""})
    # The cache itself is built from the shipped seed (compute_deterministic
    # -> load_elo_ratings), so the seed's own snapshot_date is the real date.
    return JSONResponse({"ratings": ratings, "source": "seed", "as_of": _seed_as_of()})


def _cold_start_blend(n_matches: int) -> dict:
    """Honest no-calibration payload (same shape as the World Cup route)."""
    return {
        "n_signals_available": 0,
        "available_signals": [],
        "blend_weights": {},
        "backtest_briers": {},
        "calibration_status": "cold_start",
        "n_matches_for_calibration": int(n_matches),
        "threshold": _CALIBRATION_THRESHOLD,
    }


@laliga_app.get("/api/blend")
def api_blend():
    """Blend/calibration view.

    Real weights come from the on-disk artifact produced by
    ``competitions.laliga.src.pipeline.run_calibration_task`` (schema
    identical to UCL's). Without that artifact there is nothing to report,
    so the answer is an honest cold start — never invented weights.

    Note the artifact is deliberately NOT ``config/signal_weights.json``:
    that file is the deployed *engine* blend, not a fit, so reporting it
    as calibration output would relabel hand-set weights as fitted.
    """
    try:
        config = (json.loads(BLEND_CALIBRATION_PATH.read_text(encoding="utf-8"))
                  if BLEND_CALIBRATION_PATH.exists() else {})
        weights = {
            name: float(value)
            for name, value in (config.get("weights") or {}).items()
            if isinstance(value, (int, float))
        }
        n_matches = int(config.get("n_matches") or len(_snap().get("_results") or []))
        if not weights:
            return JSONResponse(_cold_start_blend(n_matches))
        return JSONResponse({
            "n_signals_available": len(weights),
            "available_signals": sorted(weights),
            "blend_weights": weights,
            # The artifact stores log-loss, not Brier: report no Brier
            # rather than relabelling the metric.
            "backtest_briers": {},
            "calibration_status": (
                "calibrated" if n_matches >= _CALIBRATION_THRESHOLD else "cold_start"),
            "n_matches_for_calibration": n_matches,
            "threshold": _CALIBRATION_THRESHOLD,
        })
    except Exception:
        logger.exception("[LaLiga] blend info unavailable")
        return JSONResponse(_cold_start_blend(0))


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
    holder.publish_boot("laliga", ())
    cached_elo = _snap().get("elo_ratings") or None

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
    """Cache/snapshot side effects. Returns the public task summary."""
    payload = dict(result)
    payload["boot"] = list(holder.read_boot("laliga"))
    meta_block = result.get("_meta") or {}
    meta = build_simulation_meta(
        requested_count=count,
        actual_count=result.get("n_iterations"),
        seed=meta_block.get("seed"),
        provenance_extra=meta_block.get("provenance") or {},
        engine_version=meta_block.get("engine_version"),
    )
    payload["status"] = "completed"
    payload["simulation_meta"] = meta
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
        "simulation_meta": meta,
        "odds": result.get("odds", []),
        "standings": result.get("standings", []),
        "signals": result.get("signals", {}),
        "elo_ratings": result.get("elo_ratings", {}),
    }
    snapshot_path = DATA_DIR / "snapshot.json"
    atomic_write_text(
        snapshot_path,
        json.dumps(snapshot_data, indent=2, default=str, ensure_ascii=False),
    )
    holder.publish_sim("laliga", payload)  # ONE atomic assignment; never mutate after
    return {"champion": result.get("champion"),
            "count": result.get("n_iterations")}


@laliga_app.post("/api/reset")
def api_reset():
    try:
        # STAMP-BEFORE-BUILD: sample the stamp BEFORE the build (see _recompute_cache).
        stamp = _observed_stamp()
        data, mode = _build_state()
        holder.publish_data("laliga", data, mode, stamp)
        return JSONResponse({"status": "ok", "mode": holder.read_mode("laliga")})
    except Exception as e:
        return error_response(e, context="laliga reset")


@laliga_app.post("/api/refresh")
def api_refresh():
    """Explicit acquisition trigger for LaLiga (plan 02-06).

    No snapshot short-circuit here: the wrapper self-gates, so an explicit
    offline session records its truthful ``attempted=False`` +
    ``skipped_reason`` report on ZERO network instead of returning an
    opaque ``{"status": "skipped"}``. The body is the full report (stages,
    counters, season, staleness); HTTP stays 200 because a truthful
    failure is data, not an HTTP error.
    """
    from web.competitions import REGISTRY

    try:
        # STAMP-BEFORE-BUILD: the stamp is sampled BEFORE the build, so the published pair
        # is never (older data, newer stamp). The pre-ingest sample is what
        # tells us whether the ingest actually wrote the canonical stores.
        stamp_before = _observed_stamp()
        report = dict(REGISTRY.get("laliga").refresh())
        stamp_after = _observed_stamp()
        if stamp_after != stamp_before:
            # D-06: the simulation is retired AT the store write, BEFORE the
            # rebuild publishes the new facts. Clearing it after the rebuild
            # left a window in which GET /api/simulation still served the
            # previous run while GET /api/data served the new facts.
            holder.clear_sim("laliga")
        data, mode = _build_state()
        holder.publish_data("laliga", data, mode, stamp_after)
    except Exception as e:
        return error_response(
            e, status=503, context="laliga refresh",
            public="Live refresh unavailable")
    return JSONResponse(refresh_response_body(report, mode=holder.read_mode("laliga")))


@laliga_app.get("/api/validation")
def api_validation():
    """Pure-Elo validation against the real results ledger (UCL parity)."""
    try:
        results = _load_results_pipeline(DATA_DIR)
        if not results:
            return JSONResponse({"error": "no results data available", "validation": None})

        elo_ratings = _snap().get("elo_ratings", {})
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
                    "brier": round(metrics["brier"], 6) if metrics["brier"] is not None else None,
                    "log_loss": round(metrics["log_loss"], 6) if metrics["log_loss"] is not None else None,
                    "accuracy": round(metrics["accuracy"], 6) if metrics["accuracy"] is not None else None,
                    "n": metrics["n"],
                },
            },
            "calibration_available": False,
        })
    except Exception as e:
        return error_response(e, context="laliga validation")


@laliga_app.get("/api/report")
def api_report():
    snapshot_path = DATA_DIR / "snapshot.json"
    if not snapshot_path.exists():
        return JSONResponse({"error": "no snapshot available — run a simulation first"})
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return error_response(e, context="laliga report")


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

    snap = _snap()
    elo_map = snap.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    elo_prob = expected_score(elo_a, elo_b)

    engine = snap.get("_signal_engine")
    signals_with_weights: dict = {}
    blended_prob: float | None = None
    prob_available = False
    prob_reason = "engine_unavailable"
    if engine:
        from competitions.laliga.src.odds import decorate_matches, load_odds
        decorate_matches([match_data], load_odds(DATA_DIR))
        eval_match = {
            "team_a": ta, "team_b": tb, "match_id": match_id,
            "odds_home": match_data.get("odds_home"),
            "odds_draw": match_data.get("odds_draw"),
            "odds_away": match_data.get("odds_away"),
        }
        try:
            ctx = PredictionContext(
                fixtures=[eval_match],
                elo_ratings=elo_map, played_results=[],
            )
            bp = engine.evaluate(eval_match, ctx)
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

    results = snap.get("_results", [])
    form_trends: dict = {}
    h2h = {"a_wins": 0, "b_wins": 0, "draws": 0, "total": 0}
    if results:
        form_trends = {ta: _laliga_form_trend_pipeline(ta, results),
                       tb: _laliga_form_trend_pipeline(tb, results)}
        h2h = _laliga_head_to_head_pipeline(ta, tb, results)

    insight = _laliga_insight_text_pipeline(ta, tb, signals_with_weights, form_trends,
                                             h2h, outcome or {}, snap.get("signals", {}))

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

    baseline_elos = dict(_snap().get("elo_ratings", {})) or load_elo_ratings(DATA_DIR)

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
