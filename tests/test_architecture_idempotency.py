from __future__ import annotations

import json

import arch_util as au


def _no_boot(data: dict) -> dict:
    out = dict(data)
    out.pop("boot", None)
    return out


def _wc_run(wc_dir, groups, played, played_groups, monkeypatch, tmp_path):
    stub = au.StubProvider(
        au.wc_events_from_snapshot(groups, played, played_groups), competition="WC"
    )
    _, get_data_provider = au.recording_provider(stub)
    au.patch_wc_offline(monkeypatch, tmp_path)
    monkeypatch.setattr("web.common.get_data_provider", get_data_provider)
    from competitions.worldcup.src.pipeline import fetch_live_data

    return fetch_live_data("", "", wc_dir)


def test_wc_end_to_end_ingestion_is_idempotent(tmp_path, monkeypatch):
    wc_dir = au.seed_wc_dir(tmp_path / "wc")
    au.drift_wc_store(wc_dir, ko={"M76": (3, 1)}, group={"GS_A_01": (2, 1)})
    groups, played, played_groups = au.wc_repo_snapshot()

    report1 = _wc_run(wc_dir, groups, played, played_groups, monkeypatch, tmp_path)
    assert report1["success"] is True
    played1 = json.loads((wc_dir / "played.json").read_text(encoding="utf-8"))
    groups1 = json.loads(
        (wc_dir / "played_groups.json").read_text(encoding="utf-8")
    )
    assert (played1["M76"]["home_score"], played1["M76"]["away_score"]) == (2, 1)
    assert (groups1["GS_A_01"]["home_score"], groups1["GS_A_01"]["away_score"]) == (2, 0)

    ko_bytes_after_1 = (wc_dir / "played.json").read_bytes()
    grp_bytes_after_1 = (wc_dir / "played_groups.json").read_bytes()

    report2 = _wc_run(wc_dir, groups, played, played_groups, monkeypatch, tmp_path)
    assert report2["success"] is True
    assert report2["stale"] is False
    assert (wc_dir / "played.json").read_bytes() == ko_bytes_after_1
    assert (wc_dir / "played_groups.json").read_bytes() == grp_bytes_after_1

    from web import wc_app

    cache_saved = au.snapshot_cache_state(wc_app)
    try:
        monkeypatch.setattr(wc_app, "DATA_DIR", wc_dir)
        monkeypatch.setattr(wc_app, "compute_signals_meta", lambda: {"signals": [], "n_total": 0})
        wc_app.cache.clear()
        overview_after_1 = dict(wc_app.compute_overview())
        wc_app.cache.update(overview_after_1)
        api_after_1 = wc_app.api_data().body
        overview_after_2 = dict(wc_app.compute_overview())
        wc_app.cache.update(overview_after_2)
        api_after_2 = wc_app.api_data().body
        assert _no_boot(overview_after_1) == _no_boot(overview_after_2)
        assert api_after_1 == api_after_2
    finally:
        au.restore_cache_state(wc_app, cache_saved)


def test_ucl_end_to_end_ingestion_is_idempotent(tmp_path, monkeypatch):
    ucl_dir = au.seed_ucl_dir(
        tmp_path / "ucl", results={"matches": []}, knockout=False
    )
    events = au.ucl_league_events(ucl_dir, n=4)

    from competitions.ucl.src.pipeline import fetch_live_data

    def _run():
        stub = au.StubProvider(events, competition="CL")
        return fetch_live_data(ucl_dir, "", "", provider=stub)

    summary1 = _run()
    assert summary1["status"] == "ok"
    results1 = json.loads((ucl_dir / "results.json").read_text(encoding="utf-8"))
    assert len(results1["matches"]) == 4
    assert len({m["match_id"] for m in results1["matches"]}) == 4
    assert (ucl_dir / "knockout_results.json").exists()

    results_bytes_after_1 = (ucl_dir / "results.json").read_bytes()
    ko_bytes_after_1 = (ucl_dir / "knockout_results.json").read_bytes()

    summary2 = _run()
    assert summary2["status"] == "ok"
    assert summary2["n_updated"] == 0
    assert summary2["report"]["written_files"] == []
    assert (ucl_dir / "results.json").read_bytes() == results_bytes_after_1
    assert (ucl_dir / "knockout_results.json").read_bytes() == ko_bytes_after_1
    results2 = json.loads((ucl_dir / "results.json").read_text(encoding="utf-8"))
    assert len(results2["matches"]) == 4

    from competitions.ucl.src.state import build_competition_state

    state1 = build_competition_state(str(ucl_dir), mode="results")
    state2 = build_competition_state(str(ucl_dir), mode="results")
    assert state1 == state2
    assert state1.get("phase", {}).get("progress", {}).get("played") == 4

    from web import ucl_app

    ucl_cache_saved = au.snapshot_cache_state(ucl_app)
    try:
        monkeypatch.setattr(ucl_app, "DATA_DIR", ucl_dir)
        assert ucl_app._match_counts() == (ucl_app._match_counts())
    finally:
        au.restore_cache_state(ucl_app, ucl_cache_saved)