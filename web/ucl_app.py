"""UEFA Champions League — FastAPI sub-app mounted under /ucl."""
from __future__ import annotations

import logging

from football_core.freshness import (
    UNREADABLE,
    read_ledger,
    served_stale,
    store_mtime,
    update_ledger,
)
from football_core.state import atomic_write_text

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import fastapi

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
from football_core.fetcher import derive_success
from football_core.signal import PredictionContext
from football_core.simulation import SimulationContractError

from typing import Optional

from web.common import (
    error_response,
    offline_refresh_report,
    refresh_response_body,
    ts,
)
from football_core.domain import DataAvailability, load_json_store
from football_core.store_stamp import StoreStamp, stamp_store
from web.common import RobustJSONResponse as JSONResponse
from web.derived import holder
from web.derived.stamps import UCL_ROLES
from web.simulation_service import SimulationTaskService, build_simulation_meta

UCL_LEAGUE_ID: int = 7

logger = logging.getLogger(__name__)


# Credentials are read at CALL time, never frozen at import: os.environ can
# be populated (or overridden) long after this module was imported, and a
# frozen constant would keep resolving to the empty pre-import value.
def _bsd_key() -> str:
    return os.environ.get("BSD_API_KEY", "")


def _football_data_org_key() -> str:
    return os.environ.get("FOOTBALL_DATA_ORG_KEY", "")

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

#: Store→file mapping for the availability map the UCL payloads serve.
_UCL_STORE_FILES = {
    "league_results": "results.json",
    "fixtures": "fixtures.json",
    "knockout_results": "knockout_results.json",
}


def _live_availability() -> tuple[dict, dict]:
    """``(map, reasons)`` from ``load_json_store`` over the active season dir.

    Reasons carry MISSING/UNAVAILABLE entries only; the pair is the live
    truth used as fallback when the cache was never built, and the reasons
    are always served alongside the (cache-preferred) availability map.
    """
    from competitions.ucl.src.orchestrator import resolve_active_data_dir

    adir = Path(resolve_active_data_dir(DATA_DIR))
    mapping: dict = {}
    reasons: dict = {}
    for key, fname in _UCL_STORE_FILES.items():
        _payload, state, detail = load_json_store(adir / fname)
        mapping[key] = state.value
        if state in (DataAvailability.MISSING, DataAvailability.UNAVAILABLE):
            reasons[key] = detail or f"store file missing: {adir / fname}"
    return mapping, reasons


UCL_DIR = Path(__file__).parent.parent / "competitions" / "ucl"
#: Calibration artifact written by competitions.ucl.src.calibrate.
_CALIBRATION_PATH = UCL_DIR / "config" / "signal_weights.json"
#: Matches required before weights count as calibrated (mirrors World Cup).
_CALIBRATION_THRESHOLD = 30

service = SimulationTaskService()


def _active_dir() -> Path:
    from competitions.ucl.src.orchestrator import resolve_active_data_dir
    return Path(resolve_active_data_dir(DATA_DIR))


def _observed_stamp() -> StoreStamp:
    return stamp_store(_active_dir(), UCL_ROLES)


def _build_state() -> tuple[dict, str]:
    data = compute_all()          # global-free; returns dict with "mode" key
    return data, data.get("mode", "results")


def _snap():
    return holder.get_or_rebuild("ucl", _observed_stamp(), _build_state)


def _refresh_report_path() -> Path:
    """Seam for tests: location of the shared freshness ledger."""
    return Path(__file__).parent / "last_refresh.json"


