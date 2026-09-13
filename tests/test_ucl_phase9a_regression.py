"""Regression tests for the Phase 9A 2026/27 Matchday 1 live-result ingestion.

Reproduces the exact runtime rejection pattern that left the dashboard at 15
finished MD1 matches instead of 18:

1. ``Slavia Praha vs Racing Club de Lens`` (2-3) was rejected with
   ``reason=unmatchable_team_names`` because ``Racing Club de Lens`` was not
   an observed alias of the canonical ``Lens``.
2. ``Liverpool vs Atletico Madrid`` and ``Bayern Munich vs Bodo/Glimt`` were
   rejected with ``reason=no_active_season_target`` because provider ASCII
   spellings reached the accent-sensitive ``(home, away)`` fixture-pair
   lookup in ``_upsert_season_results`` instead of the catalog identities
   ``Atlético Madrid`` / ``Bodø/Glimt``.

Each test proves the fixed behavior against a DETERMINISTIC seeded draw store:
the three events attach exactly once to the canonical ``gen-*`` fixtures, the
pair matching is accent-folded like the fixtures upsert, invalid (unseeded)
pairs remain rejected, and the full run is idempotent.

Deterministic runtime, not the developer's live store
-----------------------------------------------------
``_seeded_runtime`` builds a fresh temp data dir from ONLY committed inputs —
the authoritative 2026/27 draw snapshot (``draws/2026_27_league_draw.json``),
``team_aliases.json``, and the root structural ``bracket_rules.json`` /
``playoff_pairings.json`` that ``build_competition_state`` requires — then
runs ``ensure_draw_season`` to produce the byte-identical 2026/27 store: 144
fixtures, an 8x18 schedule, ``current.json`` pointing at 2026/27, and an EMPTY
results ledger. It copies NO gitignored / runtime state (``seasons/``,
``results.json``, ``current.json``, ``shadow/``, etc.), so the tests reproduce
exactly on a clean checkout instead of drifting with the live store.

One guard test reads the LIVE store directly to keep the "18 finished MD1
matches" invariant the user demands, and skips cleanly when that store has not
been generated on the current checkout. No data file in ``competitions/ucl/data``
is ever modified by these tests.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


class _Provider:
    def __init__(self, events):
        self.events = events
        self.last_error = None

    def fetch_matches(self, competition_id="CL", **kwargs):
        return list(self.events)


def _seeded_runtime(tmp_path: Path) -> Path:
    """Deterministic 2026/27 runtime for a test.

    Copies ONLY committed inputs into a fresh temp ``data_dir`` — the
    authoritative draw snapshot (``draws/2026_27_league_draw.json``),
    ``team_aliases.json``, and the structural ``bracket_rules.json`` /
    ``playoff_pairings.json`` that ``build_competition_state`` reads from the
    data-dir root — then ``ensure_draw_season`` materializes the byte-identical
    2026/27 store: 144 fixtures, a valid 8x18 schedule, ``current.json`` set to
    2026/27, and an empty results ledger. No season store, results, current
    pointer, shadow, historical or knock-out data is copied from the repo.
    """
    from competitions.ucl.src.season_draw import ensure_draw_season

    data_dir = tmp_path / "ucl_data"
    data_dir.mkdir()
    shutil.copytree(UCL_DATA / "draws", data_dir / "draws")
    shutil.copy2(UCL_DATA / "team_aliases.json", data_dir / "team_aliases.json")
    shutil.copy2(UCL_DATA / "bracket_rules.json", data_dir / "bracket_rules.json")
    shutil.copy2(UCL_DATA / "playoff_pairings.json", data_dir / "playoff_pairings.json")
    ensure_draw_season(data_dir)
    return data_dir


def _catalog_index(fixtures_doc: dict) -> tuple[set[str], dict[str, int]]:
    """index a season fixtures.json into (catalog ids, matchday per id)."""
    catalog = fixtures_doc.get("fixtures", [])
    catalog_ids = {f["match_id"] for f in catalog}
    matchday_by_id = {
        f["match_id"]: f.get("official_matchday") or f.get("simulation_matchday")
        for f in catalog
    }
    return catalog_ids, matchday_by_id


_OBSERVED = [
    {
        "status": "finished", "season": "2026/27", "match_id": "obs-1",
        "home_team": "Slavia Praha", "away_team": "Racing Club de Lens",
        "home_score": 2, "away_score": 3, "round_number": 1,
        "stage": "LEAGUE_STAGE",
    },
    {
        "status": "finished", "season": "2026/27", "match_id": "obs-2",
        "home_team": "Liverpool", "away_team": "Atletico Madrid",
        "home_score": 2, "away_score": 3, "round_number": 1,
        "stage": "LEAGUE_STAGE",
    },
    {
        "status": "finished", "season": "2026/27", "match_id": "obs-3",
        "home_team": "Bayern Munich", "away_team": "Bodo/Glimt",
        "home_score": 3, "away_score": 1, "round_number": 1,
        "stage": "LEAGUE_STAGE",
    },
]

_EXPECTED = {
    "obs-1": ("gen-ba37659c6fb64ab3", "Slavia Prague", "Lens", 2, 3),
    "obs-2": ("gen-5dec7b8731a863ee", "Liverpool", "Atlético Madrid", 2, 3),
    "obs-3": ("gen-d2698f08d77f9e47", "Bayern Munich", "Bodø/Glimt", 3, 1),
}


def test_observed_md1_events_ingest_exactly_once_and_complete_md1(tmp_path):
    """The three runtime-rejected finished events now attach exactly once to the
    canonical fixtures on a FRESH deterministic draw store; MD1's 18-slot layout
    holds the full matchday with the 3 ingested rows as the played overlay."""
    from competitions.ucl.src.pipeline import fetch_live_data
    from competitions.ucl.src.state import build_competition_state

    data_dir = _seeded_runtime(tmp_path)
    summary = fetch_live_data(data_dir, "", "", provider=_Provider(_OBSERVED))

    finished = summary["report"]["finished"]
    assert finished["received"] == 3
    assert finished["normalized"] == 3
    assert finished["ingested"] == 3
    assert finished["skipped_unmatchable"] == 0
    assert finished["skipped_no_target"] == 0
    assert finished["skipped_missing_score"] == 0

    results = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text(encoding="utf-8")
    )["matches"]
    assert len(results) == 3, "a fresh seeded store ingests exactly the 3 repaired events"
    ids = {m["match_id"] for m in results}
    assert len(ids) == len(results), "no duplicate result rows"
    for event_id, (fid, ta, tb, hs, as_expected) in _EXPECTED.items():
        row = next(m for m in results if m["match_id"] == fid)
        assert row["team_a"] == ta
        assert row["team_b"] == tb
        assert (row["home_score"], row["away_score"]) == (hs, as_expected)

    state = build_competition_state(data_dir, active_season="2026/27")
    matchdays = state["stages"]["league"]["matchdays"]
    assert set(matchdays) == {"MD01"}
    md1 = matchdays["MD01"]
    repaired_ids = {fid for fid, *_ in _EXPECTED.values()}
    assert len(md1) == 3, "MD01 lists only played rows (the 3 repaired fixtures)"
    assert repaired_ids == {m["match_id"] for m in md1}, \
        "the played MD01 rows are exactly the repaired canonical fixtures"

    # The 18-slot MD01 layout is the seeded (deterministic) schedule: 144
    # fixtures split into 8 matchdays of exactly 18 matches each, with the 3
    # ingested rows surfacing as the played MD01 overlay in the build state.
    fixtures_doc = json.loads(
        (data_dir / "seasons" / "2026_27" / "fixtures.json").read_text(encoding="utf-8")
    )
    assert len(fixtures_doc["fixtures"]) == 144, "draw catalog has 144 fixtures"
    schedule = fixtures_doc["schedule"]
    assert len(schedule["matchdays"]) == 8, "seeded schedule has 8 matchdays"
    assert all(len(md) == 18 for md in schedule["matchdays"]), \
        "seeded schedule assigns exactly 18 matches to every matchday"
    assert repaired_ids <= {f["match_id"] for f in fixtures_doc["fixtures"]}, \
        "the 3 repaired fixtures belong to the drawn catalog"


def test_racing_club_de_lens_is_an_observed_alias_of_lens():
    """The exact provider spelling from the rejection log now normalizes."""
    from football_core.fetcher import _build_alias_lookup, normalize_team

    aliases = json.loads((UCL_DATA / "team_aliases.json").read_text(encoding="utf-8"))
    lookup = _build_alias_lookup(aliases, [])
    assert normalize_team("Racing Club de Lens", lookup) == "Lens"


def test_results_upsert_folds_unaccented_spellings_onto_canonical_fixture(
    tmp_path,
):
    """The defensive layer: even when a spelling bypasses season-lookup
    seeding (raw unaccented ``Bodo/Glimt``), the results pair-matching lands
    on the catalog's ``Bodø/Glimt`` identity and updates it in place."""
    from competitions.ucl.src.ingest import _upsert_season_results

    data_dir = _seeded_runtime(tmp_path)
    added, updated, no_target, missing = _upsert_season_results(
        data_dir,
        "2026/27",
        [
            {
                "status": "finished", "season": "2026/27", "match_id": "d1",
                "home_team": "Bayern Munich", "away_team": "Bodo/Glimt",
                "home_score": 4, "away_score": 2,
            },
        ],
        "test",
    )
    assert (added, updated, no_target, missing) == (1, 0, 0, 0)
    results = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text(encoding="utf-8")
    )["matches"]
    assert len(results) == 1, "fresh store gains exactly one row for the upserted result"
    row = next(m for m in results if m["match_id"] == "gen-d2698f08d77f9e47")
    assert row["team_b"] == "Bodø/Glimt", "canonical catalog spelling is stored, not the raw ASCII form"
    assert (row["home_score"], row["away_score"]) == (4, 2)


