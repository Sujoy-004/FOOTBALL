"""Tests for the main polling loop and shutdown behavior (Phase 4)."""

import os
import signal
import subprocess
import threading

import pytest
import sys
import time
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = MAIN_DIR / "data"


def _runner_code(data_dir=None) -> str:
    """Inline Python that mocks requests.get + run_full_simulation, sets POLL_INTERVAL=1, then calls main.main()."""
    data_override = ""
    if data_dir is not None:
        data_override = (
            f"import src.constants\n"
            f"src.constants.DATA_DIR = {str(data_dir)!r}\n"
            f"import importlib\n"
            f"import src.state\n"
            f"importlib.reload(src.state)\n"
        )
    return (
        f"import os, sys\n"
        f"os.environ['POLL_INTERVAL'] = '1'\n"
        f"os.environ['BSD_API_KEY'] = 'test_dummy_key'\n"
        f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
        f"os.chdir({str(MAIN_DIR)!r})\n"
        f"{data_override}"
        f"import requests\n"
        f"import src.constants\n"
        f"src.constants.API_TIMEOUT = 1\n"
        f"class _MockResp:\n"
        f"  status_code=200\n"
        f"  text = ''  # eloratings TSV: empty/mock is fine — sync handles gracefully\n"
        f"  def json(self):\n"
        f"    return {{}}\n"
        f"  def raise_for_status(self):\n"
        f"    pass\n"
        f"  @property\n"
        f"  def ok(self):\n"
        f"    return True\n"
        f"requests.get = lambda url, **kw: _MockResp()\n"
        f"import src.knockout\n"
        f"def _mock_sim(*args, **kwargs):\n"
        f"    teams = args[0] if args else kwargs.get('teams', {{}})\n"
        f"    return {{name: {{'qf': 0.5, 'sf': 0.3, 'final': 0.1, 'champion': 0.05}} for name in teams}}\n"
        f"src.knockout.run_full_simulation = _mock_sim\n"
        f"import main\n"
        f"main.run_full_simulation = _mock_sim\n"
        f"main.main()\n"
     )


def _runner_code_with_flag(flag: str, data_dir=None) -> str:
    """Inline Python that mocks requests.get + run_full_simulation, passes `flag` as CLI arg, then calls main.main()."""
    data_override = ""
    if data_dir is not None:
        data_override = (
            f"import src.constants\n"
            f"src.constants.DATA_DIR = {str(data_dir)!r}\n"
            f"import importlib\n"
            f"import src.state\n"
            f"importlib.reload(src.state)\n"
        )
    return (
         f"import os, sys\n"
         f"os.environ['POLL_INTERVAL'] = '1'\n"
         f"os.environ['BSD_API_KEY'] = 'test_dummy_key'\n"
         f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
         f"os.chdir({str(MAIN_DIR)!r})\n"
         f"sys.argv = ['main.py', {flag!r}]\n"
         f"{data_override}"
         f"import requests\n"
         f"import src.constants\n"
         f"src.constants.API_TIMEOUT = 1\n"
        f"class _MockResp:\n"
        f"  status_code=200\n"
        f"  text = ''  # eloratings TSV: empty/mock is fine — sync handles gracefully\n"
        f"  def json(self):\n"
        f"    return {{}}\n"
        f"  def raise_for_status(self):\n"
        f"    pass\n"
        f"  @property\n"
        f"  def ok(self):\n"
        f"    return True\n"
        f"requests.get = lambda url, **kw: _MockResp()\n"
        f"import src.knockout\n"
        f"def _mock_sim(*args, **kwargs):\n"
        f"    teams = args[0] if args else kwargs.get('teams', {{}})\n"
        f"    return {{name: {{'qf': 0.5, 'sf': 0.3, 'final': 0.1, 'champion': 0.05}} for name in teams}}\n"
        f"src.knockout.run_full_simulation = _mock_sim\n"
        f"import main\n"
        f"main.run_full_simulation = _mock_sim\n"
        f"main.main()\n"
    )