def _load_refresh_ledger(refresh_path: Path | None = None) -> dict:
    """Read the shared freshness ledger — one definition of "unreadable".

    ``{}`` still means "the file has never been written"; a corrupt or
    unreadable ledger returns the explicit ``{"ledger": "unreadable",
    "detail": ...}`` marker instead (D-11 — an I/O failure must not look like
    "no refresh has ever run").
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
#: Season-scoped refresh report store, keyed by season display id (e.g.
#: "2026/27"). The API serves the ACTIVE season's own entry so one season's
#: deferred/stale outcome never leaks onto another season's view.
_refresh_reports: dict[str, dict] = {}
_refresh_reports_seeded: bool = False


def _season_refresh_reports() -> dict:
    """Lazily hydrate the per-season store from the persisted ledger once.

    Backward-compatible loading: both the legacy single ``"ucl"`` entry
    (attached under its recorded ``active_season``) and the newer
    ``"ucl_seasons"`` map are folded in. Reports recorded THIS process
    always win over file state (``setdefault`` keeps the newest).
    """
    global _refresh_reports_seeded
    if not _refresh_reports_seeded:
        _refresh_reports_seeded = True
        data = _load_refresh_ledger()
        seasons = data.get("ucl_seasons")
        if isinstance(seasons, dict):
            for season, report in seasons.items():
                if isinstance(report, dict):
                    _refresh_reports.setdefault(str(season), report)
        legacy = data.get("ucl")
        if isinstance(legacy, dict) and legacy.get("active_season"):
            _refresh_reports.setdefault(str(legacy["active_season"]), legacy)
    return _refresh_reports


def _active_season_token() -> str:
    """Canonical season token used for refresh scoping.

    Mirrors what ``_fetch_live_data`` records as ``active_season``: the
    current.json pointer when present, otherwise the shipped local
    historical season.
    """
    from competitions.ucl.src.seasons import (
        LOCAL_HISTORICAL_SEASON, get_current_season,
    )
    current = get_current_season(DATA_DIR)
    season = (
        current.get("season")
        if isinstance(current, dict) and current.get("season")
        else None
    )
    return str(season or LOCAL_HISTORICAL_SEASON)


def _synthesize_season_report(season: str) -> dict:
    """Store-truthful standby report for a season nobody refreshed this process.

    A settled season (e.g. completed historical 2025/26, 144/144 matches
    played) derives success from its store counts. An empty store
    derives a non-success verdict with reason "deferred": nothing was
    published yet (no provider was asked, so never "provider-empty").
    ``stale=False`` always — the shipped store IS the evidence, and no
    claim about a provider is made (``attempted=False``) because no fetch
    happened for THIS season in this process.
    """
    n_unplayed, n_total = _match_counts()
    played = n_total - n_unplayed
    # D-13: success is DERIVED from the store's own counts — the shipped
    # store is the evidence, so a started/settled season derives True and an
    # empty store derives a deferred verdict. No provider was ever asked in
    # this process, so a non-success verdict is never "provider-empty".
    counters = {"received": played, "normalized": played, "ingested": played,
                "skipped_unmatchable": 0, "skipped_no_target": 0,
                "skipped_missing_score": 0}
    success, reason = derive_success(None, n_total > 0, counters)
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
        "n_matches": played,
        "synth": True,
    }


def _refresh_report_for(season: str) -> dict:
    """Season-scoped refresh report served to the API surface.

    The snapshot-skipped report is process truth (no live data for ANY
    season) and is served as-is. Otherwise the active season receives its
    OWN recorded entry; a season with no recorded report gets a synthesized
    store-truthful entry instead of inheriting another season's.

    Every branch except process truth goes through D-12 (:func:`_freshness`):
    a ledger entry claiming fresh while the store has moved on is served stale.
    """
    if _refresh_report.get("skipped_reason"):
        return _refresh_report
    # Session truth: an explicit offline session attempted NOTHING, so no
    # recorded or synthesized "ok" entry may imply a live fetch happened.
    # The disclosure rides on the synthesized entry so season context
    # (active season, played counts) survives (plan 02-06).
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
    """Which UCL stores D-12 compares against (path knowledge: the app).

    Root files are the legacy layout, season files the current one; whichever
    is absent simply contributes no mtime (a store that does not exist cannot
    make a report stale).
    """
    from competitions.ucl.src.seasons import season_dir

    sd = season_dir(DATA_DIR, season)
    return [
        DATA_DIR / "results.json",
        DATA_DIR / "knockout_results.json",
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


def _store_refresh_report(ok: bool, error: str | None, provider_name: str | None,
                          n_matches: int | None = None, n_updated: int | None = None,
                          finished: dict | None = None, stages: list | None = None,
                          per_season: dict | None = None, active_season: str | None = None,
                          deferred: bool = False, reason: str | None = None,
                          status: str | None = None) -> dict:
    """Record the UCL refresh outcome for the API surface + last_refresh.json.

    Single writer for the UCL entries (umbrella + season-scoped): the
    ingestion itself never touches the ledger, it only returns the
    structured IngestReport payload.
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
        **({"per_season": per_season} if per_season is not None else {}),
        **({"active_season": active_season} if active_season is not None else {}),
        **({"deferred": deferred} if deferred else {}),
        **({"reason": reason} if reason is not None else {}),
        **({"status": status} if status is not None else {}),
    }
    if active_season:
        _refresh_reports[str(active_season)] = _refresh_report
    try:
        refresh_path = _refresh_report_path()
        entry = dict(_refresh_report)
        entry["mode"] = provider_name
        entry["n_matches"] = n_matches or 0
        entry["n_updated"] = n_updated or 0
        # Single-writer ledger (D-18): football_core.freshness owns the lock,
        # the atomic write and the loud failure — no hand-rolled RMW here.
        # Legacy single-entry slot stays the latest report (backward
        # compatible with existing readers of last_refresh.json["ucl"]).
        update_ledger(refresh_path, "ucl", entry)
        if active_season:
            update_ledger(refresh_path, ("ucl_seasons", str(active_season)), entry)
    except Exception:
        logger.exception(
            "[UCL] refresh outcome could NOT be persisted to the freshness ledger"
        )
    return _refresh_report


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
        holder.append_boot("ucl", {"step": "UCL live fetch", "status": "skip",
                                   "elapsed": 0.0,
                                   "output": f"[{ts()}] Snapshot mode - live refresh skipped"})
        # Parity with WC: record WHY no live fetch happened so the frontend
        # can disclose snapshot data instead of silently looking live-fresh.
        # D-13: nothing was attempted, so nothing succeeded (reclassify).
        # Full IngestReport schema (plan 02-06): the offline outcome must
        # answer an explicit refresh with the SAME key set as a real run.
        globals()["_refresh_report"] = offline_refresh_report()
        return

    # Season-scoped freshness: every outcome (including genuine failures)
    # is recorded against the season it happened on.
    active_season = _active_season_token()

    from web.common import get_data_provider
    from competitions.ucl.src.pipeline import fetch_live_data as _brain_fetch

    provider = get_data_provider(
        _bsd_key(), _football_data_org_key(), UCL_LEAGUE_ID)
    if provider is None:
        logger.warning(
            "[UCL] NOT_CONFIGURED - no data provider available "
            "(BSD key configured: %s, football-data key configured: %s, "
            "DATA_PROVIDER=%s); skipping live fetch",
            bool(_bsd_key()), bool(_football_data_org_key()),
            os.environ.get("DATA_PROVIDER", "") or "(unset)",
        )
        holder.append_boot("ucl", {"step": "UCL live fetch", "status": "skip", "elapsed": 0.0, "output": f"[{ts()}] No data provider configured"})
        _store_refresh_report(False, "no data provider configured", None,
                              active_season=active_season)
        return

    try:
        # The stamp is sampled before the ingest, so the post-ingest sample
        # can tell whether the canonical stores actually changed.
        stamp_before = _observed_stamp()
        summary = _brain_fetch(
            str(DATA_DIR), _bsd_key(),
            football_data_org_key=_football_data_org_key(),
            ucl_league_id=UCL_LEAGUE_ID,
            provider=provider,
        )
    except Exception as exc:  # never let a refresh crash the request path
        logger.warning("[UCL] live fetch raised: %s — UCL data may be STALE", exc)
        _store_refresh_report(False, f"{exc.__class__.__name__}: {exc}",
                              type(provider).__name__, active_season=active_season)
        return
    report = summary.get("report") or {}
    status = summary.get("status")
    # D-13: the ledger verdict comes from the report's DERIVED success, not
    # from the transport status — a run that completed (status "ok") while
    # ingesting nothing (e.g. a fixtures-only refresh) is not success.
    ok = bool(report.get("success")) if isinstance(report, dict) else status == "ok"
    deferred = status == "deferred"
    reason = summary.get("reason")
    provider_name = summary.get("provider_name") or type(provider).__name__
    n_raw = int(summary.get("n_raw") or 0)
    n_updated = int(summary.get("n_updated") or 0)
    error = report.get("error") if not (ok or deferred) else getattr(provider, "last_error", None)
    if deferred:
        logger.info("[UCL] CONFIGURED_BUT_UNAVAILABLE - provider has no "
                    "published match data yet for the active season "
                    "(draw-derived fixtures shown)")
    elif not ok:
        logger.warning("[UCL] CONFIGURED_BUT_UNAVAILABLE - refresh failed: "
                       "%s — UCL data may be STALE",
                       error or "no ingestable matches")
    else:
        logger.info("[UCL] CONNECTED via %s: %s raw matches, %s updated",
                    provider_name, n_raw, n_updated)
    # D-13: the ledger verdict is `ok` alone — a deferred fetch is NOT
    # recorded as success (decision 1/2 of 02-02); `deferred`/`reason` still
    # travel through so the UI can present "not published yet".
    _store_refresh_report(ok, error, provider_name,
                          n_matches=n_raw, n_updated=n_updated,
                          finished=report.get("finished"),
                          stages=report.get("stages"),
                          per_season=summary.get("per_season"),
                          active_season=active_season,
                          deferred=deferred, reason=reason, status=status)
    boot_status = "deferred" if deferred else ("ok" if ok else "skip")
    holder.append_boot("ucl", {
        "step": "UCL live fetch", "status": boot_status, "elapsed": 0.0,
        "output": f"[{ts()}] {provider_name}: {n_raw} raw matches, {n_updated} updated",
    })
    # Exchange 5: if a new season was activated by the ingest, recompute
    # the cache so the API serves fresh data immediately.
    if ok:
        # D-06: this hook may publish the new facts itself (via
        # _maybe_recompute_cache_after_ingest), so the simulation must be
        # retired HERE — at the store write, before that publish. Retiring
        # it after the publish left a window in which GET /api/simulation
        # served the previous run next to the new facts.
        if _observed_stamp() != stamp_before:
            holder.clear_sim("ucl")
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
        old_mode = holder.read_mode("ucl")
        # STAMP-BEFORE-BUILD: sample the stamp BEFORE the build, so the published pair is
        # never (older data, newer stamp) — the pair a later request would
        # match and serve as current, permanently.
        stamp = _observed_stamp()
        new_result = compute_all()
        if new_result.get("error"):
            logger.warning("[UCL] Cache recomputation failed: %s", new_result["error"])
            return
        holder.publish_data("ucl", new_result, new_result.get("mode", "results"), stamp)
        if new_result.get("mode") != old_mode:
            logger.info("[UCL] Cache recomputed: mode changed from %s to %s",
                        old_mode, new_result.get("mode"))
    except Exception as exc:
        logger.warning("[UCL] Cache recomputation failed: %s", exc)


