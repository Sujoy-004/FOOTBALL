"""Compute pipeline — extracted from web.wc_app for reuse and testability.

Phase 1 of the architectural refactoring extracts 7 functions from
``web/wc_app.py`` into this pipeline module. Each function is self-contained
(receives all dependencies as parameters, no module-level globals).

Phase 2 will extract ``compute_signal_eval``, ``compute_full_bracket``, etc.
Phase 3 moved ``_build_engine_from_caches`` (renamed to ``build_engine_from_caches``)
into ``src.engine`` and ``compute_team_strengths_from_predictions`` into ``src.evaluation``.
``web.engine_helpers`` was deleted.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from src import constants
from src.knockout import run_full_simulation, resolve_knockout_slot_teams
from src.state import (
    load_annex_c,
    load_groups,
)
from football_core.freshness import read_ledger, update_ledger
from football_core.state import atomic_write_text
# The brain owns its own evaluation module: this module no longer imports
# from ``web`` (plan 01-06, D-13).
from competitions.worldcup.src.evaluation import compute_signal_eval
from football_core.fetcher import new_ingestion_stats  # type: ignore[import-untyped]
from football_core.signal import PredictionContext  # type: ignore[import-untyped]

# Pathological pass cap: the retry-set breaks (no unresolved events, or a
# pass that changed nothing) are the real stop; 8 comfortably exceeds the
# 5-round bracket depth.
MAX_KNOCKOUT_PASSES = 8  # pathological cap; the retry breaks are the real stop

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────


# Surviving ensemble signal keys (canonical roster).
SURVIVING_SIGNALS = ("elo", "market_odds", "rolling_form", "squad_value", "rest_days")


def _last_refresh_report_path() -> Path:
    """Shared freshness ledger at <repo>/web/last_refresh.json.

    Derived from this module's location (not cwd) so tests can redirect it
    by monkeypatching this function instead of changing directories.
    """
    return Path(__file__).resolve().parents[3] / "web" / "last_refresh.json"


def bracket_stage_order() -> list[str]:
    """Canonical knockout stage order for WC bracket payloads."""
    return ["R32", "R16", "QF", "SF", "TPP", "FINAL"]


def bracket_stage_labels() -> dict[str, str]:
    """Display labels keyed by knockout stage code."""
    return {
        "R32": "Round of 32",
        "R16": "Round of 16",
        "QF": "Quarter-finals",
        "SF": "Semi-finals",
        "TPP": "Third-place play-off",
        "FINAL": "Final",
    }


def _wc_stats() -> dict:
    """Zeroed WC finished-result counters for ONE processing scope.

    The shared ingestion vocabulary (``football_core.fetcher.new_ingestion_stats``)
    plus the D-14 re-offer bucket ``skipped_no_change``, so every branch of
    the WC processors can land a received event in exactly one bucket.
    """
    stats = new_ingestion_stats()
    stats["skipped_no_change"] = 0
    return stats


def _read_prev_ledger() -> dict:
    """Parse the shared freshness ledger, never raising.

    Delegates to :func:`football_core.freshness.read_ledger` so a corrupt
    ledger logs a traceback and comes back as the explicit ``unreadable``
    marker (D-11) instead of a silent ``{}`` that reads as "never refreshed".
    Callers pull ``["worldcup"]``, which is simply absent from the marker.
    """
    return read_ledger(_last_refresh_report_path())


def _results_stage_row(state: str, count: int, detail: str) -> dict:
    """OQ7 stage row for the worldcup result-ingestion step (plan 02-06).

    Row vocabulary is fixed by the ``IngestReport`` contract
    (``football_core/fetcher.py``): ``{key, label, state, count, detail}``
    with ``state ∈ ok | pending | error | unavailable``. The signal-cache
    rows are appended by a later plan — this one reports ONLY the results
    step, never an invented value for work that has not happened.
    """
    return {"key": "results", "label": "Match results", "state": state,
            "count": int(count), "detail": detail}


def _build_report(
    provider,
    *,
    attempted: bool,
    success: bool,
    error,
    stale: bool,
    reason,
    last_success_at,
    finished: dict,
    skipped_reason=None,
    stages=None,
    written_files=None,
) -> dict:
    """Single refresh-report shape for EVERY fetch_live_data exit path (02-03).

    Elevates the invariant: an attempt must surface with the same key set
    whether it succeeded or failed. ``deferred`` is only ever true for the
    deliberate no-op verdicts (``"deferred"`` / ``"deferred/provider-empty"``)
    — a genuine failure is NOT a deferral, and ``skipped_reason`` is only
    present when the refresh never reached the provider at all.

    Attempted reports are persisted to the shared freshness ledger
    (best-effort, never raising) so stale data can't masquerade as fresh;
    deferred/snapshot exits don't write.
    """
    report = {
        "provider": provider,
        "attempted": attempted,
        "success": success,
        "error": error,
        "stale": stale,
        "reason": reason,
        "last_success_at": last_success_at,
        "finished": finished,
        "stages": [dict(stage) for stage in (stages or [])],
        "written_files": list(written_files) if written_files is not None else [],
        "deferred": reason in ("deferred", "deferred/provider-empty"),
    }
    if skipped_reason is not None:
        report["skipped_reason"] = skipped_reason
    if attempted:
        # Single-writer ledger (D-18): football_core.freshness owns the lock,
        # the atomic write and the loud failure. A report path never crashes
        # the request, but the failure IS logged — never swallowed with pass.
        try:
            update_ledger(_last_refresh_report_path(), "worldcup", report)
        except Exception:
            logger.exception(
                "freshness ledger write FAILED — worldcup refresh outcome "
                "was not persisted"
            )
    return report


def _dedupe_events(events: list[dict]) -> list[dict]:
    """D-14: provider receipts are unique per run — first payload item wins.

    Collapses duplicate provider event ids inside ONE payload before any
    counting happens, so no event can be received twice (the processors'
    in-call dedup would otherwise count the duplicate as an extra receipt).
    Events without an id pass through untouched — the processors already
    treat those as never-seen.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for ev in events:
        eid = str(ev.get("id", "") or "")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        unique.append(ev)
    return unique


