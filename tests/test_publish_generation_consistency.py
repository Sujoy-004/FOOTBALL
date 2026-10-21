"""Publication-generation consistency for the derived-state holder (D-09).

Phase 04's verification found two blockers in the code the phase itself
delivered. Both are about the ORDER of two operations, so both are pinned
here as ORDER tests plus one semantic proof at the holder level.

**Gap 1 — a half-stamped snapshot.** Every publish site used to build the
data FIRST and sample the stamp SECOND. A store write that lands in that
window publishes *(data from generation n, stamp from generation n+1)*. A
later request observes generation n+1, finds the stamp equal, and serves the
stale payload as current — permanently, because the matching stamp
suppresses any rebuild. The read path already sampled the stamp *before* the
build, which is the safe direction; only the write path was backwards.

**Gap 2 — the simulation outlived the facts.** ``clear_sim`` ran AFTER the
(slow) rebuild, so between the ingest and the clear ``GET /api/simulation``
still served the previous run while ``GET /api/data`` served the newly
ingested facts. The season-switch path in the same modules already used the
correct order, so the two paths disagreed inside the same file.

The invariant both fixes restore: **the published stamp is never NEWER than
the data it describes**, and **a retired simulation is retired before the new
facts are published**.
"""

from __future__ import annotations

import importlib

import pytest

from football_core.store_stamp import StoreStamp, stamp_store
from web.derived import holder

#: competition id -> the web sub-app module that owns its refresh path.
APPS = {
    "laliga": "web.laliga_app",
    "ucl": "web.ucl_app",
    "worldcup": "web.wc_app",
}

COMP_IDS = tuple(APPS)


def _mod(comp: str):
    """The web sub-app module for *comp*."""
    return importlib.import_module(APPS[comp])


def _stamp(gen: int) -> StoreStamp:
    """A synthetic stamp whose single role carries *gen* as its mtime."""
    return StoreStamp(entries=(("results", gen, gen),))


@pytest.fixture(autouse=True)
def _clean_holder():
    holder.reset()
    yield
    holder.reset()


