"""Refresh-endpoint contract (plan 02-06, INGEST-02, CS-2/CS-3).

Proves the three explicit refresh triggers answer with the FULL IngestReport
body — provider, finished counters, ``last_success_at``, OQ7 stage rows and
provenance — in every session mode, and that plain reads stay pure (zero
provider calls). The old opaque ``{"status": "ok", "refreshed": true}`` /
``{"status": "skipped"}`` bodies are unrecoverable here: the status string is
derived FROM the report so it can never contradict it.

Modes covered, for each of worldcup / ucl / laliga:

* explicit offline session (``FOOTBALL_SNAPSHOT=1``) — full schema,
  ``attempted is False``, snapshot disclosure, **zero** provider calls;
* live attempt with a counting provider — ``attempted``/provider/counters/
  stage-row vocabulary present;
* raising provider — truthful failure (``attempted``, non-empty ``error``,
  ``stale``), HTTP 200 because a truthful failure is data, not an HTTP error;
* plain ``GET /api/data`` before any refresh — zero provider calls.

The World Cup success path is additionally driven end-to-end (hermetic
sandboxed store) to pin ``last_success_at`` + the ``results`` stage row on a
real successful HTTP response; UCL's success path needs gitignored runtime
stores this environment does not carry, so its success-shape rules are pinned
at the body-normalization layer (``test_refresh_response_body_is_self_consistent``)
and by ``tests/test_always_on_acquisition.py``.
"""

from __future__ import annotations

import importlib
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from football_core.fetcher import IngestReport

#: Every key ``IngestReport.to_dict`` guarantees — the endpoint body must
#: expose at least this set in EVERY mode (CS-3 / INGEST-02).
REPORT_KEYS = set(
    IngestReport(provider=None, attempted=False, success=False, error=None)
    .to_dict()
)

#: OQ7 stage-row contract (``football_core/fetcher.py`` docstring).
STAGE_ROW_KEYS = {"key", "label", "state", "count", "detail"}
STAGE_STATES = {"ok", "pending", "error", "unavailable"}

#: Counter vocabulary every ``finished`` block must expose (D-14).
COUNTER_KEYS = {
    "received", "normalized", "ingested",
    "skipped_unmatchable", "skipped_no_target", "skipped_missing_score",
}

APPS = [
    pytest.param("worldcup", "wc_app", "wc_app", id="worldcup"),
    pytest.param("ucl", "ucl_app", "ucl_app", id="ucl"),
    pytest.param("laliga", "laliga_app", "laliga_app", id="laliga"),
]


class CountingProvider:
    """Minimal provider that records every fetch call (criterion 2 / T-06-S)."""

    calls = 0
    last_error = None

    def __init__(self, payload=(), raises=None):
        self.payload = list(payload)
        self.raises = raises

    def fetch_matches(self, *args, **kwargs):
        type(self).calls += 1
        if self.raises is not None:
            raise self.raises
        return list(self.payload)


def _sandbox_data_dir(monkeypatch, tmp_path, module, name: str) -> None:
    """Point a competition app at a THROWAWAY copy of its data dir.

    A refresh test must never rewrite the repository's tracked stores: an
    empty-payload ingest still re-serializes ``fixtures.json``/``results.json``
    and would dirty the working tree (observed while writing this file).
    """
    import shutil
    from pathlib import Path

    src = Path(module.DATA_DIR)
    dst = tmp_path / name
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DATA_DIR", dst)


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    """Isolated per-app session: ledgers in tmp, data dirs sandboxed, reports
    reset, auto decision.

    Nothing here may touch the repository's freshness ledger or the tracked
    runtime stores — a contract test must never rewrite the data it inspects.
    """
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.laliga_app as laliga_app
    import web.startup as startup
    import web.ucl_app as ucl_app
    import web.wc_app as wc_app

    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path",
                        lambda: tmp_path / "wc_freshness.json")
    monkeypatch.setattr(ucl_app, "_refresh_report_path",
                        lambda: tmp_path / "ucl_freshness.json")
    monkeypatch.setattr(laliga_app, "_refresh_report_path",
                        lambda: tmp_path / "laliga_freshness.json")
    monkeypatch.setattr(ucl_app, "_refresh_report", {})
    monkeypatch.setattr(ucl_app, "_refresh_reports", {})
    monkeypatch.setattr(ucl_app, "_refresh_reports_seeded", False)
    monkeypatch.setattr(laliga_app, "_refresh_report", {})
    _sandbox_data_dir(monkeypatch, tmp_path, wc_app, "wcdata")
    _sandbox_data_dir(monkeypatch, tmp_path, ucl_app, "ucldata")
    _sandbox_data_dir(monkeypatch, tmp_path, laliga_app, "laligadata")

    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)
    startup.set_session_decision(startup.StartupDecision("auto", ""))
    yield
    startup.set_session_decision(None)


