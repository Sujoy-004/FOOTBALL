"""Focused tests for the canonical domain contracts (football_core.domain).

Exchange 1: these lock down the semantics the whole multi-competition
architecture will rely on — played vs scheduled vs simulated, missing vs
empty vs unavailable stores — independent of any competition.
"""

import json

import pytest

from football_core.domain import (
    CanonicalMatch,
    DataAvailability,
    MatchStatus,
    ResultProvenance,
    canonical_from_result_entry,
    canonical_scheduled_match,
    canonical_simulated_result,
    effective_status,
    is_semantically_empty,
    load_json_store,
)


class TestMatchStatusSemantics:
    def test_effective_status_played_stays_played(self):
        assert (
            effective_status(MatchStatus.PLAYED, ResultProvenance.OFFICIAL)
            is MatchStatus.PLAYED
        )

    def test_effective_status_simulated_never_renders_as_played(self):
        assert (
            effective_status(MatchStatus.PLAYED, ResultProvenance.SIMULATED)
            is MatchStatus.SCHEDULED
        )
        assert (
            effective_status(MatchStatus.PLAYED_PENS, ResultProvenance.SIMULATED)
            is MatchStatus.SCHEDULED
        )

    def test_effective_status_accepts_raw_strings(self):
        assert effective_status("played", "official") is MatchStatus.PLAYED

    def test_is_played_fact_excludes_simulated(self):
        real = CanonicalMatch(
            match_id="m1", competition="X", home_team="A", away_team="B",
            status=MatchStatus.PLAYED, home_goals=1, away_goals=0,
        )
        sim = CanonicalMatch(
            match_id="m2", competition="X", home_team="A", away_team="B",
            status=MatchStatus.PLAYED, home_goals=2, away_goals=1,
            provenance=ResultProvenance.SIMULATED,
        )
        assert real.is_played_fact is True
        assert sim.is_played_fact is False


class TestCanonicalAdapters:
    def test_wc_group_entry_with_explicit_draw(self):
        entry = {
            "match_id": "GS_A_01", "team_a": "Mexico", "team_b": "South Africa",
            "winner": None, "is_draw": True, "home_score": 0, "away_score": 0,
            "completed_at": "2026-06-11T19:00:00Z",
        }
        m = canonical_from_result_entry(entry, "WC")
        assert m.status is MatchStatus.PLAYED
        assert m.winner is None
        assert m.home_goals == 0 and m.away_goals == 0
        assert m.kickoff_utc == "2026-06-11T19:00:00Z"

    def test_ucl_entry_without_winner_field_derives_it(self):
        entry = {
            "match_id": "MD01_01", "team_a": "Athletic Bilbao", "team_b": "Arsenal",
            "home_score": 0, "away_score": 2,
        }
        m = canonical_from_result_entry(entry, "UCL")
        assert m.status is MatchStatus.PLAYED
        assert m.winner == "Arsenal"
        # UCL ledger carries no timestamp: provenance degrades to MANUAL.
        assert m.provenance is ResultProvenance.MANUAL

    def test_level_score_with_winner_means_shootout(self):
        entry = {
            "match_id": "M88", "team_a": "Spain", "team_b": "Egypt",
            "winner": "Spain", "is_draw": False, "home_score": 1, "away_score": 1,
        }
        m = canonical_from_result_entry(entry, "WC")
        assert m.status is MatchStatus.PLAYED_PENS
        assert m.winner == "Spain"

    def test_null_scores_mean_scheduled(self):
        entry = {
            "match_id": "GS_B_02", "team_a": "France", "team_b": "Brazil",
            "winner": None, "score_a": None, "score_b": None,
        }
        m = canonical_from_result_entry(entry, "WC")
        assert m.status is MatchStatus.SCHEDULED
        assert m.winner is None
        assert m.home_goals is None and m.away_goals is None

    def test_winner_empty_string_normalizes_to_none(self):
        entry = {
            "match_id": "SF_1", "team_a": "A", "team_b": "B",
            "winner": "", "home_score": None, "away_score": None,
        }
        m = canonical_from_result_entry(entry, "UCL")
        assert m.winner is None
        assert m.status is MatchStatus.SCHEDULED

    def test_empty_completed_at_becomes_none(self):
        entry = {
            "match_id": "FINAL", "team_a": "Spain", "team_b": "Argentina",
            "winner": "Spain", "home_score": 1, "away_score": 0,
            "completed_at": "",
        }
        m = canonical_from_result_entry(entry, "WC")
        assert m.kickoff_utc is None
        assert m.provenance is ResultProvenance.MANUAL

    def test_scheduled_constructor(self):
        m = canonical_scheduled_match("GS_C_03", "WC", "A", "B", stage=None)
        assert m.status is MatchStatus.SCHEDULED
        assert m.provenance is ResultProvenance.OFFICIAL
        assert m.as_dict()["effective_status"] == "scheduled"

    def test_simulated_result_marks_provenance(self):
        m = canonical_simulated_result("MD09_01", "UCL", "A", "B", 3, 1)
        assert m.provenance is ResultProvenance.SIMULATED
        assert m.status is MatchStatus.PLAYED
        assert m.effective_status() is MatchStatus.SCHEDULED
        assert m.is_played_fact is False

    def test_simulated_penalty_decider(self):
        m = canonical_simulated_result(
            "r16_01", "UCL", "A", "B", 1, 1, pens_home=4, pens_away=3,
        )
        assert m.status is MatchStatus.PLAYED_PENS
        assert m.winner == "A"

    def test_as_dict_is_json_safe(self):
        m = canonical_from_result_entry(
            {"match_id": "x", "team_a": "A", "team_b": "B",
             "home_score": 2, "away_score": 2},
            "TEST",
        )
        payload = json.loads(json.dumps(m.as_dict()))
        assert payload["status"] == "played"
        assert payload["provenance"] == "manual"


class TestStoreAvailability:
    def test_missing_file(self, tmp_path):
        _, availability, detail = load_json_store(tmp_path / "nope.json")
        assert availability is DataAvailability.MISSING
        assert detail

    def test_available_file(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"matches": [{"id": 1}]}), encoding="utf-8")
        payload, availability, _ = load_json_store(p)
        assert availability is DataAvailability.AVAILABLE
        assert payload["matches"][0]["id"] == 1

    def test_present_but_empty_object_is_empty_not_available(self, tmp_path):
        p = tmp_path / "ko.json"
        p.write_text('{\n  "matches": {}\n}\n', encoding="utf-8")
        _, availability, _ = load_json_store(p)
        assert availability is DataAvailability.EMPTY

    def test_present_but_empty_list_is_empty(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("[]", encoding="utf-8")
        _, availability, _ = load_json_store(p)
        assert availability is DataAvailability.EMPTY

    def test_malformed_file_is_unavailable(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{not json", encoding="utf-8")
        payload, availability, detail = load_json_store(p)
        assert payload is None
        assert availability is DataAvailability.UNAVAILABLE
        assert "JSONDecodeError" in detail

    def test_zero_is_content_not_empty(self):
        assert is_semantically_empty({"count": 0}) is False

    def test_nested_wrapper_emptiness(self):
        assert is_semantically_empty({"matches": {}, "champion": ""}) is True
        assert is_semantically_empty({"playoff": [], "rounds": {"R16": []}}) is True
        assert is_semantically_empty({"rounds": {"R16": [{"id": 1}]}}) is False