class _Recorder:
    """Records the order of the seam calls a refresh path makes."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def stamp(self) -> str:
        self.calls.append("stamp")
        return "stamp"

    def build(self) -> str:
        self.calls.append("build")
        return "build"

    def publish(self) -> str:
        self.calls.append("publish")
        return "publish"

    def clear_sim(self) -> str:
        self.calls.append("clear_sim")
        return "clear_sim"


def _drive_refresh(comp: str, monkeypatch, recorder: _Recorder,
                   stamps: list[StoreStamp]) -> int:
    """Run *comp*'s refresh path with every seam stubbed; return the status.

    The ingest is stubbed to a no-op so the test makes ZERO provider calls,
    and the store stamps are fed from *stamps* so the test can decide
    whether the ingest "wrote" anything.
    """
    mod = _mod(comp)
    monkeypatch.setattr(mod, "_fetch_live_data", lambda: None)

    pending = list(stamps)

    def fake_observed_stamp() -> StoreStamp:
        recorder.stamp()
        return pending.pop(0)

    def fake_build_state():
        recorder.build()
        return {"n": 1}, "results"

    monkeypatch.setattr(mod, "_observed_stamp", fake_observed_stamp)
    monkeypatch.setattr(mod, "_build_state", fake_build_state)

    real_publish = holder.publish_data
    real_clear = holder.clear_sim

    def fake_publish(c, data, mode, stamp):
        recorder.publish()
        real_publish(c, data, mode, stamp)

    def fake_clear(c):
        recorder.clear_sim()
        real_clear(c)

    monkeypatch.setattr(holder, "publish_data", fake_publish)
    monkeypatch.setattr(holder, "clear_sim", fake_clear)

    response = mod.api_refresh()
    return response.status_code


# --------------------------------------------------------------------------
# Gap 1 — the publish path must not publish a NEWER stamp than its data
# --------------------------------------------------------------------------


@pytest.mark.parametrize("comp", COMP_IDS)
def test_refresh_publishes_a_stamp_sampled_before_the_build(comp, monkeypatch):
    """The stamp used for the publish is sampled BEFORE the build.

    The refresh path samples the stamp twice: once before the ingest (to
    detect whether anything was written) and once after it. The publish must
    use a stamp observed no LATER than the build's start — never one
    observed after it.
    """
    recorder = _Recorder()
    # The post-ingest sample is the NEWER one; if the publish used a stamp
    # sampled after the build, the recorded order would put a "stamp" call
    # after "build".
    status = _drive_refresh(comp, monkeypatch, recorder, [_stamp(1), _stamp(2)])
    assert status == 200

    calls = recorder.calls
    assert "build" in calls, f"the build never ran: {calls}"
    build_at = calls.index("build")
    publish_at = calls.index("publish")
    stamps_before_build = [i for i, c in enumerate(calls[:build_at]) if c == "stamp"]
    assert stamps_before_build, f"no stamp sampled before the build: {calls}"
    # Every stamp sampled after the build would be a NEWER observation than
    # the data — the half-stamped pair.
    assert not [i for i, c in enumerate(calls[build_at:publish_at]) if c == "stamp"], (
        f"the publish used a stamp sampled after the build: {calls}"
    )


def test_a_store_write_during_the_build_cannot_publish_a_newer_stamp(tmp_path):
    """The semantic proof: (older data, newer stamp) must be unreachable.

    A store write lands DURING the build. The published snapshot must carry
    the stamp observed BEFORE the build, so the next request observes a
    MISMATCH and rebuilds. Publishing the newer stamp would make the next
    request MATCH, and it would then serve the stale payload as current —
    permanently, because the match suppresses any rebuild.
    """
    roles = {"results": "results.json"}
    store = tmp_path / "results.json"
    store.write_text("[]", encoding="utf-8")

    def observe() -> StoreStamp:
        return stamp_store(tmp_path, roles)

    def build():
        # The out-of-band write lands while the data is being built.
        store.write_text('[{"m": 1}]', encoding="utf-8")
        return {"n": 1}, "results"

    stamp = observe()          # sampled BEFORE the build
    data, mode = build()
    holder.publish_data("laliga", data, mode, stamp)

    published = holder.read_stamp("laliga")
    assert published == stamp, "the published stamp is not the pre-build one"
    assert published != stamp_store(tmp_path, roles), (
        "the newer stamp was published: a later request would MATCH it and "
        "serve the stale payload as current"
    )

    # The next request observes the newer stamp -> MISMATCH -> it rebuilds.
    stale_stamp = holder.read_stamp("laliga")
    holder.get_or_rebuild("laliga", stamp_store(tmp_path, roles), build)
    assert holder.read_stamp("laliga") != stale_stamp, (
        "the next request did not rebuild: it was served the stale payload"
    )


def test_a_stale_publish_does_not_overwrite_a_newer_snapshot():
    """A late-arriving older publish is refused, not applied.

    The comparison and the assignment happen under the same per-competition
    lock, so the check cannot be raced. This matters because the publish
    path is reachable from more than one thread (a request handler and a
    background run).
    """
    newer = _stamp(200)
    older = _stamp(100)

    holder.publish_data("laliga", {"n": 2}, "results", newer)
    holder.publish_data("laliga", {"n": 1}, "results", older)

    assert holder.read_stamp("laliga") == newer, (
        "a strictly older publish overwrote the newer snapshot"
    )
    assert holder.read_data("laliga")["n"] == 2


def test_a_publish_with_an_unknown_role_is_not_treated_as_older():
    """A deleted or added store is a real change, never a stale observation.

    ``is_strictly_older_than`` must refuse to call a stamp older when the
    two disagree about WHICH roles exist — otherwise a store deletion would
    freeze the published state forever.
    """
    with_results = StoreStamp(entries=(("results", 100, 10),))
    without_results = StoreStamp(entries=(("fixtures", 100, 10),))

    assert not with_results.is_strictly_older_than(without_results)
    assert not without_results.is_strictly_older_than(with_results)
    # Same roles, smaller mtime -> strictly older.
    assert _stamp(100).is_strictly_older_than(_stamp(200))
    assert not _stamp(200).is_strictly_older_than(_stamp(100))
    # Equal mtime is not "strictly older" either.
    assert not _stamp(100).is_strictly_older_than(_stamp(100))


# --------------------------------------------------------------------------
# Gap 2 — the simulation must be retired AT the store write
# --------------------------------------------------------------------------


@pytest.mark.parametrize("comp", COMP_IDS)
def test_refresh_retires_the_simulation_before_publishing_the_new_facts(
        comp, monkeypatch):
    """``clear_sim`` runs BEFORE the new data is published.

    Clearing it after the rebuild left a window in which
    ``GET /api/simulation`` served the previous run while ``GET /api/data``
    served the newly ingested facts. The only intermediate state that is
    honest is (old facts, no simulation).
    """
    recorder = _Recorder()
    # The ingest wrote the stores: the post-ingest stamp differs.
    status = _drive_refresh(comp, monkeypatch, recorder, [_stamp(1), _stamp(2)])
    assert status == 200

    calls = recorder.calls
    assert "clear_sim" in calls, f"the simulation was never retired: {calls}"
    clear_at = calls.index("clear_sim")
    publish_at = calls.index("publish")
    assert clear_at < publish_at, (
        f"the simulation was retired AFTER the new facts were published: {calls}"
    )


@pytest.mark.parametrize("comp", COMP_IDS)
def test_a_refresh_that_writes_nothing_keeps_the_simulation(comp, monkeypatch):
    """D-06 is scoped to a refresh that WROTE the stores.

    A refresh that changed nothing left the derived state untouched, so the
    simulation that was computed from it is still current. Retiring it would
    discard a valid answer for no reason.
    """
    recorder = _Recorder()
    holder.publish_sim(comp, {"status": "completed", "n": 1})

    # The ingest wrote nothing: the stamp is unchanged across the ingest.
    status = _drive_refresh(comp, monkeypatch, recorder, [_stamp(1), _stamp(1)])
    assert status == 200

    assert "clear_sim" not in recorder.calls, (
        f"a no-op refresh retired the simulation: {recorder.calls}"
    )
    assert holder.read_sim(comp).get("status") == "completed"


@pytest.mark.parametrize("comp", COMP_IDS)
def test_the_simulation_is_empty_from_the_moment_the_stores_change(
        comp, monkeypatch):
    """At the instant the new facts are published, no simulation is served."""
    recorder = _Recorder()
    holder.publish_sim(comp, {"status": "completed", "n": 1})

    seen: dict[str, object] = {}

    real_publish = holder.publish_data

    def fake_publish(c, data, mode, stamp):
        # The state a reader observes AT the moment the new facts land.
        seen["sim_at_publish"] = dict(holder.read_sim(c))
        real_publish(c, data, mode, stamp)

    mod = _mod(comp)
    monkeypatch.setattr(mod, "_fetch_live_data", lambda: None)
    pending = [_stamp(1), _stamp(2)]
    monkeypatch.setattr(
        mod, "_observed_stamp",
        lambda: (recorder.stamp(), pending.pop(0))[1])
    monkeypatch.setattr(
        mod, "_build_state",
        lambda: (recorder.build(), ({"n": 1}, "results"))[1])
    monkeypatch.setattr(holder, "publish_data", fake_publish)
    real_clear = holder.clear_sim
    monkeypatch.setattr(
        holder, "clear_sim",
        lambda c: (recorder.clear_sim(), real_clear(c))[1])

    response = mod.api_refresh()
    assert response.status_code == 200
    assert seen["sim_at_publish"] == {}, (
        "a simulation was still served at the moment the new facts were "
        f"published: {seen['sim_at_publish']!r}"
    )
