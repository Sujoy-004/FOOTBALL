"""Per-competition single-reference frozen snapshot holder (RECON-03/04).

D-01/D-04 substrate: one ``DerivedState`` per competition — the computed
derived dict (standings, bracket, signal caches) **plus** the freshness
:class:`~football_core.store_stamp.StoreStamp` **plus** the folded display mode
— carried in a single frozen object behind a ``MappingProxyType`` and rebound
in ONE assignment. A reader can never observe new data with an old stamp or
vice versa (the "photo that includes its own timestamp").

Locking discipline (D-04):

* The **fast path is lock-free** — ``read_*`` and the stamp comparison read a
  single dict item, which is atomic under the GIL. No lock is taken on the
  hot path.
* Only the **rebuild** takes ``_REBUILD_LOCKS[comp]`` (a non-reentrant
  ``threading.Lock``, pre-created so there is no lock-creation race) and
  double-checks the stamp before rebuilding.
* ``_BOOT_LOCK`` is a DISTINCT lock from ``_REBUILD_LOCKS[*]``, so a
  ``build()`` callback may safely call ``append_boot``/``boot_step`` while the
  rebuild lock is held — the two locks are never nested on the same thread.

The callbacks (``build``) are caller-supplied and MUST be lock-free with
respect to this module: only the rebind is inside the lock.

Read-path contract: every value reachable from :attr:`DerivedState.data` is
recursively frozen by :func:`_freeze` (dict→``MappingProxyType``,
list/tuple→``tuple``, set/frozenset→``frozenset``), so a request handler cannot
corrupt state another request will read. Opaque objects (a live signal
engine, a dataclass) are passed through as values and are read via
``.get(...)``/attribute access, never mutated.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from football_core.store_stamp import StoreStamp

#: The ONE mutable reference per competition (RECON-04). Values are frozen
#: ``DerivedState`` objects; a reader sees a complete generation or the
#: previous one, never a half-built one.
_STATES: dict[str, DerivedState] = {}

#: Simulated results slot — frozen payload, rebound (never mutated in place).
_SIMS: dict[str, MappingProxyType] = {}

#: Boot-diagnostic ledger — a SEPARATE single-ref slot per competition, an
#: immutable tuple rebind; appends happen under one lock.
_BOOTS: dict[str, tuple[dict, ...]] = {}

#: Distinct from the rebuild locks: build() may append to the boot ledger.
_BOOT_LOCK = threading.Lock()

#: One non-reentrant lock per shipped competition, pre-created to avoid a
#: lock-creation race.
_REBUILD_LOCKS: dict[str, threading.Lock] = {
    "worldcup": threading.Lock(),
    "ucl": threading.Lock(),
    "laliga": threading.Lock(),
}

#: Fallback for a competition id outside the three shipped ones.
_FALLBACK_LOCK = threading.Lock()


def _rebuild_lock(comp: str) -> threading.Lock:
    """The rebuild lock for *comp* (pre-created, or the shared fallback)."""
    return _REBUILD_LOCKS.get(comp, _FALLBACK_LOCK)


@dataclass(frozen=True)
class DerivedState:
    """An immutable snapshot: derived data + its freshness stamp + display mode.

    Attributes:
        stamp: The :class:`~football_core.store_stamp.StoreStamp` this data was
            built from — the ONE value a request compares to decide freshness.
        data: The recursively-frozen derived dict.
        mode: The folded display mode (``"results"``/``"simulation"``/…) that
            was current when the snapshot was built.
    """

    stamp: StoreStamp
    data: MappingProxyType
    mode: str | None


def _freeze(obj):
    """Recursively freeze *obj* so no nested value is mutable.

    ``dict`` → ``MappingProxyType`` (recursing), ``list``/``tuple`` → ``tuple``
    (recursing), ``set``/``frozenset`` → ``frozenset`` (recursing); every other
    object is returned as-is (opaque values such as a live signal engine stay
    readable via ``.get(...)``/attributes and are never mutated by a reader).
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_freeze(v) for v in obj)
    if isinstance(obj, (set, frozenset)):
        return frozenset(_freeze(v) for v in obj)
    return obj


