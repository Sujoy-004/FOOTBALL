"""Per-competition single-reference frozen snapshot holder (RECON-03/04).

D-01/D-04 substrate: one ``DerivedState`` per competition — the computed
derived dict (standings, bracket, signal caches) **plus** the freshness
:class:`~football_core.store_stamp.StoreStamp` **plus** the folded display mode
— carried in a single frozen object behind a ``MappingProxyType`` and rebound
in ONE assignment. A reader can never observe new data with an old stamp or
vice versa (the "photo that includes its own timestamp").

Locking discipline (D-04):

* The **fast path is lock-free** - ``read_*`` and the stamp comparison read a
  single dict item, which is atomic under the GIL. No lock is taken on the
  hot path.
* Only the **rebuild** takes ``_REBUILD_LOCKS[comp]`` (a RE-ENTRANT
  ``threading.RLock``, pre-created so there is no lock-creation race) and
  double-checks the stamp before rebuilding. The same lock serialises
  ``publish_data``, so a publish can never interleave with a rebuild's
  rebind.
* ``_BOOT_LOCK`` is a DISTINCT lock from ``_REBUILD_LOCKS[*]``, so a
  ``build()`` callback may safely call ``append_boot``/``boot_step`` while the
  rebuild lock is held - the two locks are never nested on the same thread.

Stamp discipline (STAMP-BEFORE-BUILD):

* The stamp is sampled BEFORE the data is built, at every publish site. A
  store write that lands during the build therefore publishes the OLDER
  stamp, and the next request observes a mismatch and rebuilds. Sampling
  after the build would publish (older data, newer stamp) - a pair a later
  request would MATCH and serve as current, permanently. That is the state
  the phase goal forbids.
* The ORDER is what enforces it, not a comparison of stamps. A stamp says
  which store generation was observed; it cannot say whether the DATA that
  accompanies it is stale. Publishing an OLDER stamp is harmless (the next
  request sees the mismatch and rebuilds); publishing a NEWER stamp next to
  older data is the dangerous pair, and only the order rules it out.

The callbacks (``build``) are caller-supplied and MUST NOT publish for the
same competition: :func:`publish_data` takes the same per-competition lock,
so a build callback that publishes is re-entrant. That case is guarded
explicitly in :func:`get_or_rebuild` (it raises) rather than hanging or
recursing forever. A build callback may still touch the boot ledger, which
has its own distinct lock.

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

#: One lock per shipped competition, pre-created to avoid a lock-creation
#: race. It is RE-ENTRANT on purpose: :func:`publish_data` takes the SAME
#: lock as :func:`get_or_rebuild`, so a build callback that publishes (a
#: contract violation, but a possible one) must deadlock-by-hang never
#: happen. Re-entrancy is guarded explicitly inside
#: :func:`get_or_rebuild` instead, so the hazard is a loud error rather than
#: an invisible hang.
_REBUILD_LOCKS: dict[str, threading.RLock] = {
    "worldcup": threading.RLock(),
    "ucl": threading.RLock(),
    "laliga": threading.RLock(),
}

#: Fallback for a competition id outside the three shipped ones.
_FALLBACK_LOCK = threading.RLock()

#: Per-thread record of the competitions this thread is currently rebuilding.
#: Used to turn a re-entrant rebuild (the D-04 contract violation the threat
#: model tracks) into an explicit error instead of unbounded recursion.
_REBUILDING = threading.local()


def _rebuild_lock(comp: str) -> threading.RLock:
    """The rebuild lock for *comp* (pre-created, or the shared fallback)."""
    return _REBUILD_LOCKS.get(comp, _FALLBACK_LOCK)


def _rebuilding_comps() -> set:
    """The set of competitions THIS thread is currently rebuilding."""
    comps = getattr(_REBUILDING, "comps", None)
    if comps is None:
        comps = set()
        _REBUILDING.comps = comps
    return comps


@dataclass(frozen=True)
class DerivedState:
    """An immutable snapshot: derived data + its freshness stamp + display mode.

    Attributes:
        stamp: The :class:`~football_core.store_stamp.StoreStamp` this data was
            built from — the ONE value a request compares to decide freshness.
            ``None`` when the publisher had no freshness information; such a
            snapshot never matches an observed stamp, so the next request
            rebuilds.
        data: The recursively-frozen derived dict.
        mode: The folded display mode (``"results"``/``"simulation"``/…) that
            was current when the snapshot was built.
    """

    stamp: StoreStamp | None
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
        active = _rebuilding_comps()
        if comp in active:
            # A build callback that calls get_or_rebuild for the SAME
            # competition is the D-04 contract violation. Fail loudly instead
            # of recursing forever or hanging on a non-reentrant lock.
            raise RuntimeError(
                f"re-entrant rebuild for {comp!r}: the build callback must not "
                f"call get_or_rebuild for the same competition"
            )
        active.add(comp)
        try:
            data, mode = build()
        finally:
            active.discard(comp)
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


def publish_data(comp: str, data: dict, mode: str | None,
                 stamp: StoreStamp | None) -> None:
    """Publish a complete frozen ``DerivedState`` for *comp* in ONE assignment.

    The stamp MUST be sampled BEFORE the data was built. A store write that
    lands during the build then yields the OLDER stamp, and the next request
    observes a MISMATCH and rebuilds — the safe direction. Sampling after the
    build would publish (older data, newer stamp): a later request would
    MATCH that stamp and serve the stale payload as current, permanently,
    because the match suppresses any rebuild. That pair is the exact state
    the phase goal forbids, and the ORDER is what prevents it — not a
    comparison of stamps, because a stamp cannot say whether the DATA it
    accompanies is stale. A publish of an OLDER stamp is harmless (the next
    request sees the mismatch and rebuilds); a publish of a NEWER stamp
    paired with older data is the dangerous one, and only the order rules
    it out.

    The assignment is a single dict store, which is atomic under the GIL,
    so a reader sees either the whole previous snapshot or the whole new
    one — never a half-built one.

    Args:
        comp: Competition id.
        data: The derived state (frozen on publish; never mutated after).
        mode: The display mode folded into the snapshot.
        stamp: The freshness stamp the data was built against, or ``None``
            when the caller has no freshness information to offer.
    """
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


def thaw(obj):
    """Return a plain, mutable copy of a value read out of the holder.

    The holder freezes every nested ``dict`` into a ``MappingProxyType`` and
    every nested ``list`` into a ``tuple``, so a reader can never corrupt
    state another reader will see. A consumer that hands the value to a
    competition brain — which is written against plain ``dict``/``list`` and
    type-checks them with ``isinstance`` — needs the mutable shape back.

    This is the ONE place that conversion is allowed to happen: the freeze is
    an implementation detail of this module, and the brains keep their
    plain-data contract.

    Args:
        obj: Any value (frozen or not).

    Returns:
        The same value with every frozen container replaced by its plain
        equivalent. Opaque values (numbers, strings, dataclasses) pass
        through unchanged.
    """
    if isinstance(obj, MappingProxyType):
        return {key: thaw(value) for key, value in obj.items()}
    if isinstance(obj, tuple):
        return [thaw(value) for value in obj]
    if isinstance(obj, list):
        return [thaw(value) for value in obj]
    if isinstance(obj, frozenset):
        return {thaw(value) for value in obj}
    if isinstance(obj, set):
        return {thaw(value) for value in obj}
    return obj
