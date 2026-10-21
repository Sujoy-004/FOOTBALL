"""Publication-generation consistency for the derived-state holder.

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


def test_publishing_an_older_stamp_is_allowed():
    """An older-stamped publish is allowed — and that is deliberate.

    A stamp says which store generation was observed; it cannot say whether
    the DATA that accompanies it is stale. Refusing an older-stamped publish
    would therefore refuse legitimate work — a test installing a scenario at
    the current disk generation, or a concurrent publish that sampled its
    stamp a moment earlier — in order to prevent a problem (one redundant
    rebuild) that no reader can observe. The dangerous pair is (older data,
    NEWER stamp), and only the sample-before-build ORDER rules that out.

    This test exists so the decision is explicit: if someone re-adds a
    stamp-regression refusal, this fails and the reasoning has to be
    revisited.
    """
    holder.publish_data("laliga", {"n": 2}, "results", _stamp(200))
    holder.publish_data("laliga", {"n": 1}, "results", _stamp(100))

    assert holder.read_stamp("laliga") == _stamp(100)
    assert holder.read_data("laliga")["n"] == 1
    # The next request observes a MISMATCH and rebuilds — the older stamp is
    # detectable, so the stale payload is never served as current.
    rebuilt = holder.get_or_rebuild("laliga", _stamp(200), lambda: ({"n": 9}, "results"))
    assert rebuilt["n"] == 9
    assert holder.read_stamp("laliga") == _stamp(200)


def test_publishing_without_a_stamp_neither_crashes_nor_poisons_the_slot():
    """A snapshot published with no stamp must not break later publishes.

    ``tests/arch_util.py::restore_cache_state`` publishes with
    ``holder.read_stamp(comp)``, which is ``None`` when the competition was
    never published. A publish must accept that (a snapshot with no
    freshness information simply never matches, so the next request
    rebuilds) and must not make every LATER publish fail.
    """
    holder.publish_data("laliga", {"n": 1}, "results", None)
    assert holder.read_stamp("laliga") is None
    assert holder.read_data("laliga")["n"] == 1

    # A later publish with a real stamp must still land.
    holder.publish_data("laliga", {"n": 2}, "results", _stamp(200))
    assert holder.read_stamp("laliga") == _stamp(200)
    assert holder.read_data("laliga")["n"] == 2


def test_the_wc_ingest_hook_retires_the_simulation_before_it_publishes(monkeypatch):
    """The WC hook publishes the new facts itself, so it retires the sim HERE.

    ``web/wc_app.py::_fetch_live_data`` calls ``_publish_snapshot`` — the
    new facts are published from inside the ingest hook, BEFORE the
    endpoint's own ``clear_sim`` runs. The hook must therefore retire the
    simulation at the store write, or there is a window in which
    ``GET /api/simulation`` serves the previous run next to the new facts.
    """
    import competitions.worldcup.src.pipeline as pipeline
    import web.wc_app as wc_app

    recorder = _Recorder()
    holder.publish_sim("worldcup", {"status": "completed", "n": 1})
    seen: dict[str, object] = {}

    # before-the-ingest, after-the-ingest, and the publish's own sample
    stamps = [_stamp(1), _stamp(2), _stamp(2)]
    monkeypatch.setattr(
        wc_app, "_observed_stamp",
        lambda: (recorder.stamp(), stamps.pop(0))[1])
    monkeypatch.setattr(
        wc_app, "_build_state",
        lambda: (recorder.build(), ({"n": 1}, "results"))[1])
    monkeypatch.setattr(
        pipeline, "fetch_live_data",
        lambda *a, **k: {"provider": "stub", "attempted": True, "success": True,
                         "stale": False, "finished": {}, "stages": []})

    real_publish = holder.publish_data
    real_clear = holder.clear_sim

    def fake_publish(c, data, mode, stamp):
        seen["sim_at_publish"] = dict(holder.read_sim(c))
        recorder.publish()
        real_publish(c, data, mode, stamp)

    def fake_clear(c):
        recorder.clear_sim()
        real_clear(c)

    monkeypatch.setattr(holder, "publish_data", fake_publish)
    monkeypatch.setattr(holder, "clear_sim", fake_clear)

    wc_app._fetch_live_data()

    assert seen["sim_at_publish"] == {}, (
        "the WC ingest hook published the new facts while the previous "
        f"simulation was still served: {seen['sim_at_publish']!r}"
    )
    assert recorder.calls.index("clear_sim") < recorder.calls.index("publish")


def test_the_ucl_ingest_hook_retires_the_simulation_before_it_publishes(monkeypatch):
    """The UCL hook may publish the new facts itself — so it retires the sim.

    ``web/ucl_app.py::_fetch_live_data`` calls
    ``_maybe_recompute_cache_after_ingest``, which rebuilds and publishes.
    The simulation must be retired at the store write, before that publish.
    """
    import competitions.ucl.src.pipeline as pipeline
    import web.ucl_app as ucl_app

    recorder = _Recorder()
    holder.publish_sim("ucl", {"status": "completed", "n": 1})
    seen: dict[str, object] = {}

    stamps = [_stamp(1), _stamp(2), _stamp(2)]
    monkeypatch.setattr(
        ucl_app, "_observed_stamp",
        lambda: (recorder.stamp(), stamps.pop(0))[1])
    monkeypatch.setattr(
        ucl_app, "_build_state",
        lambda: (recorder.build(), ({"n": 1}, "results"))[1])
    monkeypatch.setattr(
        ucl_app, "_maybe_recompute_cache_after_ingest",
        lambda summary: holder.publish_data("ucl", {"n": 1}, "results", _stamp(2)))
    monkeypatch.setattr(
        pipeline, "fetch_live_data",
        lambda *a, **k: {"report": {"success": True, "finished": {}},
                         "status": "ok", "provider_name": "stub",
                         "n_raw": 1, "n_updated": 1, "per_season": {}})

    real_publish = holder.publish_data
    real_clear = holder.clear_sim

    def fake_publish(c, data, mode, stamp):
        seen.setdefault("sim_at_publish", dict(holder.read_sim(c)))
        recorder.publish()
        real_publish(c, data, mode, stamp)

    def fake_clear(c):
        recorder.clear_sim()
        real_clear(c)

    monkeypatch.setattr(holder, "publish_data", fake_publish)
    monkeypatch.setattr(holder, "clear_sim", fake_clear)

    ucl_app._fetch_live_data()

    assert seen.get("sim_at_publish") == {}, (
        "the UCL ingest hook published the new facts while the previous "
        f"simulation was still served: {seen.get('sim_at_publish')!r}"
    )
    assert recorder.calls.index("clear_sim") < recorder.calls.index("publish")


def test_the_laliga_ingest_hook_retires_the_simulation_before_it_publishes(monkeypatch):
    """The LaLiga hook publishes the new facts itself — so it retires the sim.

    ``web/laliga_app.py::_fetch_live_data`` calls ``_recompute_cache``,
    which rebuilds and publishes. The simulation must be retired at the
    store write, before that publish.
    """
    import competitions.laliga.src.pipeline as pipeline
    import web.laliga_app as laliga_app

    recorder = _Recorder()
    holder.publish_sim("laliga", {"status": "completed", "n": 1})
    seen: dict[str, object] = {}

    stamps = [_stamp(1), _stamp(2), _stamp(2)]
    monkeypatch.setattr(
        laliga_app, "_observed_stamp",
        lambda: (recorder.stamp(), stamps.pop(0))[1])
    monkeypatch.setattr(
        laliga_app, "compute_all",
        lambda: {"n": 1, "mode": "results"})

    real_publish = holder.publish_data
    real_clear = holder.clear_sim

    def fake_publish(c, data, mode, stamp):
        seen.setdefault("sim_at_publish", dict(holder.read_sim(c)))
        recorder.publish()
        real_publish(c, data, mode, stamp)

    def fake_clear(c):
        recorder.clear_sim()
        real_clear(c)

    monkeypatch.setattr(holder, "publish_data", fake_publish)
    monkeypatch.setattr(holder, "clear_sim", fake_clear)

    def fake_brain_fetch(*a, **k):
        return {"report": {"success": True, "finished": {}},
                "status": "ok", "provider_name": "stub",
                "n_raw": 1, "n_updated": 1, "odds": {}}

    monkeypatch.setattr(pipeline, "fetch_live_data", fake_brain_fetch)
    monkeypatch.setattr(
        laliga_app, "_brain_fetch", fake_brain_fetch, raising=False)
    # The app imports the brain fetch under a local alias; patch the module
    # attribute the app actually calls.
    monkeypatch.setattr(
        laliga_app, "_fetch_live_data", laliga_app._fetch_live_data)
    monkeypatch.setattr(
        laliga_app, "get_data_provider", lambda *a, **k: object(), raising=False)

    laliga_app._fetch_live_data()

    assert seen.get("sim_at_publish") == {}, (
        "the LaLiga ingest hook published the new facts while the previous "
        f"simulation was still served: {seen.get('sim_at_publish')!r}"
    )
    assert recorder.calls.index("clear_sim") < recorder.calls.index("publish")


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