def _client(module_name: str, attr: str) -> TestClient:
    """Bare competition sub-app (no server mount — the contract lives on the app)."""
    module = importlib.import_module(f"web.{module_name}")
    return TestClient(getattr(module, attr))


def _arm(monkeypatch, provider: CountingProvider) -> None:
    """Route every provider lookup at the counting stub (no network)."""
    CountingProvider.calls = 0
    monkeypatch.setattr("football_core.runtime_support.get_data_provider",
                        lambda b, f, l=None: provider)


def _finished_keys(finished: dict) -> set[str]:
    """Counter names across both report layouts: nested WC per-stage blocks
    (``{group_stage, knockout}``) and the flat IngestReport counters."""
    if "group_stage" in finished:
        return set(finished["group_stage"]) | set(finished["knockout"])
    return set(finished)


def _assert_report_shape(body: dict) -> None:
    """The full IngestReport key set plus vocabulary checks every mode shares."""
    missing = REPORT_KEYS - set(body)
    assert not missing, f"response is missing IngestReport keys: {sorted(missing)}"
    assert isinstance(body["attempted"], bool)
    assert isinstance(body["success"], bool)
    assert isinstance(body["stale"], bool)
    assert isinstance(body["finished"], dict)
    assert isinstance(body["stages"], list)
    for row in body["stages"]:
        assert set(row) == STAGE_ROW_KEYS, f"stage row shape drifted: {row!r}"
        assert row["state"] in STAGE_STATES, f"bad stage state: {row!r}"
        assert isinstance(row["count"], int)
    # `status` is derived from the report, so it can never contradict it.
    if body["success"]:
        assert body["status"] == "ok" and body["refreshed"] is True
    elif not body["attempted"]:
        assert body["status"] == "skipped" and body["refreshed"] is False
    else:
        assert body["status"] in {"error", "deferred"}
        assert body["refreshed"] is False
        assert body["deferred"] is (body["status"] == "deferred"), (
            "deferred flag and status must agree:", body["deferred"],
            body["status"], body.get("reason"))
    if body["last_success_at"] is not None:
        assert isinstance(body["last_success_at"], str)
        assert body["last_success_at"].endswith("Z"), (
            "last_success_at must be ISO-8601 UTC with a Z suffix: "
            f"{body['last_success_at']!r}"
        )
        datetime.fromisoformat(body["last_success_at"].replace("Z", "+00:00"))


# ── 1. explicit offline session: full schema, zero network ────────────────


@pytest.mark.parametrize("app_id, module_name, attr", APPS)
def test_snapshot_mode_answers_full_report_with_zero_network(
    app_env, monkeypatch, app_id, module_name, attr,
):
    """FOOTBALL_SNAPSHOT=1 → full report, attempted=False, snapshot disclosed,
    and the provider is NEVER touched — neither by the trigger nor by a read."""
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    _arm(monkeypatch, CountingProvider(payload=[]))

    client = _client(module_name, attr)
    response = client.post("/api/refresh")
    assert response.status_code == 200
    body = response.json()

    _assert_report_shape(body)
    assert body["attempted"] is False
    assert body["success"] is False
    assert body["provider"] is None
    assert "snapshot" in str(
        body.get("skipped_reason") or body.get("reason") or ""
    ), f"offline session must disclose the snapshot reason: {body!r}"
    assert CountingProvider.calls == 0, "snapshot mode must never call a provider"

    # read purity in the same session (criterion 2's page-load clause)
    before = CountingProvider.calls
    assert client.get("/api/data").status_code == 200
    assert CountingProvider.calls == before, "a plain read must not acquire"