def _load_results() -> list[dict]:
    """Load results from the active season's data directory."""
    from competitions.ucl.src.orchestrator import resolve_active_data_dir
    return _load_results_pipeline(resolve_active_data_dir(DATA_DIR))


def _load_knockout_results() -> dict | None:
    """Load knockout results from the active season only."""
    from competitions.ucl.src.orchestrator import resolve_active_data_dir
    return _load_knockout_results_pipeline(resolve_active_data_dir(DATA_DIR))


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
    from competitions.ucl.src.orchestrator import run_deterministic_compute as _f
    result = _f(str(DATA_DIR), bsd_api_key=_bsd_key())
    result["mode"] = "results"
    result["boot"] = result.get("boot", [])
    return result


def compute_all() -> dict:
    from competitions.ucl.src.orchestrator import resolve_compute_mode
    mode, mode_reason = resolve_compute_mode(str(DATA_DIR))
    if mode == "results":
        return deterministic_compute()
    if mode == "error":
        # Real results exist but are unreadable: surface the failure instead
        # of fabricating a simulated season over them.
        return {
            "error": mode_reason,
            "mode": "results",
            "boot": [{"step": "Select data mode", "status": "error", "elapsed": 0.0,
                      "output": f"[error] {mode_reason}"}],
        }
    from competitions.ucl.src.orchestrator import run_compute_all as _f
    result = _f(str(DATA_DIR), bsd_api_key=_bsd_key(), team_aliases=_BSD_TEAM_ALIASES)
    result["mode"] = "simulation"
    result["boot"] = result.get("boot", [])
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
    holder.publish_data("ucl", data, mode, stamp)
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
    # Reads are pure (plan 02-06): no acquisition fires here. Ingestion
    # happens only through the explicit POST /api/refresh endpoint, the
    # FOOTBALL_PRELOAD_ALL preload, or a test driving adapter.refresh().
    n_unplayed, n_total = _match_counts()
    lifecycle = _lifecycle_view()
    snap = _snap()
    availability = snap.get("availability") or None
    live_map, reasons = _live_availability()
    if not availability:
        availability = live_map
    payload = {
        "refresh": _refresh_report_for(_active_season_token()),
        "teams": snap.get("teams", []),
        "all_teams": snap.get("all_teams", []),
        "n_teams": snap.get("n_teams", 0),
        "n_iterations": snap.get("n_iterations", 0),
        "snapshot_date": snap.get("snapshot_date", ""),
        "champion": snap.get("champion"),
        "mode": snap.get("mode"),
        "availability": availability,
        "phase": snap.get("phase", {}),
        "lifecycle": lifecycle,
        "season": lifecycle.get("season"),
        "n_total_fixtures": n_total,
        "simulation": _simulation_state_block(),
        "n_unplayed": n_unplayed,
        "n_played": n_total - n_unplayed,
    }
    if reasons:
        payload["availability_reason"] = reasons
    return JSONResponse(payload)