def _unresolved_ko_indices(
    ko_events: list[dict],
    aliases: dict,
    resolved_bracket: list[dict],
) -> tuple[set[int], set[int]]:
    """Classify finished payload events against ONE resolved bracket pass.

    Returns ``(matched, unresolved)`` index sets: ``matched`` events have a
    resolvable slot target (terminal once seen — never re-processed), while
    ``unresolved`` events have none yet and form the next retry batch.
    Unnormalizable team names belong to neither set: they were counted
    ``skipped_unmatchable`` and can never match on any pass.
    """
    from football_core.fetcher import (
        _build_alias_lookup,
        find_bracket_match,
        normalize_team,
    )

    lookup = _build_alias_lookup(aliases, resolved_bracket)
    matched: set[int] = set()
    unresolved: set[int] = set()
    for idx, ev in enumerate(ko_events):
        if ev.get("status") != "finished":
            continue
        home = normalize_team(str(ev.get("home_team", "")), lookup)
        away = normalize_team(str(ev.get("away_team", "")), lookup)
        if home is None or away is None:
            continue
        if find_bracket_match(home, away, resolved_bracket) is None:
            unresolved.add(idx)
        else:
            matched.add(idx)
    return matched, unresolved


def build_blend_params(engine_predictions: list, all_matches: list[dict], engine) -> dict:
    """Build the simulation blend payload from canonical EnsembleEngine output.

    This is the single blending path: EnsembleEngine blended probabilities
    become per-match win probabilities for the Monte Carlo simulation.

    Exchange 5 correctness fix: entries without a REAL team pairing are
    excluded. Knockout bracket slots carry no teams on disk, so blending
    them produced one constant, matchup-blind probability for every KO tie
    (systematically favouring team_b and inverting strength-based rankings).
    Unresolved slots now fall through to the matchup-aware Elo fallback in
    ``football_core.knockout._get_blended_prob``.
    """
    match_probs: dict[str, float] = {}
    for bp, m in zip(engine_predictions, all_matches):
        mid = m.get("match_id", "")
        if not (mid and m.get("team_a") and m.get("team_b")):
            continue
        match_probs[mid] = bp.home_prob
    return {
        "match_probs": match_probs,
        "blend_weights": dict(engine.weights),
    }


# ── Function 1: fetch_live_data ──────────────────────────────────────────


