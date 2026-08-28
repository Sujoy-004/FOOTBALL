from __future__ import annotations

import json

import arch_util as au


def test_wc_ingestion_never_writes_ucl_data(tmp_path, monkeypatch):
    wc_dir = au.seed_wc_dir(tmp_path / "worldcup" / "data")
    ucl_dir = au.seed_ucl_dir(tmp_path / "ucl" / "data")
    before_ucl = au.snapshot_tree(ucl_dir)

    groups, played, played_groups = au.wc_repo_snapshot()
    stub = au.StubProvider(
        au.wc_events_from_snapshot(groups, played, played_groups),
        competition="WC",
    )
    _, get_data_provider = au.recording_provider(stub)
    leader = au.patch_wc_offline(monkeypatch, tmp_path)
    monkeypatch.setattr("web.common.get_data_provider", get_data_provider)

    from competitions.worldcup.src.pipeline import fetch_live_data

    report = fetch_live_data("", "", wc_dir)

    assert report["success"] is True
    assert report["stale"] is False
    assert report["provider"] == "StubProvider"
    assert au.snapshot_tree(ucl_dir) == before_ucl
    assert json.loads(leader.read_text(encoding="utf-8")).get("worldcup")


def test_ucl_ingestion_never_writes_worldcup_data(tmp_path, monkeypatch):
    wc_dir = au.seed_wc_dir(tmp_path / "worldcup" / "data")
    ucl_dir = au.seed_ucl_dir(
        tmp_path / "ucl" / "data", results={"matches": []}, knockout=False
    )
    before_wc = au.snapshot_tree(wc_dir)

    stub = au.StubProvider(au.ucl_league_events(ucl_dir, n=4), competition="CL")

    from competitions.ucl.src.pipeline import fetch_live_data

    summary = fetch_live_data(ucl_dir, "", "", provider=stub)

    assert summary["status"] == "ok"
    results = json.loads((ucl_dir / "results.json").read_text(encoding="utf-8"))
    assert len(results["matches"]) == 4
    assert au.snapshot_tree(wc_dir) == before_wc


def test_web_refresh_boundaries_are_per_competition(tmp_path, monkeypatch):
    from web import ucl_app, wc_app

    wc_dir = au.seed_wc_dir(tmp_path / "worldcup" / "data")
    ucl_dir = au.seed_ucl_dir(tmp_path / "ucl" / "data")
    before_wc = au.snapshot_tree(wc_dir)
    before_ucl = au.snapshot_tree(ucl_dir)

    wc_cache_saved = au.snapshot_cache_state(wc_app)
    ucl_cache_saved = au.snapshot_cache_state(ucl_app)
    ucl_report_saved = dict(ucl_app._refresh_report)
    try:
        wc_app.cache.clear()
        ucl_app.cache.clear()

        groups, played, played_groups = au.wc_repo_snapshot()
        wc_leader = au.patch_wc_offline(monkeypatch, tmp_path)
        monkeypatch.setattr("web.startup.is_snapshot_mode", lambda: False)

        wc_stub = au.StubProvider(
            au.wc_events_from_snapshot(groups, played, played_groups),
            competition="WC",
        )
        wc_calls, wc_gp = au.recording_provider(wc_stub)
        monkeypatch.setattr("web.common.get_data_provider", wc_gp)
        monkeypatch.setattr(wc_app, "DATA_DIR", wc_dir)
        monkeypatch.setattr(wc_app, "BSD_API_KEY", "")
        monkeypatch.setattr(wc_app, "FOOTBALL_DATA_ORG_KEY", "")

        wc_report = wc_app._fetch_live_data()
        assert wc_report["success"] is True
        assert wc_calls == [27]
        assert json.loads(wc_leader.read_text(encoding="utf-8")).get("worldcup")
        assert wc_app.cache.get("refresh", {}).get("success") is True
        assert ucl_app.cache == {}
        assert au.snapshot_tree(ucl_dir) == before_ucl

        wc_after_wc_refresh = au.snapshot_tree(wc_dir)

        ucl_leader = tmp_path / "ucl_freshness.json"
        ucl_stub = au.StubProvider(au.ucl_league_events(ucl_dir, n=4), competition="CL")
        ucl_calls, ucl_gp = au.recording_provider(ucl_stub)
        monkeypatch.setattr("web.common.get_data_provider", ucl_gp)
        monkeypatch.setattr(ucl_app, "DATA_DIR", ucl_dir)
        monkeypatch.setattr(ucl_app, "_refresh_report_path", lambda: ucl_leader)
        monkeypatch.setattr(
            ucl_app, "_maybe_recompute_cache_after_ingest", lambda summary: None
        )
        monkeypatch.setattr(ucl_app, "_refresh_report", {})

        ucl_app._fetch_live_data()
        assert ucl_calls == [7]
        ucl_ledger = json.loads(ucl_leader.read_text(encoding="utf-8"))
        assert ucl_ledger.get("ucl", {}).get("success") is not False
        assert wc_app.cache.get("refresh", {}).get("success") is True
        assert au.snapshot_tree(wc_dir) == wc_after_wc_refresh
    finally:
        au.restore_cache_state(wc_app, wc_cache_saved)
        au.restore_cache_state(ucl_app, ucl_cache_saved)
        ucl_app._refresh_report = ucl_report_saved


def test_app_data_dirs_and_ledger_keys_are_competition_scoped(tmp_path):
    from web import ucl_app, wc_app
    from competitions.worldcup.src import constants

    assert wc_app.DATA_DIR == constants.DATA_DIR
    assert wc_app.DATA_DIR != ucl_app.DATA_DIR
    assert str(wc_app.DATA_DIR).replace("\\", "/").endswith("competitions/worldcup/data")
    assert str(ucl_app.DATA_DIR).replace("\\", "/").endswith("competitions/ucl/data")
    assert constants.DEFAULT_LEAGUE_ID != ucl_app.UCL_LEAGUE_ID

    shared = tmp_path / "last_refresh.json"
    shared.write_text(
        json.dumps({"worldcup": {"k": "wc"}, "ucl": {"k": "ucl"}}),
        encoding="utf-8",
    )
    data = json.loads(shared.read_text(encoding="utf-8"))
    assert set(data) == {"worldcup", "ucl"}