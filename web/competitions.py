"""Competition registry and adapter boundary (Exchange 4).

Explicit, dumb discovery of which competitions exist and what they can do.
No plugin framework, no dynamic package magic: the default registry lists
the two shipped competitions by name; a future competition (La Liga,
Serie A) plugs in by appending one adapter to ``build_default_registry``.

Layering: adapters live in the WEB layer because they hold FastAPI
sub-apps and closures over app modules. They never import football_core
internals, never own tournament rules, and never shape competition
payloads - those stay in the brains. All callables read module attributes
dynamically at call time because the apps rebind globals (cache/sim_cache)
during refreshes.

Status contract (identical shape for every competition):

    get_status() -> {
        "phase":        <brain-owned phase dict: phase/label/champion/
                         progress/stores>,
        "n_played":     int,
        "n_unplayed":   int,
        "mode":         "results"|"simulation"|None,
        "availability": {store: "available"|"empty"|"missing"|"unavailable"},
        "champion":     str | None,
    }

    simulation_support() -> {
        "availability": "available"|"not_needed"|"unavailable",
        "reason":       code or None,
        "request_state":"not_requested"|"running"|"completed"|"failed",
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fastapi import FastAPI


class UnknownCompetitionError(KeyError):
    """Raised for competition ids that are not registered."""

    def __init__(self, competition_id: str, known: list[str]) -> None:
        self.competition_id = competition_id
        self.known = known
        super().__init__(
            f"unknown competition {competition_id!r}; "
            f"known competitions: {', '.join(known)}"
        )


@dataclass(frozen=True)
class CompetitionAdapter:
    """Everything the shared shell may know about one competition."""

    id: str
    display_name: str
    mount_prefix: str
    api_prefix: str
    subapp: FastAPI
    get_status: Callable[[], dict]
    simulation_support: Callable[[], dict]
    short: str = ""
    season_label: str = ""
    # Optional thin delegation; competitions without simulation omit it.
    run_simulation: Optional[Callable[..., tuple[int, dict]]] = None

    def status(self) -> dict:
        return self.get_status()

    def simulation(self) -> dict:
        return self.simulation_support()


class CompetitionRegistry:
    """Explicit registration list; insertion order is presentation order."""

    def __init__(self) -> None:
        self._adapters: dict[str, CompetitionAdapter] = {}

    def register(self, adapter: CompetitionAdapter) -> None:
        if adapter.id in self._adapters:
            raise ValueError(f"competition {adapter.id!r} already registered")
        self._adapters[adapter.id] = adapter

    def get(self, competition_id: str) -> CompetitionAdapter:
        if competition_id not in self._adapters:
            raise UnknownCompetitionError(competition_id, self.ids())
        return self._adapters[competition_id]

    def list(self) -> list[CompetitionAdapter]:
        return list(self._adapters.values())

    def ids(self) -> list[str]:
        return list(self._adapters.keys())


def build_default_registry() -> CompetitionRegistry:
    """The shipped competitions, registered explicitly.

    Kept as a factory so tests can build isolated registries without
    touching the module-level singleton.
    """
    # Imported here so importing this module stays cheap and side-effect
    # free for unit tests of the registry mechanics themselves.
    from web import ucl_app, wc_app

    registry = CompetitionRegistry()

    def wc_status() -> dict[str, Any]:
        phase = wc_app.cache.get("phase") or {}
        return {
            "phase": phase,
            "n_played": wc_app.cache.get("n_played", 0),
            "n_unplayed": wc_app.unplayed_match_count(),
            "mode": None,  # WC has no mode concept; real data always shown
            "availability": dict(phase.get("stores", {})),
            "champion": phase.get("champion"),
        }

    def wc_simulation_support() -> dict[str, Any]:
        eligible, reason, _msg = wc_app.simulation_eligibility()
        sim_status = wc_app.sim_cache.get("status", "not_requested")
        request_state = {
            "running": "running",
            "completed": "completed",
            "failed": "failed",
        }.get(sim_status, "not_requested" if sim_status in ("", "none", "not_requested") else sim_status)
        return {
            "availability": "available" if eligible else "not_needed",
            "reason": reason,
            "request_state": request_state,
        }

    registry.register(CompetitionAdapter(
        id="worldcup",
        display_name="World Cup 2026",
        short="WC",
        mount_prefix="/worldcup",
        api_prefix="/worldcup/api",
        subapp=wc_app.wc_app,
        get_status=wc_status,
        simulation_support=wc_simulation_support,
        run_simulation=lambda **kw: wc_app.service.start(
            competition_id="worldcup", **kw),
    ))

    def ucl_status() -> dict[str, Any]:
        counts = ucl_app._match_counts()
        return {
            "phase": ucl_app.cache.get("phase") or {},
            "n_played": counts[1] - counts[0],
            "n_unplayed": counts[0],
            "mode": getattr(ucl_app, "_mode", None),
            "availability": dict(ucl_app.cache.get("availability", {})),
            "champion": ucl_app.cache.get("champion"),
        }

    def ucl_simulation_support() -> dict[str, Any]:
        eligible, reason, _msg = ucl_app.simulation_eligibility()
        sim_status = ucl_app.sim_cache.get("status", "not_requested")
        request_state = {
            "running": "running",
            "completed": "completed",
            "failed": "failed",
        }.get(sim_status, "not_requested" if sim_status in ("", "none", "not_requested") else sim_status)
        return {
            "availability": "available" if eligible else "not_needed",
            "reason": reason,
            "request_state": request_state,
        }

    registry.register(CompetitionAdapter(
        id="ucl",
        display_name="UEFA Champions League 2025/26",
        short="UCL",
        mount_prefix="/ucl",
        api_prefix="/ucl/api",
        subapp=ucl_app.ucl_app,
        get_status=ucl_status,
        simulation_support=ucl_simulation_support,
        run_simulation=lambda **kw: ucl_app.service.start(
            competition_id="ucl", **kw),
    ))

    return registry


REGISTRY = build_default_registry()
