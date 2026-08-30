from pathlib import Path


def test_ucl_default_bootstrap_creates_pointer_without_touching_historical(tmp_path, monkeypatch):
    from competitions.ucl.src.season_draw import ensure_draw_season
    from competitions.ucl.src.seasons import get_current_season

    data_dir = tmp_path / "ucl" / "data"
    source = Path("competitions/ucl/data")
    data_dir.mkdir(parents=True)
    (data_dir / "draws").mkdir()
    snapshot = source / "draws" / "2026_27_league_draw.json"
    (data_dir / "draws" / snapshot.name).write_bytes(snapshot.read_bytes())

    # This mirrors the server helper's contract without binding a test app.
    assert get_current_season(data_dir) is None
    summary = ensure_draw_season(data_dir)
    assert summary["season"] == "2026/27"
    pointer = get_current_season(data_dir)
    assert pointer and pointer["season"] == "2026/27"