def test_once_flag_runs_single_cycle(tmp_path):
    """--once runs a single fetch->simulate->print cycle, then exits (no polling loop)."""
    import shutil
    src_dir = MAIN_DIR / "data"
    for f in ["teams.json", "groups.json", "bracket.json", "annex_c.json", "played.json", "team_aliases.json"]:
        shutil.copy2(src_dir / f, tmp_path / f)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", _runner_code_with_flag("--once", data_dir=tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        assert False, (
            f"--once should exit within 10s, did not. "
            f"stdout={stdout!r} stderr={stderr!r}"
        )
    # --once should exit cleanly (code 0)
    assert proc.returncode == 0, (
        f"--once should exit code 0, got {proc.returncode}. "
        f"stdout={stdout!r} stderr={stderr!r}"
    )
    # Must contain simulation output (confirms sim ran)
    assert "UPDATED PROBABILITIES" in stdout or "Initial probabilities" in stdout, (
        f"--once must print probability output. stdout={stdout!r}"
    )
    # Must NOT contain more than 1 "Polling..." heartbeat (confirms single _run_iteration call, no loop)
    heartbeat_count = stdout.count("Polling...")
    assert heartbeat_count <= 1, (
        f"--once should have at most 1 heartbeat, got {heartbeat_count}. stdout={stdout!r}"
    )


def test_main_loop_runs_iterations(tmp_path):
    """Loop should run multiple fetch cycles when poll interval is short.

    Each cycle prints 'Polling...' heartbeat when no new matches.
    """
    import shutil
    src_dir = MAIN_DIR / "data"
    for f in ["teams.json", "groups.json", "bracket.json", "annex_c.json", "played.json", "team_aliases.json"]:
        shutil.copy2(src_dir / f, tmp_path / f)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", _runner_code(data_dir=tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
    assert stdout.count("Polling") >= 2, (
        f"Expected >=2 'Polling' lines, got {stdout.count('Polling')}: {stdout!r}"
    )


def test_main_loop_clean_shutdown(tmp_path):
    """Ctrl+C should print final probabilities banner before exit."""
    import shutil
    src_dir = MAIN_DIR / "data"
    for f in ["teams.json", "groups.json", "bracket.json", "annex_c.json", "played.json", "team_aliases.json"]:
        shutil.copy2(src_dir / f, tmp_path / f)
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", _runner_code(data_dir=tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        **kwargs,
    )
    # Read stdout in background thread to avoid blocking
    stdout_lines = []
    def _reader():
        try:
            for line in iter(proc.stdout.readline, ''):
                stdout_lines.append(line)
        except ValueError:
            pass
    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    # Wait for first iteration's heartbeat before sending shutdown signal
    start = time.time()
    while time.time() - start < 10:
        time.sleep(0.1)
        if any("Polling" in line for line in stdout_lines):
            break
    sig = signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT
    try:
        proc.send_signal(sig)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    reader.join(timeout=2)
    stdout = ''.join(stdout_lines)
    assert "FINAL CHAMPIONSHIP PROBABILITIES" in stdout, (
        f"Missing shutdown banner: {stdout!r}"
    )


def test_hourly_resim_triggers(monkeypatch):
    """When >3600s since last_sim_time, hourly re-sim runs without API call."""
    import time as time_module
    import main as main_mod

    fake_time = [5000.0]

    def mock_time():
        return fake_time[0]

    monkeypatch.setattr(time_module, "time", mock_time)

    def mock_sim(*args, **kwargs):
        teams = args[0] if args else kwargs.get("teams", {})
        return {name: {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.05} for name in teams}
    import src.knockout
    monkeypatch.setattr(src.knockout, "run_full_simulation", mock_sim)
    monkeypatch.setattr(main_mod, "run_full_simulation", mock_sim)

    teams = {"Arg": {"elo": 2000}, "Bra": {"elo": 2000}}
    groups = {"groups": {"A": {"teams": ["Arg", "Bra"], "matches": []}}}
    bracket = [
        {"match_id": "F", "round": "FINAL", "source_matches": ["SF_1", "SF_2"], "winner": None},
    ]
    annex_c = {"_meta": {"source": "test"}}
    played = {}
    played_groups = {}
    last_sim_time = 1000.0  # 5000 - 1000 = 4000 > 3600, triggers hourly re-sim
    last_request_time = 100.0

    new_sim, new_req, new_probs = main_mod._run_iteration(
        teams, groups, bracket, annex_c, played, played_groups, "dummy_key", {},
        last_sim_time, last_request_time,
    )

    assert new_req == last_request_time, "Should NOT make API call during hourly re-sim"
    assert new_sim == fake_time[0], "Should update last_sim_time to current time"