def fetch_live_data(
    bsd_api_key: str,
    football_data_org_key: str,
    data_dir: Path,
) -> dict:
    """Fetch live match data + signal caches from the configured provider.

    Returns a refresh report {provider, attempted, success, error, stale,
    finished: <nested per-stage counters>, reason, last_success_at,
    stages, written_files, deferred} which is also merged into
    <repo>/web/last_refresh.json under "worldcup" so a failed or
    stale refresh is never mistaken for fresh data.
    """
    from football_core.fetcher import derive_success

    def _fail(reason: str, provider_name=None) -> dict:
        prev = _read_prev_ledger().get("worldcup", {})
        report = _build_report(
            provider_name,
            attempted=True,
            success=False,
            error=reason,
            stale=True,
            reason=None,
            last_success_at=prev.get("last_success_at"),
            finished={"group_stage": _wc_stats(), "knockout": _wc_stats()},
            stages=[_results_stage_row("error", 0, reason)],
        )
        logger.warning("fetch_live_data FAILED: %s — WC data may be STALE", reason)
        return report

    from football_core.runtime_support import is_snapshot_mode
    if is_snapshot_mode():
        report = _wc_stats()
        # D-13: nothing was attempted, so nothing succeeded — the deferred
        # verdict is DERIVED from the (zeroed) counters, never declared.
        success, reason = derive_success(None, False, report)
        # D-02/02-09: the four signal caches were not attempted either; they
        # publish truthful ``unavailable`` rows and write nothing (zero network).
        from src.signal_caches import produce_signal_caches

        return _build_report(
            None,
            attempted=False,
            success=success,
            error=None,
            stale=True,
            reason=reason,
            last_success_at=None,
            finished=report,
            skipped_reason="snapshot mode selected at startup",
            stages=produce_signal_caches(
                data_dir, now=datetime.now(timezone.utc), mode="snapshot"
            ),
        )
    from football_core.runtime_support import get_data_provider
    provider = get_data_provider(bsd_api_key, football_data_org_key, constants.DEFAULT_LEAGUE_ID)
    if provider is None:
        return _fail("no data provider configured")

    try:
        teams = json.loads((data_dir / "teams.json").read_text(encoding="utf-8"))
        groups = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
        bracket_raw = json.loads(
            (data_dir / "bracket.json").read_text(encoding="utf-8")
        )
        aliases = json.loads(
            (data_dir / "team_aliases.json").read_text(encoding="utf-8")
        )
    except Exception as e:
        logger.warning("fetch_live_data: failed to load data files: %s", e)
        return _build_report(
            None,
            attempted=False,
            success=False,
            error=f"failed to load data files: {e}",
            stale=True,
            reason=None,
            last_success_at=None,
            finished=_wc_stats(),
            skipped_reason="local competition data files unreadable",
        )

    # 1. Fetch and process match results via provider
    group_stats = _wc_stats()
    ko_stats = _wc_stats()
    try:
        from src.fetcher import (
            partition_events_by_stage, process_group_matches, process_matches,
        )

        # OQ9: pin the season so a provider's current-season default can never
        # silently serve the prior season (the canonical WC 2026 corpus must be
        # 2026). The provider builds ``params["season"]`` from this kwarg.
        raw_matches = provider.fetch_matches(competition_id="WC", season=2026)
        if not raw_matches:
            reason = "provider returned no matches"
            err = getattr(provider, "last_error", None)
            if err:
                reason += f" ({err})"
            return _fail(reason, type(provider).__name__)

        # Stage-aware routing: partition provider events by stage before
        # dispatching to the appropriate processor.  Events with a non-empty
        # group_name are group-stage; the rest are knockout.  This prevents
        # cross-stage routing that produced noisy "no matching fixture/slot"
        # warnings and wasted work in each processor.
        #
        # D-14: receipts are unique per run — collapse duplicate payload
        # items (same provider id) before counting, so one event can never
        # be received twice across retry passes.
        raw_matches = _dedupe_events(raw_matches)
        group_events, ko_events = partition_events_by_stage(raw_matches)

        played_groups_path = data_dir / "played_groups.json"
        played_groups = (
            json.loads(played_groups_path.read_text(encoding="utf-8"))
            if played_groups_path.exists()
            else {}
        )
        grp_before = json.dumps(played_groups, sort_keys=True, ensure_ascii=False)
        new_grp = process_group_matches(
            group_events, teams, groups, aliases, played_groups, set(),
            ingestion_stats=group_stats,
        )
        for m in new_grp:
            played_groups[m["match_id"]] = m
        if json.dumps(played_groups, sort_keys=True, ensure_ascii=False) != grp_before:
            atomic_write_text(
                played_groups_path,
                json.dumps(played_groups, indent=2, ensure_ascii=False),
            )

        annex_c = load_annex_c(data_dir)
        played_path = data_dir / "played.json"
        played = (
            json.loads(played_path.read_text(encoding="utf-8"))
            if played_path.exists()
            else {}
        )

        # Multi-pass with per-event retry accounting (02-03): downstream
        # bracket slots (SF, TPP, FINAL) only resolve once earlier rounds
        # land in the store, so each pass re-resolves the bracket and
        # re-processes ONLY the finished events that still have no slot
        # target.  Receipts are still counted exactly once per event:
        #
        #   * pass 0 processes (and counts) every payload event;
        #   * later passes count into a fresh scratch dict whose buckets
        #     REPLACE the previous counted pass's ``skipped_no_target``
        #     receipts for exactly the retried events (the fold below);
        #   * ``matched_once`` events are terminal — once an event has
        #     found a slot target it is never re-counted, even if a
        #     correction later reshuffles the bracket.
        #
        # The fold is exact because every retried event was counted
        # ``skipped_no_target`` in the immediately preceding counted pass
        # (payload dedup guarantees one receipt per event), and unmatched
        # events that stay unmatched simply re-land in the same bucket.
        matched_once: set[int] = set()   # found a slot target at least once
        unresolved: set[int] = set()     # counted no_target in last counted pass
        for pass_no in range(MAX_KNOCKOUT_PASSES):
            known_winners = {
                mid: d["winner"] for mid, d in played.items() if d.get("winner")
            }
            slot_teams = resolve_knockout_slot_teams(
                groups,
                teams,
                played_groups,
                bracket_raw,
                annex_c,
                known_winners,
            )
            resolved_bracket = [
                {"match_id": mid, "team_a": st["team_a"], "team_b": st["team_b"]}
                for mid, st in slot_teams.items()
                if st.get("team_a") and st.get("team_b")
            ]
            if pass_no == 0:
                batch, pass_stats = ko_events, ko_stats
            else:
                retry = sorted(unresolved - matched_once)
                if not retry:
                    break  # nothing left to retry: every event resolved or died
                batch = [ko_events[i] for i in retry]
                pass_stats = _wc_stats()
            ko_before = json.dumps(played, sort_keys=True, ensure_ascii=False)
            new_ko = process_matches(
                batch, teams, resolved_bracket, aliases, played,
                ingestion_stats=pass_stats,
            )
            for m in new_ko:
                played[m["match_id"]] = m
            ko_changed = (
                json.dumps(played, sort_keys=True, ensure_ascii=False) != ko_before
            )
            if ko_changed:
                atomic_write_text(
                    played_path,
                    json.dumps(played, indent=2, ensure_ascii=False),
                )
            if pass_no > 0:
                # Fold this pass's scratch receipts into the run totals: the
                # batch events were counted skipped_no_target last pass, so
                # refund exactly len(batch) of those receipts before adding
                # this pass's outcomes for the same events.
                ko_stats["skipped_no_target"] -= len(batch)
                for key in (
                    "ingested", "skipped_unmatchable",
                    "skipped_missing_score", "skipped_no_change",
                    "skipped_no_target",
                ):
                    ko_stats[key] += pass_stats[key]
            # Reclassify every payload event against THIS pass's bracket so
            # the next batch only contains still-unresolved slots.
            matched_now, unresolved_now = _unresolved_ko_indices(
                ko_events, aliases, resolved_bracket
            )
            matched_once |= matched_now
            unresolved = unresolved_now - matched_once
            # Stop only when nothing new AND nothing corrected: a score
            # correction may change downstream knockout winners, so the
            # bracket must be re-resolved once more when updates occurred.
            # A pass with no store change re-resolves to the identical
            # bracket, so retrying can never produce anything new.
            if not new_ko and not ko_changed:
                break
    except Exception as e:
        # Acquisition-truth fix: a RAISING provider must surface as a failed
        # refresh, never fall through to a success-shaped report with
        # silently skipped matches. Stores already written stay untouched;
        # everything after this point is skipped.
        reason = f"match fetch failed: {e.__class__.__name__}: {e}"
        logger.warning("fetch_live_data: %s", reason)
        return _fail(reason, type(provider).__name__)

    # Success report — persisted so stale data can't masquerade as fresh.
    # D-13: success is DERIVED from the finished-result counters. The two
    # per-stage stat objects are summed into one flat counter dict for the
    # derivation (the helper stays flat-only); the report keeps its nested
    # per-stage display form.
    flat_counters = {
        key: group_stats.get(key, 0) + ko_stats.get(key, 0)
        for key in ("received", "normalized", "ingested",
                    "skipped_unmatchable", "skipped_no_target",
                    "skipped_missing_score", "skipped_no_change")
    }
    success, reason = derive_success(type(provider).__name__, True, flat_counters)
    # D-02/02-09: one acquisition pass also refreshes the four signal caches.
    # The results row stays first; the four cache rows follow, each truthful
    # about what it did (wrote / skipped-as-fresh / unavailable / error).
    from src.signal_caches import produce_signal_caches

    written_files: list[str] = []
    cache_rows = produce_signal_caches(
        data_dir,
        now=datetime.now(timezone.utc),
        mode="live",
        written_files=written_files,
    )
    report = _build_report(
        type(provider).__name__,
        attempted=True,
        success=success,
        error=None,
        stale=not success,
        reason=reason,
        last_success_at=(
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if success
            else _read_prev_ledger().get("worldcup", {}).get("last_success_at")
        ),
        finished={"group_stage": group_stats, "knockout": ko_stats},
        stages=[
            _results_stage_row(
                "ok" if success else "error",
                flat_counters["ingested"] if success else 0,
                type(provider).__name__ if success else (reason or "refresh failed"),
            ),
            *cache_rows,
        ],
        written_files=written_files,
    )
    if not success:
        logger.warning(
            "fetch_live_data derived success=False (%s) — counters: %r",
            reason, flat_counters,
        )
    return report