@ucl_app.get("/api/seasons")
def api_seasons():
    from competitions.ucl.src.seasons import (
        LOCAL_HISTORICAL_SEASON, get_current_season, list_seasons,
        season_dir, set_current_season, read_season_fixtures, read_season_results,
    )
    current = get_current_season(DATA_DIR)
    active = (current.get("season") if current else LOCAL_HISTORICAL_SEASON)
    candidates = {LOCAL_HISTORICAL_SEASON}
    for season_token in list_seasons(DATA_DIR):
        candidates.add(season_token.replace("_", "/") if season_token.count("_") == 1 else season_token)
    seasons = []
    for season in sorted(candidates, reverse=True):
        if season == LOCAL_HISTORICAL_SEASON:
            fx, fx_avail, _ = load_json_store(DATA_DIR / "fixtures.json")
            rs, rs_avail, _ = load_json_store(DATA_DIR / "results.json")
        else:
            fx = read_season_fixtures(DATA_DIR, season)
            rs = read_season_results(DATA_DIR, season)
        fixtures_count = len(fx.get("fixtures", [])) if isinstance(fx, dict) else 0
        if season == LOCAL_HISTORICAL_SEASON and isinstance(fx, dict):
            fixtures_count = len(
                [m for md in fx.get("schedule", {}).get("matchdays", []) if isinstance(md, list) for m in md]
            )
        results_count = len(rs.get("matches", [])) if isinstance(rs, dict) else 0
        seasons.append({
            "season": season,
            "active": season == active,
            "historical": season == LOCAL_HISTORICAL_SEASON,
            "fixtures": fixtures_count,
            "results": results_count,
        })
    return JSONResponse({"active_season": active, "seasons": seasons})