def test_seed_propagates_through_run_iteration(monkeypatch):
    """seed parameter is passed through to run_full_simulation()."""
    import main as main_mod
    import src.knockout

    captured_seeds = []

    def mock_sim(*args, **kwargs):
        seed = kwargs.get("seed")
        captured_seeds.append(seed)
        teams = args[0] if args else kwargs.get("teams", {})
        return {name: {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.05} for name in teams}

    monkeypatch.setattr(src.knockout, "run_full_simulation", mock_sim)
    monkeypatch.setattr(main_mod, "run_full_simulation", mock_sim)

    teams = {"Arg": {"elo": 2000}, "Bra": {"elo": 2000}}
    groups = {"groups": {"A": {"teams": ["Arg", "Bra"], "matches": []}}}
    bracket = [
        {"match_id": "F", "round": "FINAL", "source_matches": ["SF_1", "SF_2"], "winner": None},
    ]
    annex_c = {"_meta": {"source": "test"}}
    played = {}
    played_groups = {}

    new_sim, new_req, probs = main_mod._run_iteration(
        teams, groups, bracket, annex_c, played, played_groups, "dummy_key", {},
        last_sim_time=0.0, last_request_time=0.0,
        prev_probs=None, seed=42,
    )

    assert len(captured_seeds) >= 1, "run_full_simulation should have been called"
    assert 42 in captured_seeds, f"seed=42 should be in captured_seeds: {captured_seeds}"