# ── Function 2: build_chronological_matches ──────────────────────────────


def build_chronological_matches(data_dir: Path) -> dict:
    """Build chronological match listing grouped by round.

    Returns: {rounds: [{round_name, round_type, matches}]}
    """
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups = load_groups(data_dir, teams=teams_raw)
    groups_data = (
        groups.get("groups", groups) if isinstance(groups, dict) else groups
    )
    groups_data = groups_data if isinstance(groups_data, dict) else {}
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    played_groups_raw = (
        json.loads(
            (data_dir / "played_groups.json").read_text(encoding="utf-8")
        )
        if (data_dir / "played_groups.json").exists()
        else {}
    )
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )

    rounds: list[dict] = []

    for gk in sorted(groups_data.keys()):
        g = groups_data[gk]
        matches = []
        for m in g.get("matches", []):
            mid = m["match_id"]
            r = played_groups_raw.get(mid, {})
            matches.append(
                {
                    "match_id": mid,
                    "date": r.get("completed_at"),
                    "team_a": m["team_a"],
                    "team_b": m["team_b"],
                    "home_score": r.get("home_score"),
                    "away_score": r.get("away_score"),
                    "winner": r.get("winner"),
                    "played": mid in played_groups_raw,
                    "status": "played" if mid in played_groups_raw else "tbd",
                    "matchday": m.get("matchday"),
                }
            )
        if matches:
            rounds.append(
                {
                    "round_name": "Group " + gk,
                    "round_type": "group",
                    "matches": matches,
                }
            )

    KO_ROUND_TYPES = {
        "R32": "r32",
        "R16": "r16",
        "QF": "qf",
        "SF": "sf",
        "TPP": "tpp",
        "FINAL": "final",
    }
    ko_rounds_order = bracket_stage_order()
    for round_name in ko_rounds_order:
        matches = []
        for be in bracket_raw:
            if be.get("round") != round_name:
                continue
            mid = be["match_id"]
            r = played_raw.get(mid, {})
            matches.append(
                {
                    "match_id": mid,
                    "date": r.get("completed_at"),
                    "team_a": r.get("team_a"),
                    "team_b": r.get("team_b"),
                    "home_score": r.get("home_score"),
                    "away_score": r.get("away_score"),
                    "winner": r.get("winner"),
                    "played": mid in played_raw,
                    "status": "played" if mid in played_raw else "tbd",
                    "source_matches": be.get("source_matches"),
                }
            )
        if matches:
            rounds.append(
                {
                    "round_name": round_name,
                    "round_type": KO_ROUND_TYPES.get(round_name, "ko"),
                    "matches": matches,
                }
            )

    return {"rounds": rounds}


# ── Function 3: build_knockout_tree ──────────────────────────────────────


def build_knockout_tree(data_dir: Path) -> dict:
    """Build knockout tree structure with resolved teams for all rounds.

    Returns: {round_name: [{match_id, team_a, team_b, score, winner, played, source_matches}]}
    """
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups = load_groups(data_dir, teams=teams_raw)
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    annex_c = load_annex_c(data_dir)
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )
    played_groups_raw = (
        json.loads(
            (data_dir / "played_groups.json").read_text(encoding="utf-8")
        )
        if (data_dir / "played_groups.json").exists()
        else {}
    )

    # Function-local: bracket.py resolves bracket_stage_order from this module
    # at call time, so a module-scope import here would close an import cycle.
    from competitions.worldcup.src.bracket import compute_full_bracket

    fb = compute_full_bracket(
        groups, teams_raw, bracket_raw, annex_c, played_raw, played_groups_raw
    )
    return fb.get("rounds", {})


# ── Function 4: collect_downstream_matches ───────────────────────────────