def test_phantom_pair_outside_catalog_stays_no_target(tmp_path):
    """Validation is NOT weakened: a finished, scored event with no fixture in
    the active catalog is still rejected, not silently recorded."""
    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _seeded_runtime(tmp_path)
    events = [
        {
            "status": "finished", "season": "2026/27", "match_id": "phantom",
            "home_team": "Club Brugge", "away_team": "Manchester United",
            "home_score": 1, "away_score": 0, "round_number": 1,
            "stage": "LEAGUE_STAGE",
        },
    ]
    summary = fetch_live_data(data_dir, "", "", provider=_Provider(events))
    season = summary["per_season"]["2026/27"]
    assert season["results_added"] == 0
    assert season["skipped_no_target"] == 1
    results = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text(encoding="utf-8")
    )["matches"]
    assert all(m.get("match_id") != "phantom" for m in results)


def test_rerun_is_idempotent_no_new_rows_or_score_changes(tmp_path):
    """A fresh seeded store ingests the three events exactly once: the first
    run adds 3 rows, the rerun adds and updates nothing, and the on-disk
    results ledger is byte-identical between runs."""
    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _seeded_runtime(tmp_path)
    results_path = data_dir / "seasons" / "2026_27" / "results.json"
    first = fetch_live_data(data_dir, "", "", provider=_Provider(_OBSERVED))

    assert first["per_season"]["2026/27"]["results_added"] == 3
    first_bytes = results_path.read_bytes()

    second = fetch_live_data(data_dir, "", "", provider=_Provider(_OBSERVED))
    second_season = second["per_season"]["2026/27"]
    assert second_season["results_added"] == 0
    assert second_season["results_updated"] == 0
    assert results_path.read_bytes() == first_bytes, (
        "idempotent rerun leaves results.json byte-identical "
        "(same 3 rows, same ids and scores)"
    )