def test_ai_preview_flag_disabled(tmp_path):
    """Without --ai-preview, 'No AI previews available.' must NOT appear."""
    import shutil
    src_dir = MAIN_DIR / "data"
    for f in ["teams.json", "groups.json", "bracket.json", "annex_c.json", "played.json", "team_aliases.json"]:
        shutil.copy2(src_dir / f, tmp_path / f)
    code = _runner_code_with_flag("--once", data_dir=tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    assert proc.returncode == 0, f"exit {proc.returncode}: {stderr}"
    assert "No AI previews available." not in stdout, (
        f"--once alone must NOT print AI previews. stdout={stdout!r}"
    )


def test_ai_preview_flag_enabled(tmp_path):
    """With --ai-preview --once, 'No AI previews available.' appears (gate works)."""
    import shutil
    src_dir = MAIN_DIR / "data"
    for f in ["teams.json", "groups.json", "bracket.json", "annex_c.json", "played.json", "team_aliases.json"]:
        shutil.copy2(src_dir / f, tmp_path / f)
    code = (
        f"import os, sys\n"
        f"os.environ['POLL_INTERVAL'] = '1'\n"
        f"os.environ['BSD_API_KEY'] = 'test_dummy_key'\n"
        f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
        f"os.chdir({str(MAIN_DIR)!r})\n"
        f"sys.argv = ['main.py', '--ai-preview', '--once']\n"
        f"import requests\n"
        f"import src.constants\n"
        f"src.constants.DATA_DIR = {str(tmp_path)!r}\n"
        f"import importlib\n"
        f"import src.state\n"
        f"importlib.reload(src.state)\n"
        f"src.constants.API_TIMEOUT = 1\n"
        f"class _MockResp:\n"
        f"  status_code=200\n"
        f"  text = ''\n"
        f"  def json(self):\n"
        f"    return {{}}\n"
        f"  def raise_for_status(self):\n"
        f"    pass\n"
        f"  @property\n"
        f"  def ok(self):\n"
        f"    return True\n"
        f"requests.get = lambda url, **kw: _MockResp()\n"
        f"import src.knockout\n"
        f"def _mock_sim(*args, **kwargs):\n"
        f"    teams = args[0] if args else kwargs.get('teams', {{}})\n"
        f"    return {{name: {{'qf': 0.5, 'sf': 0.3, 'final': 0.1, 'champion': 0.05}} for name in teams}}\n"
        f"src.knockout.run_full_simulation = _mock_sim\n"
        f"import main\n"
        f"main.run_full_simulation = _mock_sim\n"
        f"main.main()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    assert proc.returncode == 0, f"exit {proc.returncode}: {stderr}"
    assert "No AI previews available." in stdout, (
        f"--ai-preview --once must show AI previews gate. stdout={stdout!r}"
    )


class TestHistoricalCatchUp:
    """Tests for _run_historical_catch_up in main.py."""

    @pytest.fixture
    def full_data(self):
        """Load production data for integration tests."""
        import json
        with open(f"{DATA_DIR}/teams.json", encoding="utf-8") as f:
            teams = json.load(f)
        with open(f"{DATA_DIR}/groups.json", encoding="utf-8") as f:
            groups = json.load(f)
        with open(f"{DATA_DIR}/bracket.json", encoding="utf-8") as f:
            bracket = json.load(f)
        with open(f"{DATA_DIR}/annex_c.json", encoding="utf-8") as f:
            annex_c = json.load(f)
        return teams, groups, bracket, annex_c

    def test_empty_raw_is_noop(self, monkeypatch):
        """When fetch_raw_matches returns [], catch-up returns inputs unchanged."""
        import main as main_mod

        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: [])

        played_groups_in = {"GS_A_01": {"match_id": "GS_A_01", "winner": "Mexico"}}
        played_in = {"M73": {"match_id": "M73", "winner": "Argentina"}}
        rg, rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", {}, {"groups": {}}, [], {}, {},
            played_groups_in, played_in,
        )
        assert rg == played_groups_in
        assert rp == played_in
        assert id(rg) == id(played_groups_in)

    def test_knockout_event_matched_to_r32_slot(self, monkeypatch, full_data):
        """A single finished knockout BSD event is matched to the correct R32 slot and persisted."""
        import main as main_mod
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data

        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 3,
            "away_score": 1,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]

        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        played = {}
        team_copies = {n: dict(d) for n, d in teams.items()}
        rg, rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, played,
        )
        assert first_mid in rp
        assert rp[first_mid]["team_a"] == slot["team_a"]
        assert rp[first_mid]["team_b"] == slot["team_b"]
        assert rp[first_mid]["winner"] == slot["team_a"]
        assert rp[first_mid]["home_score"] == 3
        assert rp[first_mid]["away_score"] == 1
        elo_a = team_copies[slot["team_a"]]["elo"]
        elo_b = team_copies[slot["team_b"]]["elo"]
        assert elo_a > teams[slot["team_a"]]["elo"]  # winner gained Elo
        assert elo_b < teams[slot["team_b"]]["elo"]  # loser lost Elo

    def test_draw_included(self, monkeypatch, full_data):
        """Draw events produce entry with winner=None, is_draw=True, and Elo is adjusted."""
        import main as main_mod
        from src.knockout import resolve_knockout_slot_teams
        from src.elo import expected_score

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 1,
            "away_score": 1,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        rg, rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, {},
        )
        assert first_mid in rp
        assert rp[first_mid]["winner"] is None
        assert rp[first_mid]["is_draw"] is True
        assert rp[first_mid]["home_score"] == 1
        assert rp[first_mid]["away_score"] == 1
        # Elo should be adjusted for draw
        e_a = expected_score(teams[slot["team_a"]]["elo"], teams[slot["team_b"]]["elo"])
        if e_a > 0.5:
            assert team_copies[slot["team_a"]]["elo"] < teams[slot["team_a"]]["elo"]
        else:
            assert team_copies[slot["team_b"]]["elo"] < teams[slot["team_b"]]["elo"]

    def test_knockout_pk_catch_up(self, monkeypatch, full_data):
        """PK shootout (equal scores + BSD winner) produces PK entry with winner set, is_draw=False."""
        import main as main_mod
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99998,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 1,
            "away_score": 1,
            "winner": slot["team_a"],
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        rg, rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, {},
        )
        assert first_mid in rp
        assert rp[first_mid]["winner"] == slot["team_a"]
        assert rp[first_mid]["is_draw"] is False

    def test_restart_dedup(self, monkeypatch, full_data):
        """Event already in played is not re-processed on restart."""
        import main as main_mod
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        played_before = {first_mid: {"match_id": first_mid, "winner": slot["team_a"]}}
        rg, rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", teams, groups, bracket, annex_c, aliases,
            {}, played_before,
        )
        assert rp[first_mid]["winner"] == slot["team_a"]
        assert len(rp) == 1

    def test_unmatchable_team_skipped(self, monkeypatch, full_data):
        """Event with unmatchable team names is skipped gracefully."""
        import main as main_mod

        teams, groups, bracket, annex_c = full_data

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": "Unknown FC",
            "away_team": "Nowhere United",
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        rg, rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", teams, groups, bracket, annex_c, {},
            {}, {},
        )
        assert rp == {}

    def test_catch_up_applies_elo_to_knockout(self, monkeypatch, full_data):
        """Catch-up applies Elo to ingested knockout matches in chronological order."""
        import main as main_mod
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        before_a = team_copies[slot["team_a"]]["elo"]
        before_b = team_copies[slot["team_b"]]["elo"]
        _rg, _rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c,
            {slot["team_a"]: [], slot["team_b"]: []},
            {}, {},
        )
        assert team_copies[slot["team_a"]]["elo"] > before_a
        assert team_copies[slot["team_b"]]["elo"] < before_b

    def test_catch_up_elo_deterministic(self, monkeypatch, full_data):
        """Same ingested matches produce same Elo across runs."""
        import main as main_mod
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 3,
            "away_score": 1,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        def run_catchup():
            tc = {n: dict(d) for n, d in teams.items()}
            _rg, _rp, _ea = main_mod._run_historical_catch_up(
                "dummy_key", tc, groups, bracket, annex_c, aliases,
                {}, {},
            )
            return tc

        elo1 = run_catchup()
        elo2 = run_catchup()
        for name in teams:
            assert elo1[name]["elo"] == elo2[name]["elo"]

    def test_elo_applied_prevents_reapplication(self, monkeypatch, full_data):
        """Passing elo_applied with match_id skips that match's Elo update."""
        import main as main_mod
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]

        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(main_mod.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        before_a = team_copies[slot["team_a"]]["elo"]
        _rg, _rp, _ea = main_mod._run_historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, {}, elo_applied={first_mid},
        )
        assert team_copies[slot["team_a"]]["elo"] == before_a