def collect_downstream_matches(
    target_id: str,
    bracket_raw: list[dict],
) -> list[str]:
    """Collect all downstream matches reachable from target_id via source_matches."""
    children_of: dict[str, list[str]] = {}
    for be in bracket_raw:
        for sm in be.get("source_matches") or []:
            children_of.setdefault(sm, []).append(be["match_id"])

    downstream: list[str] = []
    queue = [target_id]
    visited: set[str] = set()
    while queue:
        mid = queue.pop(0)
        for child in children_of.get(mid, []):
            if child not in visited:
                visited.add(child)
                downstream.append(child)
                queue.append(child)
    return downstream


# ── Function 5: simulate_from_match ──────────────────────────────────────


def simulate_from_match(
    match_id: str,
    data_dir: Path,
    iterations: int = 10000,
) -> dict:
    """Run a full simulation and extract probabilities for target + downstream matches."""
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups_raw = load_groups(data_dir, teams=teams_raw)
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    annex_c = load_annex_c(data_dir)
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )
    played_groups_raw = (
        json.loads(
            (data_dir / "played_groups.json").read_text(encoding="utf-8")
        )
        if (data_dir / "played_groups.json").exists()
        else {}
    )

    # Lazy import — build_engine_from_caches lives in src.engine (consolidated from web.engine_helpers).
    from src.engine import build_engine_from_caches  # noqa: PLC0415

    engine = build_engine_from_caches()
    elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
    groups_data = (
        groups_raw.get("groups", groups_raw)
        if isinstance(groups_raw, dict)
        else groups_raw
    )
    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket_raw:
        all_matches.append(m)

    engine_predictions = []
    context = PredictionContext(
        fixtures=all_matches,
        elo_ratings=elo_ratings,
        played_results=list(played_raw.values())
        + list(played_groups_raw.values()),
    )
    for m in all_matches:
        bp = engine.evaluate(m, context)
        engine_predictions.append(bp)
    blend_params = build_blend_params(engine_predictions, all_matches, engine)

    def _noop_progress(current: int, total: int) -> None:
        pass

    sim_result = run_full_simulation(
        teams_raw,
        groups_raw,
        bracket_raw,
        annex_c,
        played_raw,
        iterations=iterations,
        played_groups=played_groups_raw,
        blend_params=blend_params,
        progress_cb=_noop_progress,
    )

    bracket_entry = None
    for be in bracket_raw:
        if be["match_id"] == match_id:
            bracket_entry = be
            break

    downstream_ids = collect_downstream_matches(match_id, bracket_raw)
    simulated: list[dict] = []
    for mid in downstream_ids:
        probs: dict[str, list[dict]] = {}
        for team_name, pdata in sim_result.items():
            for stage in ("champion", "final", "sf", "qf"):
                prob = pdata.get(stage, 0)
                if prob > 0.001:
                    probs.setdefault(stage, []).append(
                        {"name": team_name, "probability": prob}
                    )
        sorted_probs = {
            k: sorted(v, key=lambda x: x["probability"], reverse=True)[:3]
            for k, v in probs.items()
        }
        simulated.append(
            {
                "match_id": mid,
                "top_teams": sorted(
                    [
                        {"name": name, **pdata}
                        for name, pdata in sim_result.items()
                    ],
                    key=lambda t: t.get("champion", 0),
                    reverse=True,
                )[:5],
            }
        )

    target_probs: dict[str, dict[str, float]] = {}
    target_round = bracket_entry.get("round", "?") if bracket_entry else "?"
    for team_name, pdata in sim_result.items():
        target_probs[team_name] = {
            stage: pdata.get(stage, 0)
            for stage in ("champion", "final", "sf", "qf")
        }
    top_target = sorted(
        target_probs.items(),
        key=lambda x: x[1].get("champion", 0),
        reverse=True,
    )[:4]

    return {
        "match_id": match_id,
        "round": target_round,
        "predictions": [
            {"name": name, **probs}
            for name, probs in top_target
            if probs.get("champion", 0) > 0
        ],
        "downstream": simulated,
    }


# ── Function 6: run_simulation_compute ───────────────────────────────────


