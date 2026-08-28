from __future__ import annotations

import json

import arch_util as au


def _wc_run(wc_dir, group_events, ko_events, monkeypatch, tmp_path):
    stub = au.StubProvider(
        group_events + ko_events, competition="WC"
    )
    _, get_data_provider = au.recording_provider(stub)
    au.patch_wc_offline(monkeypatch, tmp_path)
    monkeypatch.setattr("web.common.get_data_provider", get_data_provider)
    from competitions.worldcup.src.pipeline import fetch_live_data

    return fetch_live_data("", "", wc_dir)


def test_wc_provider_exception_preserves_stores_and_reports_stale(
    tmp_path, monkeypatch
):
    wc_dir = au.seed_wc_dir(tmp_path / "wc")
    before_files = au.snapshot_tree(wc_dir)

    stub = au.StubProvider(raises=RuntimeError("provider crash"))
    _, get_data_provider = au.recording_provider(stub)
    leader = au.patch_wc_offline(monkeypatch, tmp_path)
    monkeypatch.setattr("web.common.get_data_provider", get_data_provider)

    from competitions.worldcup.src.pipeline import fetch_live_data

    report = fetch_live_data("", "", wc_dir)
    assert report["success"] is False
    assert report["stale"] is True
    assert "match fetch failed" in report["error"]
    assert au.snapshot_tree(wc_dir) == before_files

    from web import wc_app

    cache_saved = au.snapshot_cache_state(wc_app)
    try:
        monkeypatch.setattr(wc_app, "DATA_DIR", wc_dir)
        monkeypatch.setattr(
            wc_app, "compute_signals_meta", lambda: {"signals": [], "n_total": 0}
        )
        wc_app.cache.clear()
        overview = wc_app.compute_overview()
        assert isinstance(overview, dict) and overview.get("n_played", 0) >= 0
        assert "error" not in overview
    finally:
        au.restore_cache_state(wc_app, cache_saved)
    assert json.loads(leader.read_text(encoding="utf-8")).get("worldcup", {}).get(
        "success"
    ) is False


def test_wc_provider_empty_preserves_stores(tmp_path, monkeypatch):
    wc_dir = au.seed_wc_dir(tmp_path / "wc")
    before = au.snapshot_tree(wc_dir)

    groups, played, played_groups = au.wc_repo_snapshot()
    report = _wc_run(wc_dir, [], [], monkeypatch, tmp_path)
    assert report["success"] is False
    assert report["stale"] is True
    assert "no matches" in report["error"]
    assert au.snapshot_tree(wc_dir) == before


def test_wc_stale_undecided_provider_cannot_wipe_penalty_decisions(
    tmp_path, monkeypatch
):
    wc_dir = au.seed_wc_dir(tmp_path / "wc")
    before = au.snapshot_tree(wc_dir)
    groups, played, played_groups = au.wc_repo_snapshot()
    pk = [m for m in played.values()
          if m["home_score"] == m["away_score"] and not m.get("is_draw")]
    assert len(pk) == 4
    stale_events = []
    for entry in pk:
        stale_events.append({
            "id": entry["match_id"],
            "match_id": entry["match_id"],
            "status": "finished",
            "home_team": entry["team_a"],
            "away_team": entry["team_b"],
            "home_score": entry["home_score"],
            "away_score": entry["away_score"],
            "event_date": entry.get("completed_at") or "",
        })
    group_events = [
        ev for ev in au.wc_events_from_snapshot(groups, played, played_groups)
        if ev.get("group_name")
    ]
    ko_events = [
        ev for ev in au.wc_events_from_snapshot(groups, played, played_groups)
        if not ev.get("group_name")
    ]
    ko_events = [ev for ev in ko_events if ev["match_id"] not in {e["match_id"] for e in stale_events}]
    report = _wc_run(wc_dir, group_events, ko_events + stale_events, monkeypatch, tmp_path)
    assert report["success"] is True

    after = json.loads((wc_dir / "played.json").read_text(encoding="utf-8"))
    for entry in pk:
        assert after[entry["match_id"]]["winner"] == entry["winner"]
        assert after[entry["match_id"]]["is_draw"] is False
    assert (wc_dir / "played.json").read_bytes() == before["played.json"]
    assert (
        wc_dir / "played_groups.json"
    ).read_bytes() == before["played_groups.json"]