class TestDrawBackfillIntegration:
    """Integration tests for draw backfill + baseline flow."""

    @pytest.fixture
    def sample_teams(self):
        return {"A": {"elo": 2000}, "B": {"elo": 1900}, "C": {"elo": 1800}}

    def test_backfill_populates_elo_applied(self, monkeypatch, sample_teams):
        """2 draw matches both backfilled, Elo changed."""
        from main import _run_draw_backfill

        monkeypatch.setattr("main.state.save_elo_applied", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_teams", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_elo_update_log", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.load_elo_update_log", lambda *a, **kw: [])

        teams = dict(sample_teams)
        played = {
            "M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                    "winner": None, "home_score": 1, "away_score": 1,
                    "completed_at": "2026-06-11T20:00:00Z"},
            "M02": {"match_id": "M02", "team_a": "A", "team_b": "C",
                    "winner": None, "home_score": 2, "away_score": 2,
                    "completed_at": "2026-06-12T20:00:00Z"},
        }
        elo_applied = set()
        result = _run_draw_backfill(teams, played, {}, elo_applied)
        assert "M01" in result
        assert "M02" in result
        # Elo changed for both teams
        assert teams["A"]["elo"] != 2000
        assert teams["B"]["elo"] != 1900

    def test_backfill_includes_group_matches(self, monkeypatch, sample_teams):
        """Group draw match in played_groups is backfilled."""
        from main import _run_draw_backfill

        monkeypatch.setattr("main.state.save_elo_applied", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_teams", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_elo_update_log", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.load_elo_update_log", lambda *a, **kw: [])

        teams = dict(sample_teams)
        played_groups = {
            "GS_A_01": {"match_id": "GS_A_01", "team_a": "A", "team_b": "B",
                        "winner": None, "home_score": 1, "away_score": 1,
                        "completed_at": "2026-06-10T20:00:00Z"},
        }
        elo_applied = set()
        result = _run_draw_backfill(teams, {}, played_groups, elo_applied)
        assert "GS_A_01" in result
        assert teams["A"]["elo"] != 2000

    def test_backfill_skips_non_draw_matches(self, monkeypatch, sample_teams):
        """Only draws are backfilled, non-draws are skipped."""
        from main import _run_draw_backfill

        monkeypatch.setattr("main.state.save_elo_applied", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_teams", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_elo_update_log", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.load_elo_update_log", lambda *a, **kw: [])

        teams = dict(sample_teams)
        played = {
            "M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                    "winner": "A", "home_score": 3, "away_score": 1,
                    "completed_at": "2026-06-11T20:00:00Z"},
        }
        elo_applied = set()
        result = _run_draw_backfill(teams, played, {}, elo_applied)
        assert "M01" not in result
        assert teams["A"]["elo"] == 2000  # unchanged

    def test_baseline_records_brier(self, monkeypatch, tmp_path):
        """eval_baseline_report.json created with correct Brier for fixture matches."""
        import json
        from pathlib import Path
        from src import constants
        from main import _record_eval_baseline

        monkeypatch.setattr(constants, "DATA_DIR", tmp_path)
        monkeypatch.setattr("main.state.save_teams", lambda *a, **kw: None)

        teams = {"Arg": {"elo": 2100}, "Bra": {"elo": 2000}}
        played = {
            "M01": {"match_id": "M01", "team_a": "Arg", "team_b": "Bra",
                    "winner": "Arg", "home_score": 2, "away_score": 0,
                    "completed_at": "2026-06-11T20:00:00Z"},
        }
        _record_eval_baseline(teams, played, {})

        path = tmp_path / "eval_baseline_report.json"
        assert path.exists(), "eval_baseline_report.json should exist"
        d = json.loads(path.read_text(encoding="utf-8"))
        assert d["n_matches"] == 1
        assert 0 <= d["metrics"]["brier"] <= 1
        assert d["metrics"]["brier"] > 0

        hist_path = tmp_path / "prediction_history.json"
        assert hist_path.exists()
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
        assert len(hist) == 1
        assert hist[0]["match_id"] == "M01"
        # Compound format (Phase 13)
        assert "signals" in hist[0], "Entry should have signals dict"
        assert "prediction" not in hist[0], "No flat prediction key"
        assert hist[0]["signals"]["elo"]["available"] is True
        assert hist[0]["signals"]["elo"]["team_a_elo"] == 2100
        assert hist[0]["signals"]["elo"]["team_b_elo"] == 2000


class TestPerIterationHistory:
    """_run_iteration creates prediction_history entries for newly-finished matches."""

    def _make_mock_response(self):
        class MockResp:
            status_code = 200
            ok = True
            def json(self):
                return {}
            def raise_for_status(self):
                pass
        return MockResp()

    def test_per_iteration_creates_history_entries(self, monkeypatch):
        """New match detection triggers append_prediction_history with ELO signal."""
        import main as main_mod
        import src.state

        mock_sim_teams = lambda *a, **kw: {n: {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.05} for n in (a[0] if a else kw.get("teams", {}))}
        monkeypatch.setattr("requests.get", lambda *a, **kw: self._make_mock_response())
        monkeypatch.setattr(main_mod, "run_full_simulation", mock_sim_teams)
        monkeypatch.setattr(src.knockout, "run_full_simulation", mock_sim_teams)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_signal_cache", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_prediction_history", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_calibration_params", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "load_prediction_history", lambda *a, **kw: [])

        captured_entries = []
        monkeypatch.setattr(src.state, "append_prediction_history",
                            lambda e, *a, **kw: captured_entries.append(e))

        # Ensure fetch_raw_matches returns truthy so process_matches is called
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: [{"id": 99999}])
        # Mock process_matches to return a new knockout match
        new_match = {
            "match_id": "M99",
            "team_a": "Arg",
            "team_b": "Bra",
            "winner": "Arg",
            "home_score": 2,
            "away_score": 1,
        }
        monkeypatch.setattr(main_mod, "process_matches", lambda *a, **kw: [new_match])

        teams = {"Arg": {"elo": 2000}, "Bra": {"elo": 1900}}
        groups = {"groups": {"A": {"teams": ["Arg", "Bra"], "matches": []}}}
        bracket = [{"match_id": "M99", "round": "FINAL", "source_matches": ["SF_1", "SF_2"], "winner": None}]
        annex_c = {"_meta": {"source": "test"}}
        played = {}
        played_groups = {}

        main_mod._run_iteration(
            teams=teams, groups=groups, bracket=bracket, annex_c=annex_c,
            played=played, played_groups=played_groups,
            api_key="test", aliases={},
            last_sim_time=0.0, last_request_time=0.0,
        )

        assert len(captured_entries) == 1
        entry = captured_entries[0]
        assert entry["match_id"] == "M99"
        assert "signals" in entry
        assert "elo" in entry["signals"]
        assert entry["signals"]["elo"]["available"] is True
        assert "probability" in entry["signals"]["elo"]
        assert entry["actual"] == 1.0  # Arg won
        assert 0 < entry["signals"]["elo"]["probability"] < 1

    def test_per_iteration_dedup_skips_existing(self, monkeypatch):
        """Matches already in prediction_history are not duplicated."""
        import main as main_mod
        import src.state

        mock_sim_teams = lambda *a, **kw: {n: {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.05} for n in (a[0] if a else kw.get("teams", {}))}
        monkeypatch.setattr("requests.get", lambda *a, **kw: self._make_mock_response())
        monkeypatch.setattr(main_mod, "run_full_simulation", mock_sim_teams)
        monkeypatch.setattr(src.knockout, "run_full_simulation", mock_sim_teams)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_signal_cache", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_prediction_history", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_calibration_params", lambda *a, **kw: None)

        existing_history = [{"match_id": "M99"}]
        monkeypatch.setattr(src.state, "load_prediction_history", lambda *a, **kw: existing_history)

        captured_entries = []
        monkeypatch.setattr(src.state, "append_prediction_history",
                            lambda e, *a, **kw: captured_entries.append(e))

        new_match = {
            "match_id": "M99",
            "team_a": "Arg",
            "team_b": "Bra",
            "winner": "Arg",
            "home_score": 2,
            "away_score": 1,
        }
        monkeypatch.setattr(main_mod, "process_matches", lambda *a, **kw: [new_match])

        teams = {"Arg": {"elo": 2000}, "Bra": {"elo": 1900}}
        groups = {"groups": {"A": {"teams": ["Arg", "Bra"], "matches": []}}}
        bracket = [{"match_id": "M99", "round": "FINAL", "source_matches": ["SF_1", "SF_2"], "winner": None}]
        annex_c = {"_meta": {"source": "test"}}

        main_mod._run_iteration(
            teams=teams, groups=groups, bracket=bracket, annex_c=annex_c,
            played={}, played_groups={},
            api_key="test", aliases={},
            last_sim_time=0.0, last_request_time=0.0,
        )

        assert len(captured_entries) == 0

    def test_per_iteration_group_match_creates_entry(self, monkeypatch):
        """Group match also creates prediction_history entry."""
        import main as main_mod
        import src.state

        mock_sim_teams = lambda *a, **kw: {n: {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.05} for n in (a[0] if a else kw.get("teams", {}))}
        monkeypatch.setattr("requests.get", lambda *a, **kw: self._make_mock_response())
        monkeypatch.setattr(main_mod, "run_full_simulation", mock_sim_teams)
        monkeypatch.setattr(src.knockout, "run_full_simulation", mock_sim_teams)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_signal_cache", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_prediction_history", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_calibration_params", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "load_prediction_history", lambda *a, **kw: [])

        captured_entries = []
        monkeypatch.setattr(src.state, "append_prediction_history",
                            lambda e, *a, **kw: captured_entries.append(e))

        # Return no knockout match, but one group match
        monkeypatch.setattr(main_mod, "fetch_raw_matches", lambda *a, **kw: [{"id": 99999}])
        monkeypatch.setattr(main_mod, "process_matches", lambda *a, **kw: [])
        new_group_match = {
            "match_id": "GS_A_01",
            "team_a": "Arg",
            "team_b": "Bra",
            "winner": None,  # draw
            "home_score": 1,
            "away_score": 1,
        }
        monkeypatch.setattr(main_mod, "process_group_matches", lambda *a, **kw: [new_group_match])

        teams = {"Arg": {"elo": 2000}, "Bra": {"elo": 1900}}
        groups = {"groups": {"A": {"teams": ["Arg", "Bra"], "matches": [
            {"match_id": "GS_A_01", "team_a": "Arg", "team_b": "Bra"}]}}}
        bracket = []
        annex_c = {}

        main_mod._run_iteration(
            teams=teams, groups=groups, bracket=bracket, annex_c=annex_c,
            played={}, played_groups={},
            api_key="test", aliases={},
            last_sim_time=0.0, last_request_time=0.0,
        )

        assert len(captured_entries) == 1
        entry = captured_entries[0]
        assert entry["match_id"] == "GS_A_01"
        assert entry["actual"] == 0.5  # draw