@ucl_app.post("/api/season")
def api_set_season(req: dict = None):
    from competitions.ucl.src.seasons import LOCAL_HISTORICAL_SEASON, get_current_season, list_seasons, season_dir, set_current_season
    season = str((req or {}).get("season") or "").strip()
    if not season:
        return JSONResponse({"error": "season required"}, status_code=400)
    previous = get_current_season(DATA_DIR)
    valid = season == LOCAL_HISTORICAL_SEASON or season_dir(DATA_DIR, season).is_dir()
    if not valid:
        return JSONResponse({"error": "unknown season"}, status_code=404)
    basis = "pointer_local" if season == LOCAL_HISTORICAL_SEASON else "draw"
    provider = None if season == LOCAL_HISTORICAL_SEASON else f"ucl.draw.{season.replace('/', '_')}"
    pointer = set_current_season(DATA_DIR, season, basis=basis, provider=provider)
    try:
        holder.clear_sim("ucl")
        # STAMP-BEFORE-BUILD: the season pointer just flipped, so the stamp is sampled
        # AFTER the switch but BEFORE the build — the published pair is never
        # (older data, newer stamp).
        stamp = _observed_stamp()
        data, mode = _build_state()
        holder.publish_data("ucl", data, mode, stamp)
    except Exception:
        # Transactional rollback: the pointer was flipped above, but a
        # downstream step (compute_all) failed — restore current.json to
        # the previously-active season before the error surfaces.
        try:
            if previous is None:
                (DATA_DIR / "current.json").unlink(missing_ok=True)
            else:
                set_current_season(
                    DATA_DIR,
                    previous.get("season"),
                    basis=previous.get("basis"),
                    provider=previous.get("provider"),
                )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).error(
                "[UCL] failed to restore seasons pointer after POST /api/season error",
                exc_info=True)
        raise
    return JSONResponse({"status": "ok", "current": pointer,
                         "mode": holder.read_mode("ucl")})


