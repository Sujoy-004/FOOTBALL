from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WC_REPO = ROOT / "competitions" / "worldcup" / "data"
UCL_REPO = ROOT / "competitions" / "ucl" / "data"

WC_DATA_FILES = [
    "teams.json",
    "groups.json",
    "bracket.json",
    "team_aliases.json",
    "annex_c.json",
    "played.json",
    "played_groups.json",
]

UCL_DATA_FILES = [
    "fixtures.json",
    "playoff_pairings.json",
    "bracket_rules.json",
    "team_aliases.json",
    "knockout_results.json",
    "squad_values.json",
]


def require_repo_file(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"repo data fixture missing (fresh clone?): {path}")


def seed_wc_dir(dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for name in WC_DATA_FILES:
        src = WC_REPO / name
        require_repo_file(src)
        shutil.copy2(src, dst / name)
    return dst


def seed_ucl_dir(dst: Path, results=None, knockout: bool = True) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for name in UCL_DATA_FILES:
        if name == "knockout_results.json" and not knockout:
            continue
        src = UCL_REPO / name
        require_repo_file(src)
        shutil.copy2(src, dst / name)
    if results is not None:
        (dst / "results.json").write_text(
            json.dumps(results, ensure_ascii=False), encoding="utf-8"
        )
    return dst


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def snapshot_tree(root: Path) -> dict:
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root)).replace("\\", "/")] = p.read_bytes()
    return out


def groups_data(groups_raw) -> dict:
    return groups_raw.get("groups", groups_raw)


def wc_events_from_snapshot(groups_raw, played, played_groups) -> list:
    events = []
    for letter, g in groups_data(groups_raw).items():
        for m in g.get("matches", []):
            mid = m["match_id"]
            if mid not in played_groups:
                continue
            entry = played_groups[mid]
            events.append({
                "id": mid,
                "match_id": mid,
                "status": "finished",
                "group_name": f"Group {letter}",
                "home_team": entry["team_a"],
                "away_team": entry["team_b"],
                "home_score": entry["home_score"],
                "away_score": entry["away_score"],
                "event_date": entry.get("completed_at") or "",
            })
    for mid, entry in played.items():
        ev = {
            "id": mid,
            "match_id": mid,
            "status": "finished",
            "home_team": entry["team_a"],
            "away_team": entry["team_b"],
            "home_score": entry["home_score"],
            "away_score": entry["away_score"],
            "event_date": entry.get("completed_at") or "",
        }
        if entry["home_score"] == entry["away_score"] and not entry.get("is_draw"):
            if entry.get("winner") == entry["team_a"]:
                ev["penalty_home"], ev["penalty_away"] = 4, 3
            else:
                ev["penalty_home"], ev["penalty_away"] = 3, 4
        events.append(ev)
    return events


def wc_repo_snapshot():
    groups = load_json(WC_REPO / "groups.json", {})
    played = load_json(WC_REPO / "played.json", {})
    played_groups = load_json(WC_REPO / "played_groups.json", {})
    return groups, played, played_groups


def drift_wc_store(wc_dir: Path, ko=None, group=None) -> None:
    if ko:
        played_path = wc_dir / "played.json"
        played = json.loads(played_path.read_text(encoding="utf-8"))
        for mid, (hs, as_) in ko.items():
            if mid in played:
                played[mid]["home_score"] = hs
                played[mid]["away_score"] = as_
        played_path.write_text(
            json.dumps(played, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if group:
        pg_path = wc_dir / "played_groups.json"
        pg = json.loads(pg_path.read_text(encoding="utf-8"))
        for mid, (hs, as_) in group.items():
            if mid in pg:
                pg[mid]["home_score"] = hs
                pg[mid]["away_score"] = as_
        pg_path.write_text(
            json.dumps(pg, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def ucl_league_events(data_dir: Path, n: int = 4) -> list:
    fixtures = json.loads((data_dir / "fixtures.json").read_text(encoding="utf-8"))
    rows = []
    for md in fixtures.get("schedule", {}).get("matchdays", []):
        for m in md:
            if "team_a" in m and "team_b" in m:
                rows.append(m)
    seen = set()
    events = []
    for m in rows:
        key = (m["team_a"], m["team_b"])
        if key in seen:
            continue
        seen.add(key)
        events.append({
            "match_id": m.get("match_id") or f"MD_{len(events) + 1}",
            "status": "finished",
            "home_team": m["team_a"],
            "away_team": m["team_b"],
            "home_score": 2,
            "away_score": 1,
            "stage": "LEAGUE_STAGE",
            "season": "2025/26",
            "event_date": "2025-09-16T19:00:00Z",
        })
        if len(events) >= n:
            break
    return events


def ucl_final_event(knockout: dict, decided: bool = True) -> list:
    final = knockout["matches"]["final"][0]
    ta, tb = final["team_a"], final["team_b"]
    score = final.get("score") or {"home": 1, "away": 1}
    ev = {
        "status": "finished",
        "stage": "FINAL",
        "season": "2025/26",
        "home_team": ta,
        "away_team": tb,
        "home_score": score.get("home", 1),
        "away_score": score.get("away", 1),
        "event_date": "2026-05-30T20:00:00Z",
    }
    if decided:
        ev["extra_time"] = bool(final.get("et_played"))
        ev["et_home"] = final.get("et_a", 0)
        ev["et_away"] = final.get("et_b", 0)
        ev["shootout"] = {
            "home": final.get("penalty_a", 4),
            "away": final.get("penalty_b", 3),
            "winner": final.get("penalty_winner"),
        }
    return [ev]


class StubProvider:
    name = "StubProvider"

    def __init__(self, events=None, *, raises=None, competition="WC"):
        self._events = list(events or [])
        self._raises = raises
        self.competition = competition
        self.last_error = None
        self.calls = []

    def fetch_matches(self, competition_id=None):
        self.calls.append(competition_id)
        if competition_id != self.competition:
            raise AssertionError(
                f"provider asked for competition_id={competition_id!r}, "
                f"expected {self.competition!r}"
            )
        if self._raises is not None:
            raise self._raises
        return self._events


def recording_provider(stub):
    calls = []

    def _get_data_provider(bsd_api_key, football_data_org_key, bsd_league_id=None):
        calls.append(bsd_league_id)
        return stub

    return calls, _get_data_provider


def patch_wc_offline(monkeypatch, tmp_path):
    import web.startup
    from competitions.worldcup.src import pipeline as wc_pipeline

    monkeypatch.setattr(web.startup, "is_snapshot_mode", lambda: False)
    leader = tmp_path / "freshness.json"
    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path", lambda: leader)

    def _no_signal(*a, **k):
        return {}

    monkeypatch.setattr(
        "competitions.worldcup.src.predictors.odds.fetch_and_cache_odds", _no_signal
    )
    monkeypatch.setattr(
        "competitions.worldcup.src.predictors.rest_days.compute_rest_days_signal",
        _no_signal,
    )
    monkeypatch.setattr(
        "competitions.worldcup.src.predictors.rolling_form.compute_rolling_form_signal",
        _no_signal,
    )
    monkeypatch.setattr(
        "competitions.worldcup.src.predictors.squad_value.compute_squad_value_signal",
        _no_signal,
    )
    return leader


def snapshot_cache_state(module):
    snapshot = dict(getattr(module, "cache"))
    return snapshot


def restore_cache_state(module, snapshot):
    cache = getattr(module, "cache")
    cache.clear()
    cache.update(snapshot)