"""Season-lifecycle discovery for UCL (Exchange 3 → 4).

Answers one question honestly and fully offline: where in its life cycle is
the LOCALLY tracked season? The view classifies the local season purely from
on-disk evidence (results / fixtures / knockout stores via the authoritative
competition-phase brain) and never fabricates an eternal season, guesses a
stage without evidence, or touches the network.

The web layer may hand in the provider's live season id; when it differs from
the local season the view reports the mismatch instead of hiding it.

Exchange 4 adds season-transition logic: if the provider season is newer AND
the season store has sufficient data for it (fixtures >= 100 OR results >= 50),
switch to that season as the active view. Otherwise keep the local season and
surface the mismatch with a diagnostic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

__all__ = ["discover", "LIFECYCLE_CONTRACT"]

#: Exact key contract of :func:`discover` (shared with the WC equivalent).
LIFECYCLE_CONTRACT = (
    "season",
    "stage",
    "progress",
    "historical",
    "basis",
    "provider_current_season",
    "season_mismatch",
    "label",
    "diagnostics",
)

# Thresholds for "sufficient data" to transition to a provider season.
# Fixtures: 100 out of 144 league matches (~69% coverage).
# Results: 50 scored matches (arbitrary but meaningful progress marker).
SUFFICIENT_FIXTURES_THRESHOLD = 100
SUFFICIENT_RESULTS_THRESHOLD = 50

# compute_competition_phase vocabulary -> lifecycle stages. Evidence-based:
# "completed" only occurs when every completion criterion holds (full league,
# decided playoff/R16/QF/SF/FINAL, champion == FINAL winner); a champion on
# file alone never implies it.
_PHASE_TO_STAGE = {
    "completed": "completed",
    "league_stage": "active",
    "league_stage_complete": "active",
    "knockout_playoffs": "active",
    "knockout": "active",
}


def _read_tracked_config(data_dir: Path) -> Optional[list[dict]]:
    """Read the optional tracked-seasons config (data/seasons.json).

    Expected shape::

        {"seasons": [{"id": "2025/26", "status": "completed"}]}

    Returns the validated entry list, or None when the file is absent,
    unreadable, or carries no usable entries. Never raises.
    """
    path = data_dir / "seasons.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    seasons = payload.get("seasons") if isinstance(payload, dict) else None
    if not isinstance(seasons, list):
        return None
    entries = [
        {"id": s["id"], "status": s.get("status")}
        for s in seasons
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]
    ]
    return entries or None


def _local_season_id() -> str:
    """Derive the local tracked season id from constants (no network).

    Prefers ``src.constants.SEASON`` when defined; falls back to the canonical
    ``src.state.SEASON``. No hardcoded eternal season anywhere.
    """
    try:
        from competitions.ucl.src.constants import SEASON as CONSTANTS_SEASON
    except Exception:
        CONSTANTS_SEASON = None
    if CONSTANTS_SEASON:
        return str(CONSTANTS_SEASON)
    from competitions.ucl.src.state import SEASON

    return str(SEASON)


def _fixtures_usable(data_dir: Path) -> bool:
    """True when fixtures.json exists and is at least parseable JSON."""
    from football_core.domain import DataAvailability, load_json_store

    _, availability, _ = load_json_store(data_dir / "fixtures.json")
    return availability in (DataAvailability.AVAILABLE, DataAvailability.EMPTY)


def _league_progress(data_dir: Path) -> dict:
    """League-phase progress counters from the raw stores.

    ``played`` = results.json rows carrying full scores; ``total`` = matches
    scheduled across fixtures.json matchdays. Knockout completion is
    deliberately NOT counted here (see :func:`discover` docstring).
    """
    from football_core.domain import DataAvailability, load_json_store

    played = 0
    payload, availability, _ = load_json_store(data_dir / "results.json")
    if availability is DataAvailability.AVAILABLE:
        rows = payload.get("matches", payload) if isinstance(payload, dict) else payload
        if isinstance(rows, list):
            played = sum(
                1 for m in rows
                if isinstance(m, dict)
                and m.get("home_score") is not None
                and m.get("away_score") is not None
            )

    total = 0
    fx_payload, fx_availability, _ = load_json_store(data_dir / "fixtures.json")
    if fx_availability is DataAvailability.AVAILABLE and isinstance(fx_payload, dict):
        schedule = fx_payload.get("schedule", fx_payload)
        matchdays = (
            schedule.get("matchdays", []) if isinstance(schedule, dict) else []
        )
        if isinstance(matchdays, list):
            total = sum(
                len(md) for md in matchdays if isinstance(md, list)
            )
    return {"played": played, "total": total}


def discover(
    data_dir: str | Path,
    provider_season: str | None = None,
    phase: dict | None = None,
) -> dict:
    """Return the season-lifecycle view for the local UCL season.

    Stage classification is purely evidence-based, via the authoritative
    ``compute_competition_phase`` report:

    - ``completed``: phase == "completed" (league fully played, playoff
      8/8, R16 8/8, QF 4/4, SF 2/2 and FINAL decided, champion equal to the
      FINAL winner);
    - ``inconsistent``: the evidence contradicts itself — a champion on
      file while any structural criterion fails (league unplayed, FINAL or
      earlier rounds undecided, knockout store unusable), or a champion
      differing from the FINAL winner;
    - ``active``: some league matches played but not all, OR the league is
      complete while the knockout store is missing/empty/unavailable, OR
      knockout play has begun;
    - ``future``: fixtures exist (or the season is declared in the tracked
      seasons config) but zero results have been recorded;
    - ``unknown``: no evidence at all in the stores.

    ``progress`` is LEAGUE-phase progress ONLY (``played`` results rows with
    scores over the ``total`` fixtures-scheduled league matches). Knockout
    completion influences the stage through the phase report but is never
    folded into these counters — no double counting.

    ``diagnostics`` carries the brain's violated-criterion strings
    (``ucl.*``) for active/inconsistent stages; it is ``[]`` for clean
    (completed) seasons and for future/unknown ones where no criterion can
    be violated yet.

    ``provider_season`` (optional, handed in by the web layer from live
    metadata): when provided AND different from the local season id:
    - If the season store has sufficient data for that provider season
      (fixtures >= 100 OR results >= 50) AND no diagnostics indicate
      inconsistency, return it as the active season with ``"basis": "provider"``,
      ``"season_mismatch": true``.
    - If provider season exists but store has insufficient data (fixtures < 100
      AND results < 50), **do not switch** — keep last valid season, set
      ``"season_mismatch": true``, ``"basis": "derived"``, add diagnostic
      ``"provider_season_insufficient_data"``.
    - If provider season store has diagnostics (inconsistent), do not switch,
      keep old, flag mismatch.
    - If no provider_season or no mismatch → existing derived behavior.

    Deterministic; no prints; no network.
    """
    dp = Path(data_dir)
    config_entries = _read_tracked_config(dp)

    # The explicit current.json pointer is the active-view source of truth.
    # The legacy root directory remains the canonical store only when the
    # local historical season (2025/26) is active.
    from competitions.ucl.src.seasons import (
        LOCAL_HISTORICAL_SEASON,
        get_current_season,
        season_dir,
    )
    current = get_current_season(dp)
    pointed_season = (
        str(current.get("season")) if isinstance(current, dict) and current.get("season")
        else None
    )
    active_candidate = pointed_season or LOCAL_HISTORICAL_SEASON
    active_data_dir = (
        season_dir(dp, active_candidate)
        if active_candidate != LOCAL_HISTORICAL_SEASON
        else dp
    )
    if not active_data_dir.is_dir():
        active_data_dir = dp

    phase_was_supplied = phase is not None
    if phase is None:
        # Imported lazily: orchestrator pulls the simulation stack, and a
        # module-level import here would create a circular dependency risk.
        from competitions.ucl.src.orchestrator import compute_competition_phase

        phase = compute_competition_phase(active_data_dir)
    report = phase if isinstance(phase, dict) else {}
    phase_value = report.get("phase")
    raw_diagnostics = report.get("diagnostics")
    diagnostics = (
        [str(d) for d in raw_diagnostics]
        if isinstance(raw_diagnostics, list)
        else []
    )

    season = active_candidate
    basis = (
        str(current.get("basis")) if isinstance(current, dict) and current.get("basis")
        else ("config" if config_entries else "derived")
    )
    declared_ids = {entry["id"] for entry in (config_entries or [])}

    if bool(report.get("inconsistent")):
        stage = "inconsistent"
    elif phase_value in _PHASE_TO_STAGE:
        stage = _PHASE_TO_STAGE[phase_value]
    elif phase_value == "not_started":
        stage = (
            "future"
            if (_fixtures_usable(dp) or season in declared_ids)
            else "unknown"
        )
    else:
        stage = "unknown"

    if stage not in ("active", "inconsistent"):
        diagnostics = []

    historical = sorted(
        {
            entry["id"]
            for entry in (config_entries or [])
            if entry.get("status") == "completed"
        }
    )
    if stage == "completed" and season not in historical:
        historical.append(season)
        historical.sort()

    provider_current: Optional[str] = None
    season_mismatch = False
    transition_diagnostics: list[str] = []

    # Season transition logic (Exchange 4)
    if provider_season is not None and str(provider_season) != season:
        provider_current = str(provider_season)
        season_mismatch = True

        # Check if provider season has sufficient data in its season store.
        from competitions.ucl.src.seasons import resolve_active_view, read_season_fixtures, read_season_results

        provider_view = resolve_active_view(dp)["seasons"]
        provider_season_dir_id = (
            provider_view.get(provider_current.replace("/", "_"))
            or provider_view.get(provider_current)
        )

        if provider_season_dir_id:
            fixtures_count = provider_season_dir_id.get("fixtures_count", 0)
            results_count = provider_season_dir_id.get("results_count", 0)

            sufficient_data = (
                fixtures_count >= SUFFICIENT_FIXTURES_THRESHOLD
                or results_count >= SUFFICIENT_RESULTS_THRESHOLD
            )

            if sufficient_data:
                # Switch to provider season
                season = provider_current
                basis = "provider"
            else:
                # Keep local season, add diagnostic
                transition_diagnostics.append("provider_season_insufficient_data")
                basis = "derived"
        else:
            # Provider season not in store at all
            transition_diagnostics.append("provider_season_not_in_store")
            basis = "derived"
    elif provider_season is not None and str(provider_season) == season:
        # Provider season matches local - no mismatch
        provider_current = None
        season_mismatch = False
    else:
        # No provider season hint
        provider_current = None
        season_mismatch = False

    # Recompute lifecycle evidence from the season that will actually be
    # presented. Provider-season transitions must never retain the previous
    # season's stage/progress merely because discovery began from local data.
    selected_data_dir = (
        season_dir(dp, season) if season != LOCAL_HISTORICAL_SEASON else dp
    )
    if selected_data_dir.is_dir() and not phase_was_supplied:
        from competitions.ucl.src.orchestrator import compute_competition_phase

        selected_phase = compute_competition_phase(selected_data_dir)
        selected_report = selected_phase if isinstance(selected_phase, dict) else {}
        selected_raw_diagnostics = selected_report.get("diagnostics")
        selected_diagnostics = (
            [str(d) for d in selected_raw_diagnostics]
            if isinstance(selected_raw_diagnostics, list) else []
        )
        selected_phase_value = selected_report.get("phase")
        if bool(selected_report.get("inconsistent")):
            stage = "inconsistent"
        elif selected_phase_value in _PHASE_TO_STAGE:
            stage = _PHASE_TO_STAGE[selected_phase_value]
        elif selected_phase_value == "not_started":
            stage = "future" if _fixtures_usable(selected_data_dir) else "unknown"
        else:
            stage = "unknown"
        if stage not in ("active", "inconsistent"):
            selected_diagnostics = []
        diagnostics = selected_diagnostics

    diagnostics.extend(d for d in transition_diagnostics if d not in diagnostics)

    return {
        "season": season,
        "stage": stage,
        "progress": _league_progress(
            season_dir(dp, season) if season != LOCAL_HISTORICAL_SEASON else dp
        ),
        "historical": historical,
        "basis": basis,
        "provider_current_season": provider_current,
        "season_mismatch": season_mismatch,
        "label": f"{season} - {stage}",
        "diagnostics": diagnostics,
    }
