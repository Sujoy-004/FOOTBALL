"""Role-keyed, content-independent freshness stamp for canonical stores (D-02/D-03).

RECON-03 / RECON-04 substrate: a request handler decides "is my cached
derived state still fresh?" from ONE comparison of ``(role, mtime_ns, size)``
per store file. The stamp is derived from ``os.stat`` metadata alone — store
*contents* are never re-read or diffed, so the check is cheap and the
comparison is atomic (D-02).

Design rules:

* **Role-keyed, never filename-keyed.** ``roles`` maps a LOGICAL role
  (``"results"``, ``"fixtures"``, ``"groups"`` …) to the physical filename.
  Roles survive canonicalisation rekeying; filenames do not (roadmap landmine).
* **A missing file is ABSENCE, not a zero.** A role whose file cannot be
  stat'ed is omitted from :attr:`StoreStamp.entries` entirely — a missing store
  is a fact about the generation, never a fabricated ``(role, 0, 0)`` entry.
  This mirrors ``football_core.freshness.store_mtime``'s
  "absent is a fact, not an error" discipline.
* **Nanosecond mtime.** ``st_mtime_ns`` (never ``st_mtime``) matches
  ``football_core/state.py`` staleness semantics.

Ground rules: stdlib only — no ``web`` imports and no ``competitions``
imports, and no repo-path knowledge. Callers pass the data directory and the
role→filename map, which keeps the kernel competition-agnostic. The layering
guard (``tests/test_layering_architecture.py``) enforces this.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class StoreStamp:
    """An immutable, content-independent freshness fingerprint.

    Attributes:
        entries: One ``(role, mtime_ns, size)`` triple per PRESENT store file,
            in a stable order so two stamps compare equal exactly when the
            same roles were present with the same metadata. A missing/unreadable
            role file is simply absent — never a zero entry.
    """

    entries: tuple[tuple[str, int, int], ...]

    def as_dict(self) -> dict[str, list[int]]:
        """``role -> [mtime_ns, size]`` for a JSON-friendly view of the stamp."""
        return {role: [mtime_ns, size] for role, mtime_ns, size in self.entries}


def stamp_store(data_dir: Path, roles: Mapping[str, str]) -> StoreStamp:
    """Stamp every PRESENT store file in *data_dir*, keyed by logical role.

    Args:
        data_dir: Directory holding the store files (caller-supplied).
        roles: Logical role -> filename. Iterated in SORTED role order so the
            ``entries`` tuple has a stable, comparable ordering.

    Returns:
        A frozen :class:`StoreStamp`. Roles whose file is missing or cannot be
        stat'ed are omitted (a missing store is a fact, not an error).
    """
    base = Path(data_dir)
    entries: list[tuple[str, int, int]] = []
    for role in sorted(roles):
        try:
            st = os.stat(base / roles[role])
        except OSError:
            # FileNotFoundError (absent) and any other OSError (unreadable) are
            # both "no fact to record" — omit the role, never raise.
            continue
        entries.append((role, st.st_mtime_ns, st.st_size))
    return StoreStamp(tuple(entries))


def sub_stamp(stamp: StoreStamp | None, roles: Iterable[str]) -> StoreStamp | None:
    """The sub-stamp over *roles* only — a pure filter of an already-collected stamp.

    Zero extra I/O: the entries were already stat'ed for the full stamp, so
    narrowing to the results roles costs one tuple filter, not another
    ``os.stat`` pass. A role absent from the stamp stays ABSENT (absence is
    a fact about the generation, never a fabricated zero entry), and the
    original tuple order is preserved so two sub-stamps compare equal
    exactly when the same roles were present with the same metadata.

    Args:
        stamp: The full stamp, or ``None`` when the caller has none.
        roles: The logical roles to keep.

    Returns:
        A :class:`StoreStamp` over the requested roles, or ``None`` when
        *stamp* is ``None``.
    """
    if stamp is None:
        return None
    wanted = set(roles)
    return StoreStamp(tuple(entry for entry in stamp.entries if entry[0] in wanted))