def test_failed_events_share_the_same_fixture_ids_as_the_draw(tmp_path):
    """The three results reference the SAME gen-* identities the official
    catalog uses, so the matchday grouping and presentation are consistent."""
    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _seeded_runtime(tmp_path)

    fixtures = json.loads(
        (data_dir / "seasons" / "2026_27" / "fixtures.json").read_text(encoding="utf-8")
    )["fixtures"]
    catalog_ids = {f["match_id"] for f in fixtures}
    assert all(
        fid in catalog_ids for fid, *_ in _EXPECTED.values()
    ), "results must attach to catalog fixture identities"

    fetch_live_data(data_dir, "", "", provider=_Provider(_OBSERVED))
    results = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text(encoding="utf-8")
    )["matches"]
    assert {m["match_id"] for m in results} <= catalog_ids, \
        "no result may carry an id that is not an official catalog fixture"


def test_persisted_2026_27_store_has_complete_finished_md1(tmp_path):
    """Persisted-store integrity guard: when the live 2026/27 results store is
    present on this machine, it must hold a complete 18-match finished MD1 with
    distinct catalog ids, including the three repaired rows at their true
    recovered on-disk scores. When the store has not been generated on this
    checkout it is skipped, not failed."""
    results_path = UCL_DATA / "seasons" / "2026_27" / "results.json"
    if not results_path.exists():
        pytest.skip("2026/27 results store not present — runtime-generated on this checkout")

    fixtures_path = UCL_DATA / "seasons" / "2026_27" / "fixtures.json"
    if fixtures_path.exists():
        catalog_ids, matchday_by_id = _catalog_index(
            json.loads(fixtures_path.read_text(encoding="utf-8"))
        )
    else:
        data_dir = _seeded_runtime(tmp_path)
        fixtures_doc = json.loads(
            (data_dir / "seasons" / "2026_27" / "fixtures.json").read_text(encoding="utf-8")
        )
        catalog_ids, matchday_by_id = _catalog_index(fixtures_doc)

    matches = json.loads(results_path.read_text(encoding="utf-8"))["matches"]
    match_ids = [m["match_id"] for m in matches]
    assert len(set(match_ids)) == len(match_ids), "all result ids are distinct"
    assert all(i.startswith("gen-") for i in match_ids), "all rows carry canonical gen-* ids"
    unknown_ids = [i for i in match_ids if i not in catalog_ids]
    assert not unknown_ids, f"result rows outside the committed catalog: {unknown_ids}"

    # Only rows on official matchday 1 are counted: the guard is
    # forward-compatible (MD2+ results will arrive later in the season), while
    # still failing loudly if the recovered 18-MD1 result set ever regresses.
    md1_matches = [m for m in matches if matchday_by_id.get(m["match_id"]) == 1]
    assert len(md1_matches) == 18, f"complete finished MD1: expected 18 result rows on MD1, got {len(md1_matches)}"

    expected_recovered = {
        "gen-ba37659c6fb64ab3": ("Slavia Prague", "Lens", 2, 3),
        "gen-5dec7b8731a863ee": ("Liverpool", "Atlético Madrid", 2, 1),
        "gen-d2698f08d77f9e47": ("Bayern Munich", "Bodø/Glimt", 5, 0),
    }
    rows_by_id = {m["match_id"]: m for m in matches}
    for fid, (ta, tb, home_score, away_score) in expected_recovered.items():
        assert fid in rows_by_id, f"repaired fixture {fid} missing from persisted store"
        row = rows_by_id[fid]
        assert row["team_a"] == ta
        assert row["team_b"] == tb
        assert (row["home_score"], row["away_score"]) == (home_score, away_score)