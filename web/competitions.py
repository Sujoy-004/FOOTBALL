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

Acquisition (Exchange 4 v2): each adapter exposes ``refresh()``, a
competition-scoped acquisition entry point that attempts fresh data for
THIS competition only and never raises. Server boot makes ZERO provider
calls; acquisition is lazy — a competition's first data-API request fires
its own refresh at most once per process (``try_lazy_refresh``). Why lazy
per competition: the user may never open the other tab, so unrelated
providers must not fire merely because the server started; eager scraping
of every registered competition on boot wasted quota and coupled
competitions that share nothing. Deployments that want warm tabs can set
``FOOTBALL_PRELOAD_ALL=1`` to restore eager preloading via
``adapter.refresh()`` in web.server's lifespan.

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

import threading
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
    # Competition-scoped acquisition hook (Exchange 4 v2). Returns an
    # IngestReport-shaped dict; the wrapper's own snapshot gating applies.
    refresh_fn: Optional[Callable[[], dict]] = None

    def status(self) -> dict:
        return self.get_status()

    def simulation(self) -> dict:
        return self.simulation_support()

    def refresh(self) -> dict:
        """Attempt fresh acquisition for THIS competition only. Never raises.

        Returns an IngestReport-shaped dict (provider/attempted/success/
        error/stale/stages/...). Snapshot-mode gating lives inside each
        app's fetch wrapper (zero network when explicit offline); this
        method only adds never-raise armor and honest reporting for
        adapters registered without a hook.
        """
        if self.refresh_fn is None:
            return {"provider": None, "attempted": False, "success": False,
                    "error": "no acquisition hook registered",
                    "stale": True}
        try:
            report = self.refresh_fn()
        except Exception as e:
            return {"provider": None, "attempted": True, "success": False,
                    "error": f"{e.__class__.__name__}: {e}",
                    "stale": True}
        if isinstance(report, dict):
            return dict(report)
        return {"provider": None, "attempted": True, "success": False,
                "error": f"acquisition hook returned "
                         f"{type(report).__name__}",
                "stale": True}


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


# ── Lazy, competition-scoped acquisition (Exchange 4 v2) ────────────────
#
# Server boot performs ZERO provider calls. Each competition's fresh
# acquisition fires at most ONCE PER PROCESS, on its first data-API
# request. Rationale: the user may never open the other tab, so
# unrelated providers must not fire merely because the server started;
# boot stays instant and offline-safe while every tab still warms itself
# on first open.

_LAZY_FIRED: set[str] = set()
_LAZY_LOCK = threading.Lock()


def _registry_adapter(competition_id: str) -> Optional[CompetitionAdapter]:
    try:
        return REGISTRY.get(competition_id)
    except UnknownCompetitionError:
        return None


def try_lazy_refresh(competition_id: str) -> Optional[dict]:
    """Fire THIS competition's acquisition at most once per process.

    Called at the top of each sub-app's primary read endpoint. Honors
    explicit offline mode: when ``is_snapshot_mode()`` is true nothing is
    attempted — but the once-slot IS consumed and the wrapper's truthful
    attempted=False skipped report is recorded exactly once (wrappers
    self-gate: zero network), so the first data response still discloses
    WHY no live fetch happened instead of silently looking live-fresh.
    """
    with _LAZY_LOCK:
        if competition_id in _LAZY_FIRED:
            return None
        _LAZY_FIRED.add(competition_id)

    from web.startup import is_snapshot_mode

    adapter = _registry_adapter(competition_id)
    if adapter is None:
        return None

    if is_snapshot_mode():
        # Explicit offline => never attempt. Invoke refresh() purely to
        # record the wrapper's snapshot-skipped report; wrappers make
        # zero network requests in this mode (tested guarantee).
        adapter.refresh()
        return None
    return adapter.refresh()


def consume_lazy_gate(competition_id: str) -> None:
    """Mark a competition's lazy slot as fired WITHOUT attempting.

    Used by eager preloading (FOOTBALL_PRELOAD_ALL=1) so the first data
    request does not re-attempt after boot already refreshed.
    """
    with _LAZY_LOCK:
        _LAZY_FIRED.add(competition_id)


def lazy_gate_fired(competition_id: str) -> bool:
    """True when the once-per-process slot was already consumed."""
    return competition_id in _LAZY_FIRED


def reset_lazy_gates() -> None:
    """Test seam: clear all once-per-process gates."""
    with _LAZY_LOCK:
        _LAZY_FIRED.clear()


def install_lazy_acquisition_hook(subapp: FastAPI, competition_id: str,
                                  api_path: str = "/api/data") -> None:
    """Route-level lazy-acquisition shim for sub-apps owned elsewhere.

    wc_app.py belongs to another agent, so the worldcup hook is installed
    here as an HTTP middleware that fires try_lazy_refresh immediately
    before the primary data endpoint runs (mounted scope: Starlette strips
    the mount prefix before sub-app middleware sees the path). The one-
    line follow-up for web/wc_app.py is a direct try_lazy_refresh call at
    the top of api_data, after which this shim can be dropped.
    """
    from starlette.concurrency import run_in_threadpool

    # Registries may be rebuilt repeatedly (tests) against the shared
    # sub-app objects; install the middleware exactly once.
    if getattr(subapp.state, "_lazy_hook_installed_for", None) == competition_id:
        return
    subapp.state._lazy_hook_installed_for = competition_id

    @subapp.middleware("http")
    async def _fire_lazy_acquisition(request, call_next):
        if request.url.path.endswith(api_path):
            await run_in_threadpool(try_lazy_refresh, competition_id)
        return await call_next(request)


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
        # Delegate to the app's own block so handler and adapter cannot
        # drift apart.
        return wc_app._simulation_state_block()

    def wc_refresh() -> dict[str, Any]:
        """WC-scoped acquisition: exactly the wc_app/pipeline ingest path.

        Touches only the worldcup provider selection + brain pipeline;
        the UCL app is never imported into this call path.
        """
        return dict(wc_app._fetch_live_data() or {})

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
        refresh_fn=wc_refresh,
    ))
    # wc_app.py is owned by another agent: install the lazy hook here for
    # now (see install_lazy_acquisition_hook docstring).
    install_lazy_acquisition_hook(wc_app.wc_app, "worldcup")

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
        return ucl_app._simulation_state_block()

    def ucl_refresh() -> dict[str, Any]:
        """UCL-scoped acquisition: exactly the ucl_app ingest path.

        Delegates to web.ucl_app._fetch_live_data (the UCL brain's
        fetch_live_data + freshness ledger); the worldcup pipeline is
        never imported into this call path.
        """
        ucl_app._fetch_live_data()
        return dict(getattr(ucl_app, "_refresh_report", {}) or {})

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
        refresh_fn=ucl_refresh,
    ))

    return registry


REGISTRY = build_default_registry()
