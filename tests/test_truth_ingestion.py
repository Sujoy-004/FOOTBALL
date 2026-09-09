"""Truth-first result ingestion — regression coverage (Exchange: truth-first fix).

Guarantees:
1. Provider alias normalization covers known official spellings.
2. A FINISHED result that fails normalization is loudly surfaced and counted,
   never silently dropped.
3. A completed match injected as played is never re-sampled by the simulator.
4. World Cup completed-result completeness (72 + 32 = 104) when runtime data
   is present post-tournament.
5. Knockout results ingest once upstream group state is corrected
   (Argentina vs Cape Verde regression).
6. UCL fixture-name alias coverage is complete — for the historical root
   fixtures AND the active-season (draw) fixtures.
7. UCL live ingestion normalizes the raw BSD provider spellings that were
   logged as "unmatchable team names", and refuses finished events that
   carry no score evidence instead of fabricating a 0-0.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


def _build_group_lookup():
    """Build the alias lookup exactly as production does."""
    sys.path.insert(0, str(ROOT / "competitions" / "worldcup"))
    aliases = json.loads((WC_DATA / "team_aliases.json").read_text(encoding="utf-8"))
    groups_raw = json.loads((WC_DATA / "groups.json").read_text(encoding="utf-8"))
    from competitions.worldcup.src.fetcher import _build_alias_lookup
    lookup = _build_alias_lookup(aliases, [])
    gd = groups_raw.get("groups", groups_raw)
    for g in gd.values():
        for team in g.get("teams", []):
            lookup[team.strip().lower()] = team
    return lookup


def test_alias_covers_provider_spellings():
    """1. Official provider spellings of every group-stage team must normalize."""
    from football_core.fetcher import normalize_team
    lookup = _build_group_lookup()
    assert normalize_team("Cape Verde Islands", lookup) == "Cape Verde"
    assert normalize_team("Cabo Verde", lookup) == "Cape Verde"
    assert normalize_team("Cape Verde", lookup) == "Cape Verde"
    # every canonical group team resolves through its own name
    groups_raw = json.loads((WC_DATA / "groups.json").read_text(encoding="utf-8"))
    gd = groups_raw.get("groups", groups_raw)
    for g in gd.values():
        for team in g.get("teams", []):
            assert normalize_team(team, lookup) == team


def test_finished_unmatchable_is_visible_and_counted(caplog):
    """2. A finished result with unknown teams logs a WARNING and is counted."""
    import json as _json
    import logging

    aliases = _json.loads((WC_DATA / "team_aliases.json").read_text(encoding="utf-8"))
    groups_raw = _json.loads((WC_DATA / "groups.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT / "competitions" / "worldcup"))
    from football_core.fetcher import new_ingestion_stats
    from competitions.worldcup.src.fetcher import process_group_matches
    from web.common import get_data_provider  # noqa: F401  (env sanity)

    teams = {"Unknown FC": {"elo": 1500}}
    raw = [{
        "id": "x1", "home_team": "Atlético Nowhere", "away_team": "Mystery United",
        "home_score": 2, "away_score": 1, "status": "finished",
        "group_name": "Group A", "event_date": "",
    }]
    stats = new_ingestion_stats()
    with caplog.at_level(logging.WARNING):
        out = process_group_matches(raw, teams, groups_raw, aliases,
                                    set(), set(), ingestion_stats=stats)
    assert out == []
    assert stats["finished_received"] == 1
    assert stats["skipped_unmatchable"] == 1
    assert any("RESULT INGESTION SKIP" in r.message for r in caplog.records)


def test_completed_match_is_never_sampled():
    """3+6. Injected played results are immutable regardless of seed."""
    import random

    from competitions.worldcup.src.groups import compute_standings
    from football_core.groups import simulate_group_matches

    teams = {"Alpha": {"elo": 1900}, "Beta": {"elo": 1700},
             "Gamma": {"elo": 1800}, "Delta": {"elo": 1600}}
    groups = {"groups": {"A": {
        "teams": list(teams),
        "matches": [
            {"match_id": "T1", "team_a": "Alpha", "team_b": "Beta"},
            {"match_id": "T2", "team_a": "Gamma", "team_b": "Delta"},
        ],
    }}}
    # Real completed result for T1 that pure Elo would almost never produce.
    played = {"T1": {"match_id": "T1", "team_a": "Beta", "team_b": "Alpha",
                     "home_score": 4, "away_score": 0, "winner": "Beta",
                     "is_draw": False}}
    runs = []
    for seed in (1, 2, 3):
        rng = random.Random(seed)
        elo_flat = {n: d["elo"] for n, d in teams.items()}
        res = simulate_group_matches(groups, teams, elo_flat, rng,
                                     fair_play=False,
                                     played_groups=played,
                                     base_rate=1.25)
        t1 = res["A"]["T1"]
        assert (t1["score_a"], t1["score_b"]) == (4, 0), \
            "completed match was re-sampled - truth invariant violated"
        runs.append(res)
    assert runs[0]["A"]["T1"] == runs[1]["A"]["T1"] == runs[2]["A"]["T1"]


def test_wc_completed_result_completeness_104():
    """4. Post-tournament invariant: 72 + 32 = 104, Cape Verde + Final present.

    Skips on fresh clones where the gitignored runtime files don't exist yet.
    """
    pg_path = WC_DATA / "played_groups.json"
    pl_path = WC_DATA / "played.json"
    if not (pg_path.exists() and pl_path.exists()):
        pytest.skip("WC runtime result files absent (fresh clone)")
    pg = json.loads(pg_path.read_text(encoding="utf-8"))
    pl = json.loads(pl_path.read_text(encoding="utf-8"))
    total = len(pg) + len(pl)
    if total < 104:
        pytest.skip(f"tournament still in progress locally ({total}/104)")
    assert len(pg) == 72 and len(pl) == 32
    cv = [e for e in pg.values() if "Cape Verde" in (e["team_a"], e["team_b"])]
    assert len(cv) == 3, "Group H / Cape Verde results missing"
    m86 = pl.get("M86")
    assert m86 and {m86["team_a"], m86["team_b"]} == {"Argentina", "Cape Verde"}
    final = pl.get("FINAL")
    assert final and final["winner"], "Final must be ingested as immutable history"


def test_knockout_ingestion_after_corrected_group_state():
    """5. Once identities normalize, the real R32 pairing ingests into its slot."""
    sys.path.insert(0, str(ROOT / "competitions" / "worldcup"))
    from competitions.worldcup.src.fetcher import process_matches

    teams = {"Belgium": {"elo": 1800}, "Senegal": {"elo": 1600}}
    bracket = [{"match_id": "M82", "round": "R32",
                "team_a": "Belgium", "team_b": "Senegal"}]
    aliases = {"Senegal": []}
    raw = [{"id": "r1", "home_team": "Belgium", "away_team": "Senegal",
            "home_score": 3, "away_score": 2, "status": "finished"}]
    out = process_matches(raw, teams, bracket, aliases, set())
    assert len(out) == 1 and out[0]["match_id"] == "M82"
    assert out[0]["winner"] == "Belgium"


def test_ucl_alias_coverage_complete_for_fixtures():
    """6/UCL. Every UCL (2025/26 root) fixture team normalizes through the
    production alias lookup."""
    from football_core.fetcher import _build_alias_lookup, normalize_team

    aliases = json.loads((UCL_DATA / "team_aliases.json").read_text(encoding="utf-8"))
    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text(encoding="utf-8"))
    lookup = _build_alias_lookup(aliases, [])
    for team in fixtures["schedule"]["teams"]:
        name = team["name"]
        assert normalize_team(name, lookup) == name or name.lower() in lookup, \
            f"UCL team {name!r} would fail normalization"


def _ucl_production_context():
    """Replicate pipeline fetch_live_data's ACTIVE-SEASON alias lookup EXACTLY
    via build_active_season_lookup (aliases + canonical draw seeding, explicit
    accent folding, NO root-clobber). Returns (season_lookup, drawn_pairs,
    active_season)."""
    from competitions.ucl.src.pipeline import build_active_season_lookup
    from competitions.ucl.src.seasons import get_current_season, read_season_fixtures

    aliases = json.loads((UCL_DATA / "team_aliases.json").read_text(encoding="utf-8"))
    lookup = build_active_season_lookup(UCL_DATA, aliases)

    active = get_current_season(UCL_DATA)
    season = active["season"] if active and active.get("season") else None
    pairs: set[tuple[str, str]] = set()
    if season:
        doc = read_season_fixtures(UCL_DATA, season) or {}
        for f in doc.get("fixtures", []) or []:
            if not isinstance(f, dict):
                continue
            ta, tb = f.get("team_a", "").strip(), f.get("team_b", "").strip()
            if ta and tb:
                pairs.add((ta, tb))
    return lookup, pairs, season


def test_ucl_active_season_fixture_self_resolution():
    """6/UCL. Every drawn (gen-*) fixture team resolves to ITSELF through the
    production lookup — no normalization surprise inside the drawn season; any
    legacy short-spelling row normalizes onto one of the drawn team names."""
    from competitions.ucl.src.seasons import read_season_fixtures
    from football_core.fetcher import normalize_team

    lookup, _pairs, season = _ucl_production_context()
    assert season, "repo must point current.json at a season"
    doc = read_season_fixtures(UCL_DATA, season) or {}
    assert doc.get("fixtures"), f"active season {season} has no fixtures"
    drawn_names: set[str] = set()
    for f in doc["fixtures"]:
        if str(f.get("match_id") or "").startswith("gen-"):
            drawn_names.add(f["team_a"].strip())
            drawn_names.add(f["team_b"].strip())
    assert drawn_names, f"active season {season} has no drawn fixtures"
    for f in doc["fixtures"]:
        for side in ("team_a", "team_b"):
            name = f[side].strip()
            resolved = normalize_team(name, lookup)
            if str(f.get("match_id") or "").startswith("gen-"):
                assert resolved == name, \
                    f"drawn team {name!r} normalizes to a different name"
            else:
                assert resolved == name or resolved in drawn_names, \
                    f"legacy row team {name!r} normalizes to {resolved!r} " \
                    f"(not a drawn name)"


def test_ucl_provider_aliases_normalize_to_canonical():
    """6/UCL. The raw BSD spellings behind the 'unmatchable team names'
    warnings normalize to a canonical fixture team name."""
    from football_core.fetcher import normalize_team

    lookup, _pairs, _season = _ucl_production_context()
    expected = {
        "FC Barcelona": "Barcelona",
        "Liverpool FC": "Liverpool",
        "SSC Napoli": "Napoli",
        "FC Bayern München": "Bayern Munich",
        "FC Internazionale Milano": "Inter Milan",
        "Club Brugge KV": "Club Brugge",
        "Paris Saint-Germain FC": "Paris Saint-Germain",
        "ŠK Slovan Bratislava": "Slovan Bratislava",
    }
    for provider_name, canonical in expected.items():
        assert normalize_team(provider_name, lookup) == canonical, provider_name


def test_ucl_live_provider_pairs_attach_to_drawn_fixtures():
    """6/UCL. The observed live warning pairs each have a drawn fixture in
    the active season once normalized (regression for RESULT INGESTION SKIP).
    """
    from football_core.fetcher import normalize_team

    lookup, pairs, _season = _ucl_production_context()
    observed = [
        ("Club Brugge KV", "Aston Villa FC"),
        ("FC Porto", "Manchester City FC"),
        ("FC Barcelona", "Feyenoord Rotterdam"),
        ("VfB Stuttgart", "Viking FK"),
        ("Paris Saint-Germain FC", "ŠK Slovan Bratislava"),
        ("Fenerbahçe SK", "AS Roma"),
        ("Manchester United FC", "Sabah FK"),
    ]
    for home, away in observed:
        na, nb = normalize_team(home, lookup), normalize_team(away, lookup)
        assert (na, nb) in pairs or (nb, na) in pairs, \
            f"{home} vs {away} -> ({na}, {nb}) has no drawn fixture in the active season"


def _seed_active_season_dir(tmp_path: Path) -> Path:
    """Minimal data dir: aliases + current.json + a drawn 2026/27 fixture."""
    ucl_dir = tmp_path / "ucl"
    (ucl_dir / "seasons" / "2026_27").mkdir(parents=True, exist_ok=True)
    shutil.copy2(UCL_DATA / "team_aliases.json", ucl_dir / "team_aliases.json")
    fx_doc = {"schema": 1, "season": "2026/27", "fixtures": [
        {"match_id": "gen-test01", "team_a": "Club Brugge", "team_b": "Aston Villa",
         "event_date": None, "stage": "LEAGUE_STAGE", "status": "scheduled"},
    ], "availability": {"fixtures_count": 1, "results_count": 0, "partial": True},
        "meta": {"provider": None}}
    (ucl_dir / "seasons" / "2026_27" / "fixtures.json").write_text(
        json.dumps(fx_doc, ensure_ascii=False), encoding="utf-8")
    (ucl_dir / "current.json").write_text(
        json.dumps({"season": "2026/27"}), encoding="utf-8")
    return ucl_dir


def test_finished_event_without_scores_is_refused(tmp_path, caplog):
    """7/UCL. A provider 'finished' event with (None, None) scores is loudly
    refused and NEVER written as a fabricated 0-0 result."""
    import logging

    import arch_util as au
    from competitions.ucl.src.pipeline import fetch_live_data

    ucl_dir = _seed_active_season_dir(tmp_path)
    events = [{
        "status": "finished",
        "home_team": "Club Brugge KV",
        "away_team": "Aston Villa FC",
        "home_score": None,
        "away_score": None,
        "season": "2026/27",
        "event_date": "2026-09-09T19:00:00Z",
        "stage": "LEAGUE_STAGE",
    }]
    provider = au.StubProvider(events, competition="CL")
    with caplog.at_level(logging.WARNING):
        summary = fetch_live_data(ucl_dir, "", "", provider=provider)
    assert any("FINISHED EVENT WITHOUT SCORES" in r.message for r in caplog.records)
    report = summary["report"]
    assert report.get("finished", {}).get("received", 0) == 0
    assert not (ucl_dir / "seasons" / "2026_27" / "results.json").exists(), \
        "a finished event with no scores must not be recorded as 0-0"


def test_ucl_live_event_ingests_into_active_season_store(tmp_path):
    """7/UCL positive path. A scored live event (the exact Club Brugge KV vs
    Aston Villa FC case) normalizes and lands in the season store."""
    import arch_util as au
    from competitions.ucl.src.pipeline import fetch_live_data

    ucl_dir = _seed_active_season_dir(tmp_path)
    events = [{
        "status": "finished",
        "home_team": "Club Brugge KV",
        "away_team": "Aston Villa FC",
        "home_score": 2,
        "away_score": 3,
        "season": "2026/27",
        "event_date": "2026-09-09T19:00:00Z",
        "stage": "LEAGUE_STAGE",
    }]
    summary = fetch_live_data(ucl_dir, "", "", provider=au.StubProvider(events, competition="CL"))
    report = summary["report"]
    assert report.get("finished", {}).get("ingested", 0) == 1
    res = json.loads(
        (ucl_dir / "seasons" / "2026_27" / "results.json").read_text(encoding="utf-8"))
    m = res["matches"][0]
    assert m["team_a"] == "Club Brugge" and m["team_b"] == "Aston Villa"
    assert (m["home_score"], m["away_score"]) == (2, 3)


def test_finished_scored_event_without_fixture_is_skipped_no_target(tmp_path):
    """7/UCL. A finished, scored event whose normalized pair has NO active-
    season fixture is reported as skipped_no_target and never written —
    it must not be attached to a fixture by accident."""
    import arch_util as au
    from competitions.ucl.src.pipeline import fetch_live_data

    ucl_dir = _seed_active_season_dir(tmp_path)
    events = [{
        "status": "finished",
        "home_team": "Club Brugge KV",
        "away_team": "Manchester United FC",
        "home_score": 1,
        "away_score": 1,
        "season": "2026/27",
        "event_date": "2026-09-09T19:00:00Z",
    }]
    summary = fetch_live_data(ucl_dir, "", "", provider=au.StubProvider(events, competition="CL"))
    report = summary["report"]
    assert report.get("finished", {}).get("skipped_no_target", 0) == 1
    assert report.get("finished", {}).get("ingested", 0) == 0
    res = json.loads(
        (ucl_dir / "seasons" / "2026_27" / "results.json").read_text(encoding="utf-8"))
    assert not (res.get("matches") or []), \
        "an event with no matching fixture must not be recorded as a result"