def test_ucl_provider_empty_reports_stale_and_preserves_stores(tmp_path):
    ucl_dir = au.seed_ucl_dir(tmp_path / "ucl")
    before = au.snapshot_tree(ucl_dir)
    stub = au.StubProvider([], competition="CL")

    from competitions.ucl.src.pipeline import fetch_live_data

    summary = fetch_live_data(ucl_dir, "", "", provider=stub)
    assert summary["status"] == "skip"
    assert summary["report"]["success"] is False
    assert summary["report"]["stale"] is True
    assert au.snapshot_tree(ucl_dir) == before


def test_ucl_provider_exception_preserves_stores(tmp_path):
    ucl_dir = au.seed_ucl_dir(tmp_path / "ucl")
    before = au.snapshot_tree(ucl_dir)
    stub = au.StubProvider(raises=RuntimeError("provider crash"), competition="CL")

    from competitions.ucl.src.pipeline import fetch_live_data

    try:
        fetch_live_data(ucl_dir, "", "", provider=stub)
    except RuntimeError as exc:
        assert "provider crash" in str(exc)
    else:
        raise AssertionError("brain fetch_live_data must surface a raising provider")
    assert au.snapshot_tree(ucl_dir) == before


def test_ucl_stale_undecided_final_cannot_wipe_decided_tie(tmp_path):
    ucl_dir = au.seed_ucl_dir(tmp_path / "ucl")
    before_ko = (ucl_dir / "knockout_results.json").read_bytes()
    knockout = json.loads((ucl_dir / "knockout_results.json").read_text(encoding="utf-8"))
    final = knockout["matches"]["final"][0]
    assert final.get("winner")

    from competitions.ucl.src.pipeline import fetch_live_data

    stale_events = au.ucl_final_event(knockout, decided=False)
    stub = au.StubProvider(stale_events, competition="CL")
    summary = fetch_live_data(ucl_dir, "", "", provider=stub)
    assert summary["status"] == "ok"

    after = json.loads(
        (ucl_dir / "knockout_results.json").read_text(encoding="utf-8")
    )
    assert after["matches"]["final"][0]["winner"] == final["winner"]
    assert (ucl_dir / "knockout_results.json").read_bytes() == before_ko

    from competitions.ucl.src.state import build_competition_state

    state = build_competition_state(str(ucl_dir), mode="results")
    assert state.get("phase")
    assert state.get("champion") or state.get("phase")


def test_ucl_web_raising_provider_records_stale_in_ledger(tmp_path, monkeypatch):
    import web.startup
    from web import ucl_app

    ucl_dir = au.seed_ucl_dir(tmp_path / "ucl")
    before = au.snapshot_tree(ucl_dir)
    leader = tmp_path / "ucl_freshness.json"

    stub = au.StubProvider(raises=RuntimeError("provider crash"), competition="CL")
    _, get_data_provider = au.recording_provider(stub)
    monkeypatch.setattr(web.startup, "is_snapshot_mode", lambda: False)
    monkeypatch.setattr("web.common.get_data_provider", get_data_provider)
    monkeypatch.setattr(ucl_app, "DATA_DIR", ucl_dir)
    monkeypatch.setattr(ucl_app, "_refresh_report_path", lambda: leader)

    ucl_app._fetch_live_data()

    assert au.snapshot_tree(ucl_dir) == before
    ledger = json.loads(leader.read_text(encoding="utf-8"))
    entry = ledger.get("ucl", {})
    assert entry.get("stale") is True


def test_wc_web_raising_provider_records_stale_in_ledger(tmp_path, monkeypatch):
    from web import wc_app

    wc_dir = au.seed_wc_dir(tmp_path / "wc")
    before = au.snapshot_tree(wc_dir)
    stub = au.StubProvider(raises=RuntimeError("provider crash"), competition="WC")
    _, get_data_provider = au.recording_provider(stub)
    leader = au.patch_wc_offline(monkeypatch, tmp_path)
    monkeypatch.setattr("web.common.get_data_provider", get_data_provider)
    cache_saved = au.snapshot_cache_state(wc_app)
    try:
        wc_app.cache.clear()
        report = wc_app._fetch_live_data()
        assert report["success"] is False
        assert report["stale"] is True
    finally:
        au.restore_cache_state(wc_app, cache_saved)
    assert au.snapshot_tree(wc_dir) == before
    ledger = json.loads(leader.read_text(encoding="utf-8"))
    assert ledger.get("worldcup", {}).get("stale") is True