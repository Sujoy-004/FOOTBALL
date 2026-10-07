"""Unit coverage for every ``derive_success()`` verdict branch (D-13).

``success`` must be a *derived* fact of the ingestion counters, never a
declared constant. This file pins the four verdicts and their ordering so no
construction site can reintroduce a hardcoded ``success=True``:

1. nothing attempted            -> ``(False, "deferred")``
2. attempted, zero received     -> ``(False, "deferred/provider-empty")``
3. attempted, broken invariant  -> ``(False, "counter_inconsistent")`` (fails closed)
4. attempted, consistent work   -> ``(True, None)``
"""

from __future__ import annotations

import logging

from football_core.fetcher import derive_success


def _counters(**overrides) -> dict:
    """A complete, zeroed finished-result counter dict."""
    base = {
        "received": 0,
        "normalized": 0,
        "ingested": 0,
        "skipped_unmatchable": 0,
        "skipped_no_target": 0,
        "skipped_missing_score": 0,
    }
    base.update(overrides)
    return base


# ── 4. success: attempted work with a consistent counter state ──────────────


def test_attempted_with_received_results_is_success():
    counters = _counters(received=72, normalized=72, ingested=72)
    assert derive_success("football-data-org", True, counters) == (True, None)


def test_skips_are_allowed_when_the_invariant_holds():
    counters = _counters(
        received=72,
        normalized=72,
        ingested=68,
        skipped_unmatchable=2,
        skipped_no_target=1,
        skipped_missing_score=1,
    )
    assert derive_success("football-data-org", True, counters) == (True, None)


# ── 2. deferred/provider-empty: attempted, nothing received ─────────────────


def test_attempted_with_zero_received_is_provider_empty():
    success, reason = derive_success("football-data-org", True, _counters())
    assert success is False
    assert reason == "deferred/provider-empty"


def test_attempted_with_empty_counters_is_provider_empty():
    assert derive_success("bsd", True, {}) == (False, "deferred/provider-empty")


# ── 1. deferred: nothing was attempted, so nothing succeeded ────────────────


def test_not_attempted_is_deferred_even_with_counters_present():
    counters = _counters(received=144, normalized=144, ingested=144)
    success, reason = derive_success(None, False, counters)
    assert success is False
    assert reason == "deferred"


def test_not_attempted_with_zero_counters_is_deferred():
    assert derive_success(None, False, _counters()) == (False, "deferred")


# ── 3. counter_inconsistent: a broken invariant fails closed ────────────────


def test_invariant_violation_fails_closed_with_provider_warning(caplog):
    counters = _counters(received=5, normalized=4, ingested=4)
    with caplog.at_level(logging.WARNING, logger="football_core.fetcher"):
        success, reason = derive_success("bsd", True, counters)
    assert success is False
    assert reason == "counter_inconsistent"
    assert any("bsd" in record.message for record in caplog.records), (
        "the warning must name the provider so the broken run is traceable"
    )


def test_missing_counter_key_is_treated_as_a_violation():
    # received > 0 so rule 2 does not fire, but the skipped_* keys are absent:
    # absence of evidence can never read as a consistent run.
    counters = {"received": 72, "normalized": 72, "ingested": 72}
    assert derive_success("bsd", True, counters) == (False, "counter_inconsistent")
