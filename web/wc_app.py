"""World Cup 2026 — FastAPI sub-app mounted under /worldcup.

Tournament logic lives in ``competitions.worldcup.src``; this module only
wires transport, the freshness ledger and the simulation task service.

State lives in the race-free holder (``web.derived.holder``): one frozen
snapshot per competition, rebound in ONE assignment, with the store stamp
folded in — reads go through ``_snap()``, writes through
``holder.publish_data`` / ``publish_sim``. No mutable module
globals.
"""

import json, os
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timezone

import fastapi

from dotenv import load_dotenv

from football_core.freshness import UNREADABLE, read_ledger, served_stale, store_mtime
from football_core.state import atomic_write_text
from football_core.domain import DataAvailability, load_json_store
from football_core.store_stamp import StoreStamp, stamp_store, sub_stamp
from web.derived.stamps import WC_RESULTS_ROLES, WC_ROLES
from web import reconciliation
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
from web.common import (
    RobustJSONResponse as JSONResponse,
    boot_step,
    error_response,
    load_json,
    not_attempted_report,
    refresh_response_body,
)
from web.derived import holder
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

DATA_DIR = constants.DATA_DIR

#: WC factual stores the truth layer classifies (mirrors the store set
#: ``compute_competition_phase`` tracks: played_groups.json + played.json).
_WC_FACTUAL_STORE_PATHS = {
    "played_groups": "played_groups.json",
    "played": "played.json",
}


def _availability_block(data_dir: Path | None = None) -> tuple[dict, dict]:
    """``(availability_map, reason_map)`` from ``load_json_store`` — live,
    not cached. The reason map carries MISSING/UNAVAILABLE entries only;
    EMPTY needs no reason (the file exists and parses)."""
    ddir = Path(data_dir) if data_dir is not None else DATA_DIR
    availability: dict = {}
    reasons: dict = {}
    for key, fname in _WC_FACTUAL_STORE_PATHS.items():
        _payload, state, detail = load_json_store(ddir / fname)
        availability[key] = state.value
        if state in (DataAvailability.MISSING, DataAvailability.UNAVAILABLE):
            reasons[key] = detail or f"store file missing: {ddir / fname}"
    return availability, reasons


def _factual_counts() -> tuple[int | None, int | None]:
    """``(n_played, n_unplayed)`` derived live from the two played stores.

    ``(None, None)`` when either store is MISSING/UNAVAILABLE — absence is
    never laundered into a zero. EMPTY stores are honest, readable state and
    yield real integers. Formulas match the previously-served semantics:
    ``n_played`` counts winner-carrying entries; ``n_unplayed`` counts
    group+bracket ids absent from both played stores.
    """
    pg_payload, pg_state, _ = load_json_store(DATA_DIR / "played_groups.json")
    p_payload, p_state, _ = load_json_store(DATA_DIR / "played.json")
    unreadable = (DataAvailability.MISSING, DataAvailability.UNAVAILABLE)
    if pg_state in unreadable or p_state in unreadable:
        return None, None
    played = p_payload if isinstance(p_payload, dict) else {}
    played_groups = pg_payload if isinstance(pg_payload, dict) else {}
    n_played = sum(
        1 for m in played.values()
        if isinstance(m, dict) and m.get("winner"))
    n_played += sum(
        1 for m in played_groups.values()
        if isinstance(m, dict) and m.get("winner"))
    teams_raw = load_json(DATA_DIR, "teams.json")
    groups_raw = load_groups(DATA_DIR, teams=teams_raw)
    bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
    played_ids = set(played.keys()) | set(played_groups.keys())
    all_ids: set = set()
    groups_data = groups_raw.get("groups", groups_raw) if isinstance(groups_raw, dict) else groups_raw
    for g in groups_data.values():
        for m in g.get("matches", []):
            if m.get("match_id"):
                all_ids.add(m["match_id"])
    for m in bracket_raw:
        if m.get("match_id"):
            all_ids.add(m["match_id"])
    return n_played, len(all_ids - played_ids)


service = SimulationTaskService()