# ── 2. live attempt: counters, provider, stage vocabulary ──────────────────


@pytest.mark.parametrize("app_id, module_name, attr", APPS)
def test_explicit_refresh_returns_full_report_with_counters(
    app_env, monkeypatch, app_id, module_name, attr,
):
    """A live attempt reports the provider it used, its finished counters and
    OQ7 stage rows — never a bare status string."""
    _arm(monkeypatch, CountingProvider(payload=[]))

    client = _client(module_name, attr)
    response = client.post("/api/refresh")
    assert response.status_code == 200
    body = response.json()

    _assert_report_shape(body)
    assert body["attempted"] is True, "an explicit trigger must attempt"
    assert body["provider"] == "CountingProvider"
    assert set(_finished_keys(body["finished"])) >= COUNTER_KEYS, body["finished"]
    assert CountingProvider.calls >= 1
    # the two new builders must emit the results row (UCL owns richer rows)
    if app_id in {"worldcup", "laliga"}:
        assert any(row["key"] == "results" for row in body["stages"]), body["stages"]

    # a second read stays pure after the refresh
    before = CountingProvider.calls
    client.get("/api/data")
    assert CountingProvider.calls == before


# ── 3. raising provider: truthful failure, HTTP 200 ────────────────────────


@pytest.mark.parametrize("app_id, module_name, attr", APPS)
def test_raising_provider_answers_truthful_failure(
    app_env, monkeypatch, app_id, module_name, attr,
):
    """Provider explosion → attempted + non-empty error + stale, HTTP 200
    (status-code decision recorded in 02-06-SUMMARY.md)."""
    _arm(monkeypatch, CountingProvider(
        payload=[], raises=RuntimeError("network unreachable")))

    client = _client(module_name, attr)
    response = client.post("/api/refresh")
    assert response.status_code == 200, (
        "a truthful failure is data, not an HTTP error")
    body = response.json()

    _assert_report_shape(body)
    assert body["attempted"] is True
    assert body["success"] is False
    assert body["error"], "a failed attempt must carry its reason"
    assert body["stale"] is True
    assert body["status"] == "error"
    assert body["refreshed"] is False


# ── 4. plain reads are pure (complements plan 02-06 task 1) ────────────────


@pytest.mark.parametrize("app_id, module_name, attr", APPS)
def test_plain_read_before_any_refresh_makes_zero_provider_calls(
    app_env, monkeypatch, app_id, module_name, attr,
):
    """Criterion 2: a page load alone never ingests — the ONLY sanctioned
    trigger is the explicit refresh endpoint."""
    _arm(monkeypatch, CountingProvider(payload=[]))

    client = _client(module_name, attr)
    assert client.get("/api/data").status_code == 200
    assert CountingProvider.calls == 0, (
        "a plain read must not acquire — POST /api/refresh is the only trigger")


# ── 5. World Cup success, end-to-end over HTTP ─────────────────────────────


