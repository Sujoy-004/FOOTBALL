"""Season-lifecycle discovery for UCL (Exchange 3).

Answers one question honestly and fully offline: where in its life cycle is
the LOCALLY tracked season? The view classifies the local season purely from
on-disk evidence (results / fixtures / knockout stores via the authoritative
competition-phase brain) and never fabricates an eternal season, guesses a
stage without evidence, or touches the network.

The web layer may hand in the provider's live season id; when it differs from
the local season the view reports the mismatch instead of hiding it.
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
)

# compute_competition_phase vocabulary -> lifecycle stages. Evidence-based:
# "league_stage_complete" only occurs when the knockout store carries zero
# usable evidence (missing/empty/unavailable), i.e. the season cannot be
# finished yet — that is "active", never "completed".
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

    - ``completed``: phase == "completed" (all league matches played AND a
      champion is on file in the knockout store);
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

    ``provider_season`` (optional, handed in by the web layer from live
    metadata): when provided AND different from the local season id it is
    reported under ``provider_current_season`` with ``season_mismatch`` true
    and basis "provider". The platform surfaces the mismatch honestly; this
    function never attempts to fetch the provider season's data.

    Deterministic; no prints; no network.
    """
    dp = Path(data_dir)
    config_entries = _read_tracked_config(dp)

    if phase is None:
        # Imported lazily: orchestrator pulls the simulation stack, and a
        # module-level import here would create a circular dependency risk.
        from competitions.ucl.src.orchestrator import compute_competition_phase

        phase = compute_competition_phase(dp)
    phase_value = phase.get("phase") if isinstance(phase, dict) else None

    season = _local_season_id()
    basis = "config" if config_entries else "derived"
    declared_ids = {entry["id"] for entry in (config_entries or [])}

    if phase_value in _PHASE_TO_STAGE:
        stage = _PHASE_TO_STAGE[phase_value]
    elif phase_value == "not_started":
        stage = (
            "future"
            if (_fixtures_usable(dp) or season in declared_ids)
            else "unknown"
        )
    else:
        stage = "unknown"

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
    if provider_season is not None and str(provider_season) != season:
        provider_current = str(provider_season)
        season_mismatch = True
        basis = "provider"

    return {
        "season": season,
        "stage": stage,
        "progress": _league_progress(dp),
        "historical": historical,
        "basis": basis,
        "provider_current_season": provider_current,
        "season_mismatch": season_mismatch,
        "label": f"{season} - {stage}",
    }