def _observed_stamp() -> StoreStamp:
    """The WC store stamp — the ONE value a request compares for freshness.

    World Cup stores are NOT season-routed: the six canonical files live
    flat in ``competitions/worldcup/data``, so the plain module ``DATA_DIR``
    is the right directory to stamp. ``snapshot.json`` is deliberately not
    part of ``WC_ROLES`` — a simulation run must never age the data stamp.
    """
    return stamp_store(DATA_DIR, WC_ROLES)


def _store_ids(payload: Any) -> frozenset[str]:
    """The ids a World Cup results store holds — the store's OWN keys.

    The World Cup stores are dicts keyed by the bracket slot id, so the
    keys ARE the ids. Never re-derive a fixture id to compare (C-11).
    """
    if not isinstance(payload, dict):
        return frozenset()
    return frozenset(str(key) for key in payload.keys())


def _store_rows(payload: Any) -> Mapping[str, Any]:
    """id -> the stored row, for the ledger's ``real_result`` block."""
    if not isinstance(payload, dict):
        return {}
    return {str(key): row for key, row in payload.items() if isinstance(row, dict)}


def _wc_sim_ids(payload: Mapping[str, Any]) -> frozenset[str]:
    """The badgeable per-answer ids — exactly the ``full_bracket`` entries.

    ``sim_result`` and ``top_teams`` are per-TEAM aggregates over the whole
    run and SURVIVE a retirement: a real result does not falsify "Spain has
    a 12% chance of winning the World Cup" (D-17, RESEARCH §C.3).
    """
    bracket = payload.get("full_bracket") or {}
    rounds = bracket.get("rounds") or {}
    ids: set[str] = set()
    for entries in rounds.values():
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("match_id"):
                ids.add(str(entry["match_id"]))
    return frozenset(ids)