def run_simulation_compute(
    data_dir: Path,
    iterations: int = 50000,
    seed: int | None = None,
    weights: dict[str, float] | None = None,
    bsd_api_key: str = "",
    football_data_org_key: str = "",
    progress_cb: callable | None = None,  # noqa: UP035
) -> dict:
    """Core simulation computation — returns results dict (no side effects on cache).

    The caller (web layer) is responsible for:
    * Managing ``active_simulations`` state
    * Updating the global ``cache`` with ``overview`` + meta
    * Writing the ``snapshot`` to disk
    """
    if progress_cb is None:
        progress_cb = lambda done, total, stage="": None  # noqa: E731

    # Exchange 3 truth invariant: a simulation request never mutates
    # canonical stores. Live refresh is an explicit /api/refresh concern;
    # the simulation conditions on whatever results are on disk right now.

    progress_cb(0, 100, "Loading data files...")
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups_raw = load_groups(data_dir, teams=teams_raw)
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    annex_c = load_annex_c(data_dir)
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )
    played_groups_raw = (data_dir / "played_groups.json").read_text(
        encoding="utf-8"
    )
    played_groups = (
        json.loads(played_groups_raw) if played_groups_raw.strip() else {}
    )

    progress_cb(5, 100, "Building prediction engine...")
    from src.engine import build_engine_from_caches  # noqa: PLC0415

    engine = build_engine_from_caches(weights=weights)

    progress_cb(10, 100, "Computing engine predictions...")
    elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
    groups_data = (
        groups_raw.get("groups", groups_raw)
        if isinstance(groups_raw, dict)
        else groups_raw
    )
    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket_raw:
        all_matches.append(m)

    # Canonical ensemble — blended match probabilities feed the simulation.
    # No silent fallback: an ensemble failure fails the simulation request.
    context = PredictionContext(
        fixtures=all_matches,
        elo_ratings=elo_ratings,
        played_results=list(played_raw.values())
        + list(played_groups.values()),
    )
    engine_predictions = [engine.evaluate(m, context) for m in all_matches]
    blend_params = build_blend_params(engine_predictions, all_matches, engine)

    progress_cb(15, 100, "Running Monte Carlo simulation...")

    def _sim_progress(current: int, total: int) -> None:
        progress_cb(current, total, f"Simulating match {current} of {total}")

    sim_result = run_full_simulation(
        teams_raw,
        groups_raw,
        bracket_raw,
        annex_c,
        played_raw,
        iterations=iterations,
        seed=seed,  # None lets the engine generate + return a reproducible seed
        played_groups=played_groups,
        blend_params=blend_params,
        progress_cb=_sim_progress,
    )
    sim_meta = sim_result.pop("_meta", {})

    progress_cb(92, 100, "Computing top team rankings...")
    top_teams = sorted(
        [
            {"name": name, **probs}
            for name, probs in sim_result.items()
        ],
        key=lambda t: t.get("champion", 0),
        reverse=True,
    )

    progress_cb(95, 100, "Evaluating prediction accuracy...")
    eval_metrics = compute_signal_eval(
        teams_raw,
        played_raw,
        played_groups,
        engine_predictions,
        all_matches,
    )

    progress_cb(97, 100, "Building full bracket tree...")
    from competitions.worldcup.src.bracket import compute_full_bracket
    from competitions.worldcup.src.overview import compute_overview

    full_bracket = compute_full_bracket(
        groups_raw,
        teams_raw,
        bracket_raw,
        annex_c,
        played_raw,
        played_groups,
        engine_predictions,
    )

    # Enrich unplayed bracket matches with predicted scores from simulation
    from football_core.knockout import simulate_single_match
    _score_rng = random.Random(42)
    for _round_name, _matches in full_bracket.get("rounds", {}).items():
        for _m in _matches:
            if not _m.get("played") and _m.get("team_a") and _m.get("team_b"):
                _ta, _tb = _m["team_a"], _m["team_b"]
                if _ta in elo_ratings and _tb in elo_ratings:
                    _result = simulate_single_match(_ta, _tb, elo_ratings, _score_rng)
                    _m["predicted_score"] = {"home": _result["score_a"], "away": _result["score_b"]}

    overview = compute_overview()

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "simulation",
        "iterations": sim_meta.get("n_simulations", iterations),
        # Resolved seed: when the caller passed None the engine generated
        # one and it is recorded here so the run can be reproduced.
        "seed": sim_meta.get("seed"),
        "requested_seed": seed,
        "provenance": {
            "real_results_preserved": True,
            "simulated_matches_only": True,
            **(sim_meta.get("provenance") or {}),
        },
        "weights": weights,
        "n_teams": overview.get("n_teams", 0),
        "n_played": overview.get("n_played", 0),
        "top_teams": top_teams[:20],
        "standings": overview.get("standings", []),
        "bracket": overview.get("bracket", {}),
        "signal_eval": eval_metrics,
        "signals_meta": overview.get(
            "signals_meta", {"signals": [], "n_total": 0}
        ),
        "governance": overview.get("governance", {}),
    }

    progress_cb(100, 100, "Complete")

    return {
        "overview": overview,
        "top_teams": top_teams,
        "eval_metrics": eval_metrics,
        "full_bracket": full_bracket,
        "sim_result": sim_result,
        "simulation_meta": sim_meta,
        "snapshot": snapshot,
    }


# ── Function 7: run_calibration_compute ──────────────────────────────────


def run_calibration_compute(
    data_dir: Path,
    bsd_api_key: str = "",
    football_data_org_key: str = "",
    progress_cb: callable | None = None,  # noqa: UP035
) -> dict:
    """Fit ensemble weights by inverse log-loss on recorded prediction history.

    The single canonical weight-fitting method (football_core.compute_log_loss_weights).
    Writes competitions/worldcup/config/signal_weights.json with provenance metadata
    when enough labeled history exists; reports ``insufficient_data`` otherwise —
    never invents weights.
    """
    if progress_cb is None:
        progress_cb = lambda done, total, stage="": None  # noqa: E731

    import math
    from datetime import datetime, timezone

    from football_core.blender import compute_log_loss_weights

    progress_cb(10, "Loading prediction history...")
    from src.state import load_prediction_history

    history = load_prediction_history(data_dir)

    progress_cb(40, "Collecting per-signal outcomes...")
    per_signal: dict[str, list[tuple[float, float]]] = {}
    for entry in history or []:
        actual = entry.get("actual")
        signals = entry.get("signals", {})
        if actual is None or not isinstance(signals, dict):
            continue
        for sig, sv in signals.items():
            if sig not in SURVIVING_SIGNALS or not isinstance(sv, dict):
                continue
            if not sv.get("available", True):
                continue
            p = sv.get("probability")
            if p is None:
                continue
            per_signal.setdefault(sig, []).append((float(p), float(actual)))

    progress_cb(70, "Fitting weights...")
    threshold = constants.COLD_START_THRESHOLD
    eps = 1e-15
    fitted_ll: dict[str, float] = {}
    n_map: dict[str, int] = {}
    for sig in SURVIVING_SIGNALS:
        pairs = per_signal.get(sig, [])
        n_map[sig] = len(pairs)
        if len(pairs) < threshold:
            continue
        ll = 0.0
        for p, a in pairs:
            p_c = min(max(p, eps), 1 - eps)
            # Soft-label binary cross-entropy vs actual ∈ {0.0 (loss), 0.5 (draw), 1.0 (win)}
            ll += -(a * math.log(p_c) + (1 - a) * math.log(1 - p_c))
        fitted_ll[sig] = ll / len(pairs)

    if not fitted_ll:
        progress_cb(100, "Insufficient data")
        return {
            "status": "insufficient_data",
            "threshold": threshold,
            "n_matches_per_signal": n_map,
            "message": (
                f"Fewer than {threshold} labeled predictions per signal — "
                "keeping current weights (uniform fallback until real data accrues)."
            ),
        }

    weights = compute_log_loss_weights(fitted_ll)

    payload = {
        "weights": weights,
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "method": "inverse_log_loss",
        "source": "prediction_history",
        "threshold": threshold,
        "per_signal": {
            s: {"log_loss": round(fitted_ll[s], 6), "n_matches": n_map[s]}
            for s in sorted(fitted_ll)
        },
    }
    out_path = Path(__file__).resolve().parent.parent / "config" / "signal_weights.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    progress_cb(100, "Complete")
    return {
        "status": "ok",
        "weights": weights,
        "weights_file": str(out_path),
        "per_signal": payload["per_signal"],
    }