def get_or_rebuild(
    comp: str,
    observed: StoreStamp,
    build: Callable[[], tuple[dict, str | None]],
) -> MappingProxyType:
    """Return the cached snapshot for *comp*, rebuilding only when its stamp moved.

    Args:
        comp: Competition id.
        observed: The stamp computed from the store files for this request.
        build: Lock-free callback returning ``(data, mode)``. Called at most
            once per stamp generation, and NEVER while the holder holds a lock
            that ``build`` itself needs.

    Returns:
        The frozen derived data for the (possibly rebuilt) snapshot.
    """
    current = _STATES.get(comp)  # lock-free fast path
    if current is not None and current.stamp == observed:
        return current.data
    lock = _rebuild_lock(comp)
    with lock:
        current = _STATES.get(comp)  # double-check after acquiring the lock
        if current is not None and current.stamp == observed:
            return current.data
        data, mode = build()
        fresh = DerivedState(
            stamp=observed,
            data=MappingProxyType(_freeze(data)),
            mode=mode,
        )
        _STATES[comp] = fresh  # ONE atomic publish
        return fresh.data


def read_data(comp: str) -> MappingProxyType:
    """The published derived data for *comp*, or ``{}`` when never published."""
    current = _STATES.get(comp)
    return current.data if current is not None else MappingProxyType({})


def read_mode(comp: str) -> str | None:
    """The published display mode for *comp*, or ``None`` when never published."""
    current = _STATES.get(comp)
    return current.mode if current is not None else None


def read_stamp(comp: str) -> StoreStamp | None:
    """The published freshness stamp for *comp*, or ``None`` when never published."""
    current = _STATES.get(comp)
    return current.stamp if current is not None else None


def publish_data(comp: str, data: dict, mode: str | None, stamp: StoreStamp) -> None:
    """Publish a complete frozen ``DerivedState`` for *comp* in ONE assignment."""
    _STATES[comp] = DerivedState(
        stamp=stamp,
        data=MappingProxyType(_freeze(data)),
        mode=mode,
    )


def read_sim(comp: str) -> MappingProxyType:
    """The published simulation payload for *comp*, or ``{}`` when never published."""
    return _SIMS.get(comp, MappingProxyType({}))


def publish_sim(comp: str, payload: dict) -> None:
    """Publish a complete frozen simulation payload in ONE assignment."""
    _SIMS[comp] = MappingProxyType(_freeze(payload))


def clear_sim(comp: str) -> None:
    """Rebind the sim slot to ``{}`` (D-06) — never mutate in place."""
    _SIMS[comp] = MappingProxyType({})


def read_boot(comp: str) -> tuple[dict, ...]:
    """The published boot ledger for *comp*, or ``()`` when never set."""
    with _BOOT_LOCK:
        return _BOOTS.get(comp, ())


def publish_boot(comp: str, entries) -> None:
    """Publish the boot ledger for *comp* as an immutable tuple."""
    with _BOOT_LOCK:
        _BOOTS[comp] = tuple(entries)


def append_boot(comp: str, entry: dict) -> None:
    """Append one boot entry, lost-update safe (read-current + rebind under lock)."""
    with _BOOT_LOCK:
        _BOOTS[comp] = _BOOTS.get(comp, ()) + (entry,)


def reset(comp: str | None = None) -> None:
    """Test seam: clear the state/sim/boot slots for *comp*, or all when ``None``."""
    if comp is None:
        _STATES.clear()
        _SIMS.clear()
        with _BOOT_LOCK:
            _BOOTS.clear()
        return
    _STATES.pop(comp, None)
    _SIMS.pop(comp, None)
    with _BOOT_LOCK:
        _BOOTS.pop(comp, None)
