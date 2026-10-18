"""Derived-state substrate: role-keyed stamps + frozen per-competition snapshots.

``holder`` (built in plan 04-02) owns the single-reference frozen snapshot and
the rebuild-only lock; ``stamps`` carries the logical-role → filename maps.
Both are the reusable primitives that RECON-03/RECON-04 require before any web
sub-app can stop using its module globals.
"""

from __future__ import annotations