def test_worldcup_success_body_carries_timestamp_and_results_row(
    app_env, monkeypatch, tmp_path,
):
    """A successful WC refresh over HTTP: ``last_success_at`` in Z form,
    counters, and the results stage row — the shape every competition's
    successful run must expose (CS-3)."""
    from arch_util import StubProvider, patch_wc_offline, recording_provider
    from test_knockout_ingest_chain import bracket_events, seed_empty_wc_dir

    wc_dir = seed_empty_wc_dir(tmp_path / "wc")
    events = bracket_events(wc_dir, ("R16",), seed_r32_winners=True)
    provider = StubProvider(events, competition="WC")
    _, get_data_provider = recording_provider(provider)
    monkeypatch.setattr("football_core.runtime_support.get_data_provider",
                        get_data_provider)
    patch_wc_offline(monkeypatch, tmp_path)

    import web.wc_app as wc_app

    monkeypatch.setattr(wc_app, "DATA_DIR", wc_dir)
    monkeypatch.setattr(wc_app, "_refresh_report_path",
                        lambda: tmp_path / "wc_app_freshness.json")

    response = _client("wc_app", "wc_app").post("/api/refresh")
    assert response.status_code == 200, response.text
    body = response.json()

    _assert_report_shape(body)
    assert body["attempted"] is True
    assert body["success"] is True, body
    assert body["status"] == "ok"
    assert body["provider"], "a successful run names its provider"
    assert body["last_success_at"] and body["last_success_at"].endswith("Z")
    assert set(_finished_keys(body["finished"])) >= COUNTER_KEYS, body["finished"]
    assert body["stages"], "a successful run must publish stage rows"
    assert body["stages"][0]["key"] == "results", body["stages"]
    assert body["stages"][0]["state"] == "ok", body["stages"]


# ── 6. unit-level guarantees for the normalizer itself ─────────────────────


def test_refresh_response_body_is_self_consistent():
    """The body normalizer must guarantee the full key set AND a status that
    always mirrors the report (success / attempted / deferred)."""
    from web.common import refresh_response_body

    # (a) success from an app-level entry: Z normalization + full key set
    body = refresh_response_body({
        "provider": "StubProvider", "attempted": True, "success": True,
        "error": None, "stale": False,
        "last_refresh": "2026-10-08T08:00:00.123456+00:00",
        "stages": [{"key": "results", "label": "Match results", "state": "ok",
                    "count": 3, "detail": "StubProvider"}],
        "n_matches": 3,
    }, mode="results")
    _assert_report_shape(body)
    assert body["last_success_at"] == "2026-10-08T08:00:00.123456Z"
    assert body["status"] == "ok" and body["refreshed"] is True
    assert body["mode"] == "results"
    assert body["n_matches"] == 3, "adapter extras must survive normalization"
    assert set(body) >= REPORT_KEYS

    # (b) configured-but-unpublished provider reads as deferred, not ok
    deferred = refresh_response_body({
        "provider": "StubProvider", "attempted": True, "success": False,
        "error": None, "stale": True, "reason": "deferred/provider-empty",
        "last_refresh": "2026-10-08T08:00:00+00:00",
    })
    _assert_report_shape(deferred)
    assert deferred["status"] == "deferred"
    assert deferred["deferred"] is True

    # (c) nothing attempted → skipped, and never a fabricated timestamp
    skipped = refresh_response_body({"attempted": False, "success": False,
                                     "stale": True})
    _assert_report_shape(skipped)
    assert skipped["status"] == "skipped"
    assert skipped["last_success_at"] is None
    assert skipped["stages"] == [] and skipped["written_files"] == []

    # (d) transport "ok" that ingested nothing must NOT read as success
    empty = refresh_response_body({
        "provider": "StubProvider", "attempted": True, "success": False,
        "error": "no ingestable matches", "stale": True, "status": "ok",
    })
    _assert_report_shape(empty)
    assert empty["status"] == "error", "D-13: the shim follows the verdict"
    assert empty["refreshed"] is False


def test_stage_row_builders_follow_the_report_vocabulary():
    """Both new builders emit exactly the OQ7 row shape, in allowed states."""
    from competitions.laliga.src.pipeline import _results_stage_row as laliga_row
    from competitions.worldcup.src.pipeline import _results_stage_row as wc_row

    for row in (wc_row("ok", 7, "StubProvider"),
                wc_row("error", 0, "provider exploded"),
                laliga_row("ok", 7, "StubProvider"),
                laliga_row("unavailable", 0, "no data provider configured")):
        assert set(row) == STAGE_ROW_KEYS, row
        assert row["state"] in STAGE_STATES, row
        assert row["key"] == "results"
        assert row["label"] == "Match results"
        assert isinstance(row["count"], int)