def _wc_sim_answers(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """id -> the simulated answer, VERBATIM (the ledger's superseded_answer).

    D-07: the record carries the ANSWER, not just tombstone metadata —
    otherwise "which simulated answers were wrong, and when did we learn it"
    cannot be answered after a restart.
    """
    bracket = payload.get("full_bracket") or {}
    rounds = bracket.get("rounds") or {}
    answers: dict[str, Any] = {}
    for entries in rounds.values():
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("match_id"):
                answers[str(entry["match_id"])] = dict(entry)
    return answers


def _wc_has_stale_descendants(retired_ids: frozenset[str],
                              payload: Mapping[str, Any]) -> bool:
    """True when a retired answer has a DESCENDANT that is still simulated.

    The parent→child DAG is ``bracket.json``'s ``source_matches`` (validated
    by ``football_core/state.py:validate_bracket``). A corrected upstream
    result leaves a downstream answer stale even though the ids do not
    intersect — the propagation case (D-11's extension, D-17).
    """
    if not retired_ids:
        return False
    remaining = _wc_sim_ids(payload) - set(retired_ids)
    if not remaining:
        return False
    doc, availability, _detail = load_json_store(DATA_DIR / "bracket.json")
    if availability is not DataAvailability.AVAILABLE or not isinstance(doc, list):
        return False
    children: dict[str, list[str]] = {}
    for entry in doc:
        if not isinstance(entry, dict):
            continue
        child = entry.get("match_id")
        if not child:
            continue
        for parent in entry.get("source_matches") or []:
            children.setdefault(str(parent), []).append(str(child))
    for retired in retired_ids:
        for child in children.get(str(retired), ()):
            if child in remaining:
                return True
    return False


def _wc_known_fact_ids() -> frozenset[str]:
    """The real-result ids known RIGHT NOW — the facts a run is computed against."""
    ids: set[str] = set()
    for name in ("played.json", "played_groups.json"):
        payload, availability, _detail = load_json_store(DATA_DIR / name)
        if availability is DataAvailability.AVAILABLE and isinstance(payload, dict):
            ids.update(str(key) for key in payload.keys())
    return frozenset(ids)


def _reconciliation_spec() -> reconciliation.ReconciliationSpec:
    """The World Cup's reconciliation description — the owner's input.

    The World Cup retires PER MATCH: its knockout ids (``M73``-``M96``,
    ``QF_1``-``QF_4``, ``SF_1``, ``SF_2``, ``TPP``, ``FINAL``) are set-equal
    to the simulated bracket's ids. Its group-stage ids (``GS_A_01`` …) do
    NOT intersect the bracket at all — that is the accepted limitation
    D-10 records, and it is why the ``mode`` verdict must be able to say
    ``"partial"``.
    """
    return reconciliation.ReconciliationSpec(
        competition="worldcup",
        ledger_path=reconciliation.retirement_ledger_path(DATA_DIR),
        result_stores=(
            reconciliation.ResultStore(
                role="played",
                path=DATA_DIR / "played.json",
                ids=_store_ids,
                rows=_store_rows,
            ),
            reconciliation.ResultStore(
                role="played_groups",
                path=DATA_DIR / "played_groups.json",
                ids=_store_ids,
                rows=_store_rows,
            ),
        ),
        observed_stamp=_observed_stamp,
        granularity="match",
        sim_ids=_wc_sim_ids,
        sim_answers=_wc_sim_answers,
        stale_descendants=_wc_has_stale_descendants,
    )


def _build_state() -> tuple[dict, str]:
    """Build the WC derived snapshot: the overview plus the constant mode.

    Never raises: a compute failure degrades to a truthful error block (the
    pre-holder boot path degraded the same way) so a request never fails
    with a 500 on unreadable stores.
    """
    try:
        data = dict(compute_overview() or {})
    except Exception:
        logger.exception("worldcup overview compute failed")
        data = {"error": "overview compute failed"}
    return data, "results"   # WC has no sim toggle; mode is constant truth


def _snap():
    """The frozen WC snapshot for this request (rebuilt only when stale).

    D-01: the reconciler is invoked HERE, on every read, because this is the
    only seam every read already goes through. Its per-request cost is ONE
    tuple comparison (the results sub-stamp vs the simulation's recorded
    sub-stamp); the store read happens ONLY on a mismatch. A CLI backfill or
    a ``git checkout`` of the partly-gitignored data dir leaves no report,
    so this is the path that gives them tombstones too.
    """
    snap = holder.get_or_rebuild("worldcup", _observed_stamp(), _build_state)
    reconciliation.reconcile_if_needed(_reconciliation_spec())
    return snap


def _publish_snapshot(report: dict | None = None) -> None:
    """Publish the overview (plus an optional refresh report) as ONE snapshot.

    The report and the derived data travel together, so a reader can never
    see a fresh refresh verdict next to data from an older generation.

    STAMP-BEFORE-BUILD: the stamp is sampled BEFORE the build. A store write that lands
    during the build then publishes the OLDER stamp, and the next request
    sees a mismatch and rebuilds. Sampling after the build would publish
    (older data, newer stamp) — stale data served as current, permanently.
    """
    stamp = _observed_stamp()
    data, mode = _build_state()
    if report is not None:
        data["refresh"] = report
    holder.publish_data("worldcup", data, mode, stamp)


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


def unplayed_match_count() -> int | None:
    """Count matches that have neither played nor played_groups results.

    Returns ``None`` when either played store is MISSING/UNAVAILABLE — a
    deleted/unreadable store is absence, not a zero.
    """
    return _factual_counts()[1]


def compute_signal_stats():
    """Signal statistics from on-disk caches — no ledger dependency."""
    from competitions.worldcup.src.evaluation import compute_signal_stats as _eval
    return _eval(constants.DATA_DIR)


def compute_signal_detail(name: str):
    from competitions.worldcup.src.evaluation import compute_signal_detail as _eval
    return _eval(name, constants.DATA_DIR, _snap().get("evaluation", {}))


def compute_blend_info():
    """Blend info from in-memory cache evaluation + backtest — no cached file."""
    from competitions.worldcup.src.evaluation import compute_blend_info as _eval
    return _eval(constants.DATA_DIR, _snap().get("evaluation", {}), {})


def _fetch_live_data() -> dict:
    """Fetch live match data + signal caches - delegates to pipeline.

    Returns the refresh report (provider/success/error/staleness/ingestion
    counters). The report is published INTO the holder snapshot (together
    with the overview rebuilt from the stores the run just wrote), so the
    API surface serves one generation-consistent view.
    """
    from competitions.worldcup.src.pipeline import fetch_live_data as _pipeline_fetch
    # The stamp is sampled before the ingest so the post-ingest sample can
    # tell whether the canonical stores actually changed.
    stamp_before = _observed_stamp()
    try:
        report = _pipeline_fetch(
            _bsd_key(), _football_data_org_key(), DATA_DIR)
    except Exception:  # never let a refresh crash boot; mark stale
        logger.exception("worldcup live fetch failed")
        report = {"provider": None, "attempted": True, "success": False,
                  "error": "live refresh failed", "stale": True,
                  "finished": {}}
    # D-01: the retirement happens BEFORE the new facts publish (Phase 4's
    # D-06 invariant), and the comparison is NARROWED to the RESULTS
    # roles — a teams.json Elo update, a groups.json refresh or a
    # bracket.json correction must NOT trigger a retirement.
    if (sub_stamp(_observed_stamp(), WC_RESULTS_ROLES)
            != sub_stamp(stamp_before, WC_RESULTS_ROLES)):
        try:
            reconciliation.reconcile_now(_reconciliation_spec(), report=report)
        except Exception:
            # D-03: a lost durable write must never look like a successful
            # one — log loudly and let the refresh report the failure.
            logger.exception(
                "worldcup reconciliation FAILED — the retirement was NOT persisted"
            )
            raise
    _publish_snapshot(report)
    return report



wc_app = fastapi.FastAPI()


@wc_app.get("/api/data")
def api_data():
    availability, reasons = _availability_block()
    n_played, n_unplayed = _factual_counts()
    snap = _snap()
    payload = {
        "refresh": _current_refresh_report(),
        "teams": snap.get("teams", []),
        "n_teams": snap.get("n_teams", 0),
        "phase": snap.get("phase", {}),
        "simulation": _simulation_state_block(),
        "availability": availability,
    }
    if reasons:
        payload["availability_reason"] = reasons
    if n_played is not None:
        payload["n_played"] = n_played
    if n_unplayed is not None:
        payload["n_unplayed"] = n_unplayed
    return JSONResponse(payload)


@wc_app.post("/api/refresh")
def api_refresh():
    """Explicit acquisition trigger for the World Cup (plan 02-06).

    Delegates to the competition-scoped adapter — the SAME path the
    ``FOOTBALL_PRELOAD_ALL`` preload uses — so per-competition scoping
    stays the adapter's job (never a cross-app private import). The
    pipeline self-gates on an explicit offline session (FOOTBALL_SNAPSHOT /
    --offline): zero network, truthful ``attempted=False`` +
    ``skipped_reason`` report. The response is the full IngestReport body;
    HTTP stays 200 because a truthful failure is data, not an HTTP error.

    Side effects: the wrapper persists the report to the freshness ledger
    (attempted runs only) and the snapshot is rebuilt from disk so
    subsequent ``GET /api/data`` shows the freshly ingested facts.
    """
    from web.competitions import REGISTRY

    try:
        # STAMP-BEFORE-BUILD: the stamp is sampled BEFORE the build, so the published pair
        # is never (older data, newer stamp). The pre-ingest sample is what
        # tells us whether the ingest actually wrote the canonical stores.
        stamp_before = _observed_stamp()
        report = dict(REGISTRY.get("worldcup").refresh())
        stamp_after = _observed_stamp()
        if (sub_stamp(stamp_after, WC_RESULTS_ROLES)
                != sub_stamp(stamp_before, WC_RESULTS_ROLES)):
            # D-01: this is the SECOND reconciliation on one POST (the
            # registry calls _fetch_live_data first). The set operation is
            # idempotent BY CONSTRUCTION, so the second run retires
            # nothing new and retired_count does not climb.
            try:
                reconciliation.reconcile_now(_reconciliation_spec(), report=report)
            except Exception:
                logger.exception(
                    "worldcup reconciliation FAILED — the retirement was NOT persisted"
                )
                raise
        data, mode = _build_state()
        holder.publish_data("worldcup", data, mode, stamp_after)
    except Exception as e:
        return error_response(
            e, status=503, context="worldcup refresh",
            public="Live refresh unavailable")
    # WC has no results/simulation switch in its data payload: the served
    # overview is always the real-results view, so mode is constant truth.
    return JSONResponse(refresh_response_body(report, mode="results"))


def simulation_eligibility() -> tuple[bool, Optional[str], str]:
    """Shared eligibility truth (adapter + handler both use this)."""
    remaining = unplayed_match_count()
    if remaining is None:
        return False, "store_unavailable", (
            "Played-result stores are unavailable; cannot evaluate "
            "simulation eligibility.")
    if remaining == 0:
        return False, "no_unplayed_matches", (
            "All competition results are already known from real match "
            "data. Simulation is not needed.")
    return True, None, ""


def has_simulation() -> bool:
    return bool(holder.read_sim("worldcup").get("status") == "completed")


def _run_wc_simulation(progress_cb, count: int, seed: Optional[int],
                       weights=None, show_ci: str = "auto") -> dict:
    from competitions.worldcup.src.pipeline import run_simulation_compute
    # D-18: sample the facts and the results-role sub-stamp BEFORE the run
    # reads the stores — the recorded generation is never newer than the
    # data it describes (Phase 4's STAMP-BEFORE-BUILD discipline).
    stamp = sub_stamp(_observed_stamp(), WC_RESULTS_ROLES)
    facts = _wc_known_fact_ids()
    result = run_simulation_compute(
        DATA_DIR, iterations=count, seed=seed, weights=weights,
        bsd_api_key=_bsd_key(), football_data_org_key=_football_data_org_key(),
        progress_cb=progress_cb,
    )
    result["sim_results_stamp"] = stamp
    result["sim_facts"] = tuple(sorted(facts))
    return result


def _store_wc_sim_result(result: dict, count: int, seed: Optional[int],
                         weights=None, show_ci: str = "auto") -> dict:
    """Cache/snapshot side effects. Returns the public task summary.

    The payload is assembled FIRST and published with ONE assignment: a
    concurrent ``GET /api/simulation`` reader can never observe a payload
    that is missing ``n_unplayed`` (or any other key).
    """
    remaining = unplayed_match_count()
    sim_meta = result.get("simulation_meta", {})
    extra = {
        "weights": weights,
        "show_ci": show_ci,
        "n_top_teams": len(result["top_teams"]),
        "n_signals_evaluated": len(result["eval_metrics"]),
    }
    if remaining is not None:
        extra["unplayed_matches"] = remaining
    payload = {
        "top_teams": result["top_teams"][:20],
        "signal_eval": result["eval_metrics"],
        "simulation_meta": build_simulation_meta(
            requested_count=count,
            actual_count=sim_meta.get("n_simulations", count),
            seed=sim_meta.get("seed"),
            provenance_extra=sim_meta.get("provenance") or {},
            engine_version=sim_meta.get("engine_version"),
            extra=extra,
        ),
        "full_bracket": result["full_bracket"],
        "sim_result": result.get("sim_result"),
        "sim_facts": tuple(result.get("sim_facts") or ()),
        "sim_results_stamp": result.get("sim_results_stamp"),
        "status": "completed",
    }
    if remaining is not None:
        payload["n_unplayed"] = remaining
    snapshot = result["snapshot"]
    snapshot["show_ci"] = show_ci
    atomic_write_text(
        DATA_DIR / "snapshot.json",
        json.dumps(snapshot, indent=2, default=str, ensure_ascii=False),
    )
    holder.publish_sim("worldcup", payload)  # ONE atomic assignment; never mutate after
    ack = {}
    if remaining is not None:
        ack["n_unplayed"] = remaining
    return ack


def _simulation_state_block() -> dict:
    """Shared product contract: availability + request lifecycle + reconciliation."""
    eligible, reason, _msg = simulation_eligibility()
    sim_status = holder.read_sim("worldcup").get("status", "not_requested")
    request_state = {
        "running": "running",
        "completed": "completed",
        "failed": "failed",
    }.get(sim_status, "not_requested")
    block = {
        "availability": "available" if eligible else "not_needed",
        "reason": reason,
        "request_state": request_state,
    }
    # C-05/D-12: the reconciliation verdict rides the SAME block in every
    # endpoint, so the dashboard can never see one shape here and another
    # there. The keys are ADDED — the existing ones never change.
    block.update(reconciliation.reconciliation_block(_reconciliation_spec()))
    return block


def _refresh_report_path() -> Path:
    """Seam for tests: location of the shared freshness ledger."""
    return Path(__file__).parent / "last_refresh.json"


#: Factual stores the World Cup refresh writes. ``snapshot.json`` is
#: deliberately excluded — it is a simulated artifact (02-04) and must never
#: age the freshness ledger.
_WC_FACTUAL_STORES = ("played.json", "played_groups.json")


def _freshness_store_paths() -> list[Path]:
    """Which World Cup stores D-12 compares against (path knowledge: the app)."""
    return [DATA_DIR / name for name in _WC_FACTUAL_STORES]


def _freshness(entry: dict, store_paths: list[Path]) -> dict:
    """Serve D-12: a "fresh" claim the store has outgrown becomes stale.

    The rule itself is :func:`football_core.freshness.served_stale` (shared
    and unit-tested); this is only the store-path wiring, and the returned
    dict is a *served* copy — the ledger file is never rewritten here.
    The unreadable marker is passed through untouched: it already IS the
    failure signal and must keep its exact shape.
    """
    if not entry or entry.get("stale") or entry.get("ledger") == UNREADABLE:
        return entry
    if served_stale(entry, [store_mtime(p) for p in store_paths]):
        return {**entry, "stale": True}
    return entry


def _current_refresh_report() -> dict:
    """World Cup entry of the shared ledger — loud on failure (D-11).

    Healthy file: the ``worldcup`` sub-dict, unchanged. Unreadable file: the
    explicit ``{"ledger": "unreadable", "detail": ...}`` marker, which is the
    failure signal the dashboard renders — never ``{}``, which would read as
    "no refresh has ever run". No entry at all (a process that never
    refreshed): the truthful ``not_attempted`` block — which additionally
    discloses an explicit offline session — instead of ``{}``.
    """
    ledger = read_ledger(_refresh_report_path())
    if ledger.get("ledger") == UNREADABLE:
        return ledger
    entry = ledger.get("worldcup") or {}
    if not entry:
        return not_attempted_report()
    return _freshness(entry, _freshness_store_paths())


@wc_app.get("/api/overview")
def api_overview():
    has_sim = has_simulation()
    availability, reasons = _availability_block()
    n_played, n_unplayed = _factual_counts()
    snap = _snap()
    payload = {
        "refresh": _current_refresh_report(),
        "standings": snap.get("standings", []),
        "teams": snap.get("teams", []),
        "n_teams": snap.get("n_teams", 0),
        "signals_meta": snap.get("signals_meta", {"signals": [], "n_total": 0}),
        "phase": snap.get("phase", {}),

        "has_simulation": has_sim,
        "simulation": _simulation_state_block(),
        "lifecycle": snap.get("lifecycle", {}),
        "availability": availability,
    }
    if reasons:
        payload["availability_reason"] = reasons
    if n_played is not None:
        payload["n_played"] = n_played
    if n_unplayed is not None:
        payload["n_unplayed"] = n_unplayed
    return JSONResponse(payload)


@wc_app.get("/api/simulation")
def api_simulation():
    # D-01/D-14.7: this endpoint does not go through _snap(), so the
    # reconciler is invoked here explicitly.
    reconciliation.reconcile_if_needed(_reconciliation_spec())
    sim = holder.read_sim("worldcup")
    payload = {
        "top_teams": sim.get("top_teams", []),
        "signal_eval": sim.get("signal_eval", {}),
        "simulation_meta": sim.get("simulation_meta"),
        "status": sim.get("status", "not_requested"),
        "message": sim.get("message"),
        "full_bracket": sim.get("full_bracket"),
    }
    # n_unplayed comes from the completed sim's own record; absent that,
    # derive it live — and omit the key entirely when the stores are
    # unreadable rather than emitting a synthesised 0/None.
    if "n_unplayed" in sim:
        payload["n_unplayed"] = sim["n_unplayed"]
    else:
        live = unplayed_match_count()
        if live is not None:
            payload["n_unplayed"] = live
    return JSONResponse(payload)


@wc_app.get("/api/boot")
def api_boot():
    return JSONResponse(_snap().get("boot", []))


@wc_app.get("/api/standings")
def api_standings():
    snap = _snap()
    return JSONResponse({"standings": snap.get("standings", {}), "third_place": snap.get("third_place", [])})


@wc_app.get("/api/bracket")
def api_bracket():
    return JSONResponse(_snap().get("bracket", {}))


@wc_app.get("/api/bracket/full")
def api_bracket_full():
    return JSONResponse(_snap().get("full_bracket", {}))


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
    return JSONResponse(_snap().get("evaluation", {}))


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
        for row in (_snap().get("teams") or [])
        # ``Mapping`` (not ``dict``): the snapshot is frozen, so a team row
        # arrives as a read-only mapping proxy, not a plain dict.
        if isinstance(row, Mapping) and row.get("name")
        and isinstance(row.get("elo"), (int, float))
    }
    if not ratings:
        return JSONResponse({"ratings": {}, "source": "empty", "as_of": ""})
    return JSONResponse({"ratings": ratings, "source": "teams", "as_of": ""})