@ucl_app.get("/api/boot")
def api_boot():
    season = _active_season_token()
    return JSONResponse({
        "boot": _snap().get("boot", []),
        "refresh": _freshness(_refresh_report, _freshness_store_paths(season)),
    })


@ucl_app.get("/api/simulation")
def api_simulation():
    sim = holder.read_sim("ucl")
    payload = {
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
    sim_payload = holder.read_sim("ucl").get("sim_state_payload")
    if not sim_payload:
        return None
    from competitions.ucl.src.state import build_competition_state
    from competitions.ucl.src.seasons import get_current_season
    try:
        current = get_current_season(DATA_DIR)
        active_season = current.get("season") if current and isinstance(current, dict) else None
        # The holder publishes the sim payload FROZEN (dict -> MappingProxyType,
        # list -> tuple). The brain is written against plain dicts/lists and
        # type-checks them, so the frozen value is thawed back here — at the
        # web/brain boundary, where the freeze belongs.
        return build_competition_state(str(DATA_DIR), mode="simulation",
                                       sim_payload=holder.thaw(sim_payload),
                                       active_season=active_season)
    except Exception as exc:
        # Never swallow this silently: a missing bracket used to look like
        # "nothing has happened" when the frozen shape was rejected.
        logger.warning("[UCL] simulated bracket unavailable: %s", exc)
        return None


@ucl_app.get("/api/standings")
def api_standings():
    return JSONResponse({
        "standings": _snap().get("standings", []),
        "mode": _snap().get("mode"),
        "season": _active_season_token(),
    })


@ucl_app.get("/api/bracket")
def api_bracket():
    payload = dict(_competition_state())
    # Compatibility alias for older consumers of the league matchday rows.
    payload["league_matchdays"] = (
        payload.get("stages", {}).get("league", {}).get("matchdays")
        or _snap().get("league_matchdays", {}))
    # Same lifecycle view as /api/data (cheap reuse, one discover call each).
    payload["lifecycle"] = _lifecycle_view()
    return JSONResponse(payload)


@ucl_app.get("/api/odds")
def api_odds():
    mode = _snap().get("mode")
    return JSONResponse({
        "odds": _snap().get("odds", []),
        "mode": mode,
        "season": _active_season_token(),
        # Results mode serves deterministic achieved-outcome indicators
        # (1.0/0.0), NOT model probabilities. Simulation runs surface their
        # projections through /api/simulation with SIMULATED provenance.
        "odds_semantics": (
            "achieved_outcome_indicators" if mode == "results"
            else "monte_carlo_probabilities"),
    })


@ucl_app.get("/api/signals")
def api_signals():
    return JSONResponse({
        "signals": _snap().get("signals", {}),
        "mode": _snap().get("mode"),
        "season": _active_season_token(),
    })


@ucl_app.get("/api/elo")
def api_elo():
    """Elo ratings for the Elo view — network-free, source-labelled.

    Preference order, first tier that produces numbers wins:
      a) the boot cache, when it holds real ClubElo values;
      b) the coefficient-derived boot ratings (the degraded tier, still shown
         so the view is not blank, always labelled "coefficient");
      c) nothing -> an explicit empty state.

    ``source`` names the tier the numbers actually came from, and ``as_of``
    is when they were read (empty unless they are real ClubElo values, since
    a coefficient estimate has no date).

    A GET never fetches: the cache was populated at boot from the stored
    ClubElo snapshot, and this handler only reads it.
    """
    snap = _snap()
    ratings = {
        team: float(value)
        for team, value in (snap.get("elo_ratings") or {}).items()
        if isinstance(value, (int, float))
    }
    refined_elo = (snap.get("signals") or {}).get("refined_elo") or {}
    provenance = refined_elo.get("provenance")
    coefficient_derived = provenance == "coefficient_derived"
    if coefficient_derived:
        # Boot could not reach ClubElo, so these are placeholders. Keep them
        # only as the last resort — a real on-disk source outranks them.
        ratings, source, as_of = {}, "coefficient", ""
    elif ratings:
        # Boot labels the ratings' own provenance; report that, not a guess.
        source, as_of = provenance or "clubelo", refined_elo.get("as_of") or ""
    else:
        source, as_of = "empty", ""

    if not ratings and coefficient_derived:
        ratings = {
            team: float(value)
            for team, value in (snap.get("elo_ratings") or {}).items()
            if isinstance(value, (int, float))
        }

    if not ratings:
        return JSONResponse({"ratings": {}, "source": "empty", "as_of": ""})
    return JSONResponse({
        "ratings": ratings,
        "source": source,
        "as_of": as_of,
    })


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


@ucl_app.get("/api/blend")
def api_blend():
    """Blend/calibration view.

    Real weights come from the on-disk calibration artifact produced by
    POST /api/calibrate. Without that artifact there is nothing to report,
    so the answer is an honest cold start — never invented weights.
    """
    try:
        config = (json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))
                  if _CALIBRATION_PATH.exists() else {})
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
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("[UCL] blend info unavailable: %s", exc)
        return JSONResponse(_cold_start_blend(0))


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
    snap = _snap()
    availability = snap.get("availability", {})
    ko_state = availability.get("knockout_results")
    if ko_state in ("missing", "empty", "unavailable"):
        return True
    return not snap.get("champion")


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
    sim_status = holder.read_sim("ucl").get("status", "not_requested")
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

    Deliberately does NOT flip the display mode: canonical cache data stays
    factual ("results"); simulation provenance lives in simulation_meta.
    """
    holder.publish_boot("ucl", ())
    cached_elo = _snap().get("elo_ratings") or None

    def _normalized_progress(value: int, total: int, stage: str = "") -> None:
        # Pre-MC stages report (percent, 100); the MC loop reports
        # (iteration, total_iterations). Map both onto the run count.
        if total == 100:
            progress_cb(int(value / 100 * count), count, stage)
        else:
            progress_cb(value, total, stage)

    result = _run_mc_simulation_pipeline(
        str(DATA_DIR), n_iterations=count, seed=seed,
        weights=None, show_ci="auto", bsd_api_key=_bsd_key(),
        team_aliases=_BSD_TEAM_ALIASES, progress_cb=_normalized_progress,
        elo_ratings_override=cached_elo,
    )
    return result


def _store_ucl_sim_result(result: dict, count: int, seed) -> dict:
    """Cache/snapshot side effects. Returns the public task summary."""
    payload = dict(result)
    payload["boot"] = list(holder.read_boot("ucl"))
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
    bracket = _simulation_bracket_state()
    if bracket is not None:
        snapshot_data["bracket"] = bracket
    snapshot_path = DATA_DIR / "snapshot.json"
    atomic_write_text(
        snapshot_path,
        json.dumps(snapshot_data, indent=2, default=str, ensure_ascii=False),
    )
    holder.publish_sim("ucl", payload)   # ONE atomic assignment; never mutate after
    return {"champion": result.get("champion"),
            "count": result.get("n_iterations")}


@ucl_app.post("/api/reset")
def api_reset():
    try:
        # STAMP-BEFORE-BUILD: sample the stamp BEFORE the build (see _recompute_cache).
        stamp = _observed_stamp()
        data, mode = _build_state()
        holder.publish_data("ucl", data, mode, stamp)
        return JSONResponse({"status": "ok", "mode": holder.read_mode("ucl")})
    except Exception as e:
        return error_response(e, context="ucl reset")


@ucl_app.post("/api/refresh")
def api_refresh():
    """Explicit acquisition trigger for the UCL (plan 02-06).

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
        report = dict(REGISTRY.get("ucl").refresh())
        stamp_after = _observed_stamp()
        if stamp_after != stamp_before:
            # D-06: the simulation is retired AT the store write, BEFORE the
            # rebuild publishes the new facts. Clearing it after the rebuild
            # left a window in which GET /api/simulation still served the
            # previous run while GET /api/data served the new facts.
            holder.clear_sim("ucl")
        data, mode = _build_state()
        holder.publish_data("ucl", data, mode, stamp_after)
    except Exception as e:
        return error_response(
            e, status=503, context="ucl refresh",
            public="Live refresh unavailable")
    return JSONResponse(refresh_response_body(report, mode=holder.read_mode("ucl")))


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

        elo_ratings = _snap().get("elo_ratings", {})
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
                "brier": round(metrics["brier"], 6) if metrics["brier"] is not None else None,
                "log_loss": round(metrics["log_loss"], 6) if metrics["log_loss"] is not None else None,
                "accuracy": round(metrics["accuracy"], 6) if metrics["accuracy"] is not None else None,
                "n": metrics["n"],
            },
        }

        return JSONResponse({
            "validation": validation,
            "calibration_available": False,
        })
    except Exception as e:
        return error_response(e, context="ucl validation")


@ucl_app.get("/api/report")
def api_report():
    snapshot_path = DATA_DIR / "snapshot.json"
    if not snapshot_path.exists():
        return JSONResponse({"error": "no snapshot available — run a simulation first"})
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return error_response(e, context="ucl report")


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

    results = snap.get("_results", [])
    form_trends: dict = {}
    h2h: dict = {"a_wins": 0, "b_wins": 0, "draws": 0, "total": 0}
    if results:
        form_trends = {ta: _ucl_form_trend(ta, results), tb: _ucl_form_trend(tb, results)}
        h2h = _ucl_head_to_head(ta, tb, results)

    eval_data = snap.get("signals", {})
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
    elo_ratings = _snap().get("elo_ratings") or {}
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