# ── Competition phase (Exchange 2 truth contract) ────────────────────────

_PHASE_LABELS = {
    "not_started": "Not Started",
    "group_stage": "Group Stage",
    "group_stage_complete": "Groups Complete",
    "knockout": "Knockout",
    "completed": "Completed",
}

WC_GROUP_MATCH_TOTAL = 72
WC_KNOCKOUT_MATCH_TOTAL = 32

# Required decided winners per bracket node (R32..FINAL incl. third place).
_WC_REQUIRED_KO_NODES = {
    "R32": 16,
    "R16": 8,
    "QF": 4,
    "SF": 2,
    "TPP": 1,
    "FINAL": 1,
}
_WC_NODE_UNDECIDED_DIAGNOSTICS = {
    "R32": "wc.r32_undecided",
    "R16": "wc.r16_undecided",
    "QF": "wc.qf_undecided",
    "SF": "wc.sf_undecided",
    "TPP": "wc.tpp_undecided",
    "FINAL": "wc.final_undecided",
}


def _wc_bracket_node_rounds(data_dir: Path) -> dict[str, list[str]]:
    """match_id -> bracket-round map from bracket.json (never raises).

    The only authoritative source for classifying knockout node ids into
    R32/R16/... buckets; an empty dict means the structure is unknown.
    """
    try:
        bracket_raw = json.loads(
            (data_dir / "bracket.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    mapping: dict[str, list[str]] = {}
    if isinstance(bracket_raw, list):
        for be in bracket_raw:
            if (
                isinstance(be, dict)
                and be.get("match_id")
                and be.get("round") in _WC_REQUIRED_KO_NODES
            ):
                mapping.setdefault(str(be["round"]), []).append(
                    str(be["match_id"])
                )
    return mapping


def _wc_completion_diagnostics(
    n_group_matches: int,
    ko_available: bool,
    played_ko: dict,
    node_rounds: dict[str, list[str]],
) -> tuple[list[str], bool]:
    """Brain-owned completion criteria + contradiction detection.

    Returns ``(diagnostics, inconsistent)`` with stable ``wc.*`` strings.
    ``inconsistent`` marks self-contradicting evidence — the FINAL winner
    (the only possible champion) on file while any other criterion fails.
    """
    diagnostics: list[str] = []
    if n_group_matches < WC_GROUP_MATCH_TOTAL:
        diagnostics.append("wc.groups_incomplete")

    if not ko_available:
        diagnostics.append("wc.knockout_store_unavailable")
    elif not node_rounds:
        diagnostics.append("wc.ko_structure_unavailable")
    else:
        overfull = False
        for round_name in ("R32", "R16", "QF", "SF", "TPP", "FINAL"):
            node_ids = node_rounds.get(round_name) or []
            required = _WC_REQUIRED_KO_NODES[round_name]
            if len(node_ids) > required:
                overfull = True
            decided = sum(
                1 for mid in node_ids
                if isinstance(played_ko.get(mid), dict)
                and played_ko[mid].get("winner")
            )
            if decided < required:
                diagnostics.append(_WC_NODE_UNDECIDED_DIAGNOSTICS[round_name])
        if overfull:
            diagnostics.append("wc.ko_counts_exceed_bracket")

    champion = None
    final_entry = played_ko.get("FINAL")
    if isinstance(final_entry, dict):
        champion = final_entry.get("winner") or None
    if champion is None:
        diagnostics.append("wc.champion_missing")

    structural_failure = any(d != "wc.champion_missing" for d in diagnostics)
    inconsistent = champion is not None and structural_failure
    return diagnostics, inconsistent


def compute_competition_phase(data_dir: Path | None = None) -> dict:
    """Authoritative competition-phase report for the World Cup brain.

    Derived from on-disk evidence only; frontends render this instead of
    inferring stage from array lengths. ``stores`` uses DataAvailability
    values so 'phase not reached' and 'data unavailable' stay distinct.

    ``completed`` requires ALL of: every group match played AND every
    bracket node R32..FINAL (+ TPP) carrying a winner AND a champion equal
    to the FINAL winner (the champion is derived from that node). Otherwise
    the phase stays below ``completed``; ``diagnostics`` lists each violated
    criterion as a stable ``wc.*`` string and ``inconsistent`` flags
    self-contradicting evidence (champion present while anything else
    fails).
    """
    from football_core.domain import DataAvailability, load_json_store
    from src.constants import DATA_DIR

    data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
    _, pg_availability, _ = load_json_store(data_dir / "played_groups.json")
    played_groups: dict = {}
    if pg_availability is DataAvailability.AVAILABLE:
        payload, _, _ = load_json_store(data_dir / "played_groups.json")
        if isinstance(payload, dict):
            played_groups = payload
    n_group_matches = sum(
        1 for m in played_groups.values()
        if isinstance(m, dict)
        and m.get("home_score") is not None and m.get("away_score") is not None
    )

    _, ko_availability, _ = load_json_store(data_dir / "played.json")
    played_ko: dict = {}
    if ko_availability is DataAvailability.AVAILABLE:
        payload, _, _ = load_json_store(data_dir / "played.json")
        if isinstance(payload, dict):
            played_ko = payload
    node_rounds = _wc_bracket_node_rounds(data_dir)
    diagnostics, inconsistent = _wc_completion_diagnostics(
        n_group_matches,
        ko_availability is DataAvailability.AVAILABLE,
        played_ko,
        node_rounds,
    )
    champion = None
    final_entry = played_ko.get("FINAL")
    if isinstance(final_entry, dict):
        champion = final_entry.get("winner") or None

    if not diagnostics:
        phase = "completed"
    elif len(played_ko) > 0:
        phase = "knockout"
    elif n_group_matches >= WC_GROUP_MATCH_TOTAL:
        phase = "group_stage_complete"
    elif n_group_matches > 0:
        phase = "group_stage"
    else:
        phase = "not_started"

    total = WC_GROUP_MATCH_TOTAL + WC_KNOCKOUT_MATCH_TOTAL
    return {
        "phase": phase,
        "label": _PHASE_LABELS[phase],
        "champion": champion,
        "progress": {"played": n_group_matches + len(played_ko), "total": total},
        "stores": {
            "group_results": pg_availability.value,
            "knockout_results": ko_availability.value,
        },
        "diagnostics": diagnostics,
        "inconsistent": inconsistent,
    }


# ── Season lifecycle (Exchange 3 truth contract) ─────────────────────────

_LIFECYCLE_STAGE_MAP = {
    "completed": "completed",
    "knockout": "active",
    "group_stage_complete": "active",
    "group_stage": "active",
    "not_started": "future",
}


def _wc_season_id() -> str:
    """Derive the tracked World Cup season id from constants (no network).

    The year is extracted from the league catalog name for
    ``DEFAULT_LEAGUE_ID`` ("World Cup 2026" -> "2026"); ``WC_START_DATE`` is
    the documented fallback. No hardcoded eternal season.
    """
    name = constants.LEAGUES.get(constants.DEFAULT_LEAGUE_ID, "")
    digits = "".join(ch for ch in name if ch.isdigit())
    if len(digits) == 4:
        return digits
    return str(constants.WC_START_DATE[:4])


def season_lifecycle(data_dir: Path | None = None, phase: dict | None = None) -> dict:
    """Season-lifecycle view for the World Cup — same key contract as the UCL
    ``competitions.ucl.src.lifecycle.discover`` output.

    Stage maps the authoritative ``compute_competition_phase`` report onto
    the lifecycle stages: completed -> completed (all group matches played,
    every bracket node R32..FINAL + TPP decided, champion == FINAL winner);
    inconsistent when the evidence contradicts itself (champion present
    while any structural criterion fails); group_stage / group_stage_complete
    / knockout -> active; not_started -> future.

    ``progress`` reuses the exact counters computed by
    ``compute_competition_phase`` ({played: group + knockout results,
    total: 72 + 32}) when a phase report is available; it falls back to
    deriving them straight from played_groups.json + played.json otherwise.
    ``diagnostics`` carries the brain's violated-criterion strings (``wc.*``)
    for active/inconsistent stages and is ``[]`` for completed, future and
    unknown stages. ``historical`` lists seasons with completed evidence
    (this season only, appended once the tournament is complete). Basis is
    always "derived". Deterministic; no prints; no network.
    """
    from football_core.domain import DataAvailability, load_json_store
    from src.constants import DATA_DIR

    dp = Path(data_dir) if data_dir is not None else DATA_DIR

    if phase is None:
        phase = compute_competition_phase(dp)
    report = phase if isinstance(phase, dict) else {}
    phase_value = report.get("phase")
    raw_diagnostics = report.get("diagnostics")
    diagnostics = (
        [str(d) for d in raw_diagnostics]
        if isinstance(raw_diagnostics, list)
        else []
    )

    season = _wc_season_id()
    if bool(report.get("inconsistent")):
        stage = "inconsistent"
    else:
        stage = _LIFECYCLE_STAGE_MAP.get(phase_value, "unknown")

    if stage not in ("active", "inconsistent"):
        diagnostics = []

    progress = None
    raw_progress = phase.get("progress") if isinstance(phase, dict) else None
    if isinstance(raw_progress, dict) and "played" in raw_progress and "total" in raw_progress:
        progress = {"played": int(raw_progress["played"]), "total": int(raw_progress["total"])}
    if progress is None:
        n_group = 0
        pg_payload, pg_availability, _ = load_json_store(dp / "played_groups.json")
        if pg_availability is DataAvailability.AVAILABLE and isinstance(pg_payload, dict):
            n_group = sum(
                1 for m in pg_payload.values()
                if isinstance(m, dict)
                and m.get("home_score") is not None and m.get("away_score") is not None
            )
        n_ko = 0
        ko_payload, ko_availability, _ = load_json_store(dp / "played.json")
        if ko_availability is DataAvailability.AVAILABLE and isinstance(ko_payload, dict):
            n_ko = len(ko_payload)
        progress = {
            "played": n_group + n_ko,
            "total": WC_GROUP_MATCH_TOTAL + WC_KNOCKOUT_MATCH_TOTAL,
        }

    historical = [season] if stage == "completed" else []

    return {
        "season": season,
        "stage": stage,
        "progress": progress,
        "historical": historical,
        "basis": "derived",
        "provider_current_season": None,
        "season_mismatch": False,
        "label": f"{season} - {stage}",
        "diagnostics": diagnostics,
    }