@wc_app.get("/api/blend")
def api_blend():
    return JSONResponse(compute_blend_info())






@wc_app.post("/api/simulate")
def api_simulate(req: dict = None):
    if not req:
        return JSONResponse({"error": "request body required"})
    # Validate BEFORE the eligibility short-circuit: an invalid request is
    # invalid regardless of competition state (no silent clamping).
    weights = req.get("weights")
    show_ci = str(req.get("show_ci", "auto"))
    # Never simulate over absence: a MISSING/UNAVAILABLE played store is a
    # truthful refusal, not an empty-store run (02-07 D-07).
    availability, _ = _availability_block()
    bad = [k for k, s in availability.items()
           if s in ("missing", "unavailable")]
    if bad:
        return JSONResponse(
            {"error": f"played store unavailable ({', '.join(bad)}) — cannot simulate"},
            status_code=409,
        )
    ack: dict = {}
    live_count = unplayed_match_count()
    if live_count is not None:
        ack["n_unplayed"] = live_count
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
        extra_ack=ack,
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
    if not match_id:
        return JSONResponse({"error": "match_id required"})
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
    # Never simulate over absence (02-07 D-07): MISSING/UNAVAILABLE → 409.
    availability, _ = _availability_block()
    bad = [k for k, s in availability.items()
           if s in ("missing", "unavailable")]
    if bad:
        return JSONResponse(
            {"error": f"played store unavailable ({', '.join(bad)}) — cannot simulate"},
            status_code=409,
        )

    try:
        result = _simulate_from_match_sync(match_id, iterations)
        return JSONResponse(result)
    except Exception as e:
        return error_response(e, context="worldcup simulate-from-match")


@wc_app.get("/api/match/insight")
def api_match_insight(match_id: str = ""):
    if not match_id:
        return JSONResponse({"error": "match_id parameter required"})
    snap = _snap()
    fb = snap.get("full_bracket", {})
    ev = snap.get("evaluation", {})
    bl = snap.get("blend_data")
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

    fb = _snap().get("full_bracket", {})
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
    # Never run a what-if over absence (02-07 D-07): refuse before any
    # bracket lookup so the truthful refusal is never masked by a
    # "match not found".
    availability, _ = _availability_block()
    bad = [k for k, s in availability.items()
           if s in ("missing", "unavailable")]
    if bad:
        return JSONResponse(
            {"error": f"played store unavailable ({', '.join(bad)}) — cannot simulate"},
            status_code=409,
        )

    fb = _snap().get("full_bracket", {})
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
    p_payload, _, _ = load_json_store(DATA_DIR / "played.json")
    pg_payload, _, _ = load_json_store(DATA_DIR / "played_groups.json")
    played_raw = p_payload if isinstance(p_payload, dict) else {}
    played_groups = (
        pg_payload if isinstance(pg_payload, dict) else {})

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
