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
6. UCL fixture-name alias coverage is complete.
"""

from __future__ import annotations

import json
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
    """6/UCL. Every UCL fixture team normalizes through the production lookup."""
    from football_core.fetcher import _build_alias_lookup, normalize_team

    aliases = json.loads((UCL_DATA / "team_aliases.json").read_text(encoding="utf-8"))
    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text(encoding="utf-8"))
    lookup = _build_alias_lookup(aliases, [])
    for team in fixtures["schedule"]["teams"]:
        name = team["name"]
        assert normalize_team(name, lookup) == name or name.lower() in lookup, \
            f"UCL team {name!r} would fail normalization"
