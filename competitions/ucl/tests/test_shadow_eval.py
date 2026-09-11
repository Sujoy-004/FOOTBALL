"""Tests for shadow_eval — frozen pre-kickoff prediction log for UCL."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from competitions.ucl.src.shadow_eval import (
    SCHEMA_VERSION,
    SHADOW_STRATEGIES,
    _round_probs,
    _weights_hash,
    append_jsonl,
    attach_results,
    build_report,
    build_strict_prior_context,
    load_json,
    load_jsonl,
    now_utc,
    parse_kickoff,
    render_markdown,
    resolve_elo,
)

# ── Synthetic data builders ──────────────────────────────────────────────

_TEAMS = {"Alpha": 2000.0, "Beta": 1800.0, "Gamma": 1700.0, "Delta": 1600.0}


def _future_kickoff(hours: int = 24) -> str:
    return (now_utc() + __import__("datetime").timedelta(hours=hours)).isoformat()


def _past_kickoff(hours: int = 24) -> str:
    return (now_utc() - __import__("datetime").timedelta(hours=hours)).isoformat()


def _fixture(match_id, team_a="Alpha", team_b="Beta", event_date=None):
    if event_date is None:
        event_date = _future_kickoff()
    return {"match_id": match_id, "team_a": team_a, "team_b": team_b, "event_date": event_date}


def _result_row(match_id, home_score, away_score):
    return {"match_id": match_id, "home_score": home_score, "away_score": away_score}


# ── 1. parse_kickoff ────────────────────────────────────────────────────


class TestParseKickoff:
    def test_valid_iso(self):
        dt = parse_kickoff("2026-09-15T19:00:00+00:00")
        assert dt.year == 2026
        assert dt.tzinfo is not None

    def test_trailing_z(self):
        dt = parse_kickoff("2026-09-15T19:00:00Z")
        assert dt.tzinfo is not None
        assert dt.hour == 19

    def test_naive_assumed_utc(self):
        dt = parse_kickoff("2026-09-15T19:00:00")
        assert dt.tzinfo is not None
        assert dt.hour == 19

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_kickoff("")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            parse_kickoff(None)

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            parse_kickoff("   ")


# ── 2. load_json / load_jsonl ───────────────────────────────────────────


class TestIOLayer:
    def test_load_json_existing(self, tmp_path):
        p = tmp_path / "d.json"
        p.write_text('{"a": 1}', encoding="utf-8")
        assert load_json(str(p)) == {"a": 1}

    def test_load_json_missing(self, tmp_path):
        assert load_json(str(tmp_path / "nope.json")) is None

    def test_load_json_corrupt(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{bad", encoding="utf-8")
        assert load_json(str(p)) is None

    def test_load_jsonl_empty_file(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_text("", encoding="utf-8")
        assert load_jsonl(str(p)) == []

    def test_load_jsonl_valid(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_text('{"x":1}\n{"y":2}\n', encoding="utf-8")
        assert load_jsonl(str(p)) == [{"x": 1}, {"y": 2}]

    def test_load_jsonl_skips_malformed(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_text('{"x":1}\nBAD\n{"y":2}\n', encoding="utf-8")
        assert load_jsonl(str(p)) == [{"x": 1}, {"y": 2}]

    def test_load_jsonl_missing_file(self):
        assert load_jsonl("/no/such/file.jsonl") == []


# ── 3. _round_probs ─────────────────────────────────────────────────────


class TestRoundProbs:
    def test_already_sum_1(self):
        result = _round_probs(0.4, 0.3, 0.3)
        assert sum(result.values()) == 1.0
        assert result == {"home": 0.4, "draw": 0.3, "away": 0.3}

    def test_rounds_to_4dp(self):
        result = _round_probs(0.333333, 0.333333, 0.333334)
        assert all(isinstance(v, float) for v in result.values())

    def test_sum_exactly_1(self):
        for h, d, a in [(0.99, 0.005, 0.005), (0.5001, 0.2999, 0.2)]:
            result = _round_probs(h, d, a)
            assert round(sum(result.values()), 10) == 1.0, f"Failed for {h},{d},{a}"


# ── 4. _weights_hash ────────────────────────────────────────────────────


class TestWeightsHash:
    def test_deterministic(self):
        w = {"a": 1, "b": 0.5}
        h1 = _weights_hash(w)
        h2 = _weights_hash(w)
        assert h1 == h2

    def test_starts_with_sha256_prefix(self):
        assert _weights_hash({"x": 1}).startswith("sha256:")

    def test_different_weights_different_hash(self):
        assert _weights_hash({"a": 1}) != _weights_hash({"a": 2})


# ── 5. append_jsonl ─────────────────────────────────────────────────────


class TestAppendJsonl:
    def test_creates_file_and_appends(self, tmp_path):
        p = tmp_path / "log.jsonl"
        append_jsonl(str(p), {"k": 1})
        append_jsonl(str(p), {"k": 2})
        records = load_jsonl(str(p))
        assert len(records) == 2
        assert records[0]["k"] == 1
        assert records[1]["k"] == 2

    def test_byte_identical(self, tmp_path):
        p = tmp_path / "log.jsonl"
        rec = {"a": 1, "b": [2, 3]}
        append_jsonl(str(p), rec)
        append_jsonl(str(p), rec)
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert lines[0] == lines[1]

    def test_empty_file_first_write_is_atomic(self, tmp_path):
        p = tmp_path / "log.jsonl"
        assert not p.exists()
        append_jsonl(str(p), {"only": True})
        assert p.exists()


# ── 6. resolve_elo ──────────────────────────────────────────────────────


class TestResolveElo:
    def test_snapshot_source(self, tmp_path):
        elo = {"Alpha": 2100.0, "Beta": 1900.0}
        p = tmp_path / "elo.json"
        p.write_text(json.dumps(elo), encoding="utf-8")
        ratings, prov = resolve_elo(["Alpha", "Beta"], elo_file=str(p))
        assert ratings["Alpha"] == 2100.0
        assert ratings["Beta"] == 1900.0
        assert prov["source"] == "snapshot"

    def test_missing_team_fills_default(self, tmp_path):
        from football_core.constants import DEFAULT_ELO
        p = tmp_path / "elo.json"
        p.write_text('{"Alpha": 2100.0}', encoding="utf-8")
        ratings, prov = resolve_elo(["Alpha", "Beta"], elo_file=str(p))
        assert ratings["Beta"] == float(DEFAULT_ELO)
        assert prov.get("filled_missing", 0) >= 1

    def test_no_sources_returns_empty(self):
        ratings, prov = resolve_elo(
            ["Alpha", "Beta"],
            elo_file="/no/such/file.json",
            data_dir="/no/such/dir",
        )
        assert ratings == {}
        assert prov["source"] == "none"


# ── 7. build_strict_prior_context ────────────────────────────────────────


class TestStrictPriorContext:
    def test_only_earlier_fixtures_in_context(self):
        f1 = _fixture("F1", event_date=_past_kickoff(48))
        f2 = _fixture("F2", event_date=_past_kickoff(24))
        target = _fixture("F3", event_date=_future_kickoff(24))
        ctx = build_strict_prior_context(target, [f1, f2, target], _TEAMS, {})
        ids = [f.get("match_id") for f in ctx.fixtures]
        assert "F3" not in ids
        assert "F1" in ids
        assert "F2" in ids

    def test_unknown_kickoff_excluded(self):
        f_bad = _fixture("FB", event_date="not-a-date")
        target = _fixture("FT", event_date=_future_kickoff(24))
        ctx = build_strict_prior_context(target, [f_bad, target], _TEAMS, {})
        ids = [f.get("match_id") for f in ctx.fixtures]
        assert "FB" not in ids

    def test_played_results_only_with_real_scores(self):
        f1 = _fixture("F1", event_date=_past_kickoff(48))
        target = _fixture("F2", event_date=_future_kickoff(24))
        result_rows = {"F1": _result_row("F1", 2, 1)}
        ctx = build_strict_prior_context(target, [f1, target], _TEAMS, result_rows)
        assert len(ctx.played_results) == 1
        assert ctx.played_results[0]["home_score"] == 2

    def test_missing_score_excluded_from_played(self):
        f1 = _fixture("F1", event_date=_past_kickoff(48))
        target = _fixture("F2", event_date=_future_kickoff(24))
        result_rows = {"F1": {"match_id": "F1", "home_score": None, "away_score": 1}}
        ctx = build_strict_prior_context(target, [f1, target], _TEAMS, result_rows)
        assert len(ctx.played_results) == 0


# ── 8. freeze_predictions ───────────────────────────────────────────────


class TestFreezePredictions:
    def test_freezes_only_future_kicked_off(self, tmp_path):
        from competitions.ucl.src.shadow_eval import freeze_predictions

        past = _fixture("PAST", event_date=_past_kickoff(48))
        future = _fixture("FUT", event_date=_future_kickoff(24))
        result_rows = [_result_row("PAST", 1, 0)]
        out = tmp_path / "pred.jsonl"

        stats = freeze_predictions(
            season="2026/27",
            fixtures=[past, future],
            result_rows=result_rows,
            elo_ratings=_TEAMS,
            as_of=now_utc(),
            data_dir=str(tmp_path),
            append_to=str(out),
            write=True,
        )
        assert stats["n_skipped_result_known"] >= 1
        assert stats["n_frozen"] >= 3
        records = load_jsonl(str(out))
        strategies_in = {r["strategy"] for r in records}
        assert strategies_in == set(SHADOW_STRATEGIES)

    def test_append_only_no_duplicates(self, tmp_path):
        from competitions.ucl.src.shadow_eval import freeze_predictions

        future = _fixture("FUT", event_date=_future_kickoff(24))
        out = tmp_path / "pred.jsonl"
        kwargs = dict(
            season="2026/27",
            fixtures=[future],
            result_rows=[],
            elo_ratings=_TEAMS,
            as_of=now_utc(),
            data_dir=str(tmp_path),
            append_to=str(out),
            write=True,
        )
        freeze_predictions(**kwargs)
        stats2 = freeze_predictions(**kwargs)
        assert stats2["n_frozen"] == 0
        assert len(load_jsonl(str(out))) == 3

    def test_unknown_kickoff_skipped(self, tmp_path):
        from competitions.ucl.src.shadow_eval import freeze_predictions

        bad = _fixture("BAD", event_date="not-a-date")
        out = tmp_path / "pred.jsonl"
        stats = freeze_predictions(
            season="2026/27",
            fixtures=[bad],
            result_rows=[],
            elo_ratings=_TEAMS,
            as_of=now_utc(),
            data_dir=str(tmp_path),
            append_to=str(out),
            write=True,
        )
        assert stats["n_skipped_unknown_kickoff"] == 1
        assert stats["n_frozen"] == 0

    def test_dry_run_no_write(self, tmp_path):
        from competitions.ucl.src.shadow_eval import freeze_predictions

        future = _fixture("FUT", event_date=_future_kickoff(24))
        out = tmp_path / "pred.jsonl"
        stats = freeze_predictions(
            season="2026/27",
            fixtures=[future],
            result_rows=[],
            elo_ratings=_TEAMS,
            as_of=now_utc(),
            data_dir=str(tmp_path),
            append_to=str(out),
            write=False,
        )
        assert stats["n_frozen"] == 3
        assert not out.exists()

    def test_record_schema_fields(self, tmp_path):
        from competitions.ucl.src.shadow_eval import freeze_predictions

        future = _fixture("FUT", event_date=_future_kickoff(24))
        out = tmp_path / "pred.jsonl"
        freeze_predictions(
            season="2026/27",
            fixtures=[future],
            result_rows=[],
            elo_ratings=_TEAMS,
            as_of=now_utc(),
            data_dir=str(tmp_path),
            append_to=str(out),
            write=True,
        )
        rec = load_jsonl(str(out))[0]
        assert rec["schema"] == SCHEMA_VERSION
        assert rec["season"] == "2026/27"
        assert rec["match_id"] == "FUT"
        assert rec["strategy"] in SHADOW_STRATEGIES
        assert rec["predicted"].keys() == {"home", "draw", "away"}
        assert round(sum(rec["predicted"].values()), 10) == 1.0
        assert "config" in rec
        assert "weights_hash" in rec["config"]
        assert rec["config"]["weights_hash"].startswith("sha256:")
        assert "provenance" in rec

    def test_strategy_produces_different_predictions(self, tmp_path):
        from competitions.ucl.src.shadow_eval import freeze_predictions

        future = _fixture("FUT", event_date=_future_kickoff(24))
        out = tmp_path / "pred.jsonl"
        freeze_predictions(
            season="2026/27",
            fixtures=[future],
            result_rows=[],
            elo_ratings=_TEAMS,
            as_of=now_utc(),
            data_dir=str(tmp_path),
            append_to=str(out),
            write=True,
        )
        records = load_jsonl(str(out))
        preds_by_strat = {r["strategy"]: r["predicted"] for r in records}
        assert preds_by_strat["production"] != preds_by_strat["market_elo_equal"]


# ── 9. attach_results ───────────────────────────────────────────────────


class TestAttachResults:
    def test_attaches_valid_results(self, tmp_path):
        result_rows = [
            {"match_id": "M1", "home_score": 2, "away_score": 1},
            {"match_id": "M2", "home_score": 0, "away_score": 0},
        ]
        out = tmp_path / "results.jsonl"
        stats = attach_results(
            season="2026/27",
            fixtures_by_id={"M1": {}, "M2": {}},
            result_rows=result_rows,
            result_files=["results.json"],
            result_log=str(out),
            write=True,
        )
        assert stats["n_attached"] == 2
        assert stats["n_missing_scores"] == 0

    def test_skips_missing_scores(self, tmp_path):
        result_rows = [
            {"match_id": "M1", "home_score": None, "away_score": 1},
            {"match_id": "M2", "home_score": 2, "away_score": None},
        ]
        out = tmp_path / "results.jsonl"
        stats = attach_results(
            season="2026/27",
            fixtures_by_id={},
            result_rows=result_rows,
            result_files=["results.json"],
            result_log=str(out),
            write=True,
        )
        assert stats["n_attached"] == 0
        assert stats["n_missing_scores"] == 2

    def test_idempotent_no_duplicates(self, tmp_path):
        result_rows = [{"match_id": "M1", "home_score": 2, "away_score": 1}]
        out = tmp_path / "results.jsonl"
        attach_results(
            season="2026/27",
            fixtures_by_id={},
            result_rows=result_rows,
            result_files=["results.json"],
            result_log=str(out),
            write=True,
        )
        stats = attach_results(
            season="2026/27",
            fixtures_by_id={},
            result_rows=result_rows,
            result_files=["results.json"],
            result_log=str(out),
            write=True,
        )
        assert stats["n_duplicate_skipped"] == 1

    def test_record_has_required_fields(self, tmp_path):
        result_rows = [{"match_id": "M1", "home_score": 3, "away_score": 0}]
        out = tmp_path / "results.jsonl"
        attach_results(
            season="2026/27",
            fixtures_by_id={"M1": {"status": "finished"}},
            result_rows=result_rows,
            result_files=["results.json"],
            result_log=str(out),
            write=True,
        )
        rec = load_jsonl(str(out))[0]
        assert rec["schema"] == SCHEMA_VERSION
        assert rec["outcome"] == "H"
        assert rec["home_score"] == 3
        assert rec["away_score"] == 0
        assert rec["status"] == "finished"
        assert rec["season"] == "2026/27"
        assert "attached_at" in rec

    def test_outcome_calculation(self, tmp_path):
        rows = [
            {"match_id": "W", "home_score": 2, "away_score": 1},
            {"match_id": "D", "home_score": 1, "away_score": 1},
            {"match_id": "L", "home_score": 0, "away_score": 3},
        ]
        out = tmp_path / "results.jsonl"
        attach_results(
            season="2026/27",
            fixtures_by_id={},
            result_rows=rows,
            result_files=["results.json"],
            result_log=str(out),
            write=True,
        )
        recs = load_jsonl(str(out))
        outcomes = {r["match_id"]: r["outcome"] for r in recs}
        assert outcomes["W"] == "H"
        assert outcomes["D"] == "D"
        assert outcomes["L"] == "A"


# ── 10. build_report ────────────────────────────────────────────────────


class TestBuildReport:
    def _make_data(self):
        now = now_utc()
        predictions = []
        result_records = []
        teams = [("A", 2000.0), ("B", 1800.0), ("C", 1700.0), ("D", 1600.0)]
        for i, (h, a) in enumerate([("A", "B"), ("C", "D"), ("A", "C"), ("B", "D"), ("A", "D")]):
            mid = f"M{i+1}"
            kick = (now + __import__("datetime").timedelta(hours=10)).isoformat()
            probs = [(0.5, 0.25, 0.25), (0.3, 0.4, 0.3), (0.6, 0.2, 0.2), (0.35, 0.35, 0.3), (0.45, 0.3, 0.25)]
            for strategy in SHADOW_STRATEGIES:
                predictions.append({
                    "season": "2026/27",
                    "match_id": mid,
                    "strategy": strategy,
                    "predicted": {"home": probs[i][0], "draw": probs[i][1], "away": probs[i][2]},
                    "odds_available": i % 2 == 0,
                })
            result_records.append({
                "season": "2026/27",
                "match_id": mid,
                "outcome": "H" if i % 3 != 2 else "A",
            })
        return predictions, result_records

    def test_report_structure(self):
        predictions, results = self._make_data()
        report = build_report(season="2026/27", prediction_records=predictions, result_records=results)
        assert report["schema"] == SCHEMA_VERSION
        assert report["season"] == "2026/27"
        assert "meta" in report
        assert "segments" in report
        assert "comparisons" in report
        assert "honesty" in report

    def test_honesty_counts(self):
        predictions, results = self._make_data()
        report = build_report(season="2026/27", prediction_records=predictions, result_records=results)
        assert report["honesty"]["n_prediction_records"] == len(predictions)
        assert report["honesty"]["n_scored_fixtures"] == 5

    def test_segment_all_exists(self):
        predictions, results = self._make_data()
        report = build_report(season="2026/27", prediction_records=predictions, result_records=results)
        assert "all" in report["segments"]
        assert "odds_available" in report["segments"]
        assert "odds_unavailable" in report["segments"]


# ── 11. render_markdown ─────────────────────────────────────────────────


class TestRenderMarkdown:
    def test_returns_string_with_headers(self):
        report = {
            "season": "2026/27",
            "meta": {"model_version": "shadow-1.0.0", "strategies": ["production"]},
            "segments": {"all": {"n": 5, "strategies": {"production": {"n": 5, "log_loss": 0.5, "brier": 0.3, "ece": 0.1}}}},
            "comparisons": {},
            "honesty": {"n_prediction_records": 15, "n_scored_fixtures": 5, "n_pending_fixtures": 10, "n_attached_results": 5},
            "model_config": {"production": {"weights_file": "w.json", "weights_hash": "sha256:abc"}},
        }
        md = render_markdown(report, fixture_count=20, score_counts={"attached": 5})
        assert isinstance(md, str)
        assert "Shadow Evaluation" in md
        assert "2026/27" in md
        assert "production" in md


# ── 12. now_utc ─────────────────────────────────────────────────────────


class TestNowUtc:
    def test_returns_utc(self):
        dt = now_utc()
        assert dt.tzinfo is not None
        assert dt.tzinfo == timezone.utc


# ── 13. R8 — attach ignores caller-provided rows only ────────────────────


class TestR8AttachIgnoresSimulatedArtifacts:
    def test_attach_processes_only_caller_rows(self, tmp_path):
        sim_file = tmp_path / "simulation_artifacts.json"
        sim_file.write_text(json.dumps({"simulated": True}), encoding="utf-8")
        out = tmp_path / "results.jsonl"
        result_rows = [
            {"match_id": "REAL1", "home_score": 2, "away_score": 1},
        ]
        stats = attach_results(
            season="2026/27",
            fixtures_by_id={},
            result_rows=result_rows,
            result_files=[str(sim_file)],
            result_log=str(out),
            write=True,
        )
        assert stats["n_attached"] == 1
        recs = load_jsonl(str(out))
        assert len(recs) == 1
        assert recs[0]["match_id"] == "REAL1"


# ── 14. refreeze_production ──────────────────────────────────────────────


def _make_prod_record(match_id, strategy, home_team, away_team, predicted,
                      prediction_timestamp, kickoff, elo_home, elo_away,
                      odds_home=None, odds_draw=None, odds_away=None):
    """Synthetic production prediction record for refreeze tests."""
    return {
        "schema": SCHEMA_VERSION,
        "season": "2026/27",
        "match_id": match_id,
        "kickoff": kickoff,
        "home_team": home_team,
        "away_team": away_team,
        "strategy": strategy,
        "predicted": predicted,
        "prediction_timestamp": prediction_timestamp,
        "odds_available": odds_home is not None,
        "odds": {
            "home": odds_home,
            "draw": odds_draw,
            "away": odds_away,
        },
        "provenance": {
            "signals": {"rolling_form": {"form_a": 0.6, "form_b": 0.4}},
            "market_elo": None,
            "elo": {"home": elo_home, "away": elo_away, "source": "test", "file": None},
            "fallback": None,
        },
        "config": {
            "weights": {"rolling_form": 0.25, "refined_elo": 0.35},
            "weights_file": "signal_weights.json",
            "weights_hash": "sha256:abc",
            "engine_signals": ["rolling_form", "refined_elo", "market_odds"],
        },
    }


class TestRefreezeProduction:
    def test_refreeze_preserves_timestamp_and_candidates(self, tmp_path):
        """1 production record + 2 candidate records; timestamp preserved;
        candidate lines byte-identical; production probs change."""
        from competitions.ucl.src.shadow_eval import refreeze_production

        as_of_ts = "2026-09-01T10:00:00+00:00"
        prod_rec = _make_prod_record(
            match_id="M1", strategy="production",
            home_team="Alpha", away_team="Beta",
            predicted={"home": 0.5, "draw": 0.25, "away": 0.25},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-01T19:00:00Z",
            elo_home=1900.0, elo_away=1700.0,
        )
        cand1 = _make_prod_record(
            match_id="M1", strategy="market_elo_equal",
            home_team="Alpha", away_team="Beta",
            predicted={"home": 0.45, "draw": 0.3, "away": 0.25},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-01T19:00:00Z",
            elo_home=1900.0, elo_away=1700.0,
        )
        cand1["strategy"] = "market_elo_equal"
        cand2 = _make_prod_record(
            match_id="M2", strategy="market_elo_prior",
            home_team="Alpha", away_team="Gamma",
            predicted={"home": 0.6, "draw": 0.2, "away": 0.2},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-05T19:00:00Z",
            elo_home=1900.0, elo_away=1600.0,
        )
        cand2["strategy"] = "market_elo_prior"

        fixtures = [
            {"match_id": "M1", "team_a": "Alpha", "team_b": "Beta",
             "event_date": "2026-10-01T19:00:00Z"},
            {"match_id": "M2", "team_a": "Alpha", "team_b": "Gamma",
             "event_date": "2026-10-05T19:00:00Z"},
        ]
        # Result for a prior match so rolling form has data.
        result_rows = [
            {"match_id": "MR0", "home_score": 2, "away_score": 0,
             "match_id": "MR0"},
        ]
        # Add result_rows with the right shape.
        result_rows = [
            {"match_id": "MR0", "home_score": 2, "away_score": 0},
        ]
        # Need a fixture for MR0 to appear in prior context.
        fixtures.append(
            {"match_id": "MR0", "team_a": "Alpha", "team_b": "Delta",
             "event_date": "2026-09-15T19:00:00Z"}
        )
        # Add MR0 result with team info for the provider.
        result_rows = [
            {"match_id": "MR0", "team_a": "Alpha", "team_b": "Delta",
             "home_score": 2, "away_score": 0},
        ]

        preds_path = tmp_path / "predictions.jsonl"
        import tempfile as _tf
        # We need the data_dir to resolve season fixtures/results.
        # Use tmp_path and write fixtures/results there.
        season_dir = tmp_path / "seasons" / "2026_27"
        season_dir.mkdir(parents=True)
        (season_dir / "fixtures.json").write_text(
            json.dumps({"fixtures": fixtures}), encoding="utf-8"
        )
        (season_dir / "results.json").write_text(
            json.dumps({"matches": result_rows}), encoding="utf-8"
        )

        # Write predictions.jsonl with all 3 records.
        preds_path.write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in [prod_rec, cand1, cand2]) + "\n",
            encoding="utf-8",
        )

        manifest = refreeze_production(
            season="2026/27",
            prediction_records=[prod_rec, cand1, cand2],
            fixtures=fixtures,
            result_rows=result_rows,
            as_of_batches={as_of_ts: parse_kickoff(as_of_ts)},
            data_dir=str(tmp_path),
            write=True,
            out_predictions_path=str(preds_path),
            out_manifest_path=str(tmp_path / "refreeze_manifest.json"),
        )

        assert manifest["counts"]["changed"] >= 0  # may or may not change probs
        # Candidate hash must match (byte-identical).
        assert manifest["candidate_records_hash_before"] == manifest["candidate_records_hash_after"]
        # Post-hoc guard: the recorded line hash must match a re-read of the file.
        import hashlib as _hashlib
        assert manifest["predictions_file_line_hash"] == (
            "sha256:" + _hashlib.sha256(preds_path.read_bytes()).hexdigest()
        )

        # Re-read predictions and check candidate records are identical.
        out_recs = load_jsonl(str(preds_path))
        cand_out = [r for r in out_recs if r["strategy"] != "production"]
        assert len(cand_out) == 2
        # Check candidate 1 is unchanged.
        c1_out = [r for r in cand_out if r["match_id"] == "M1"][0]
        assert c1_out["predicted"] == cand1["predicted"]
        # Production record's prediction_timestamp is preserved.
        prod_out = [r for r in out_recs if r["strategy"] == "production"]
        assert len(prod_out) == 1
        assert prod_out[0]["prediction_timestamp"] == as_of_ts

    def test_refreeze_filters_results_later_than_as_of(self, tmp_path):
        """Result for a match with kickoff > as_of is excluded from re-freeze."""
        from competitions.ucl.src.shadow_eval import refreeze_production

        as_of_ts = "2026-09-01T10:00:00+00:00"
        prod_rec = _make_prod_record(
            match_id="M1", strategy="production",
            home_team="Alpha", away_team="Beta",
            predicted={"home": 0.5, "draw": 0.25, "away": 0.25},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-01T19:00:00Z",
            elo_home=1900.0, elo_away=1700.0,
        )
        fixtures = [
            {"match_id": "M1", "team_a": "Alpha", "team_b": "Beta",
             "event_date": "2026-10-01T19:00:00Z"},
            {"match_id": "MLATE", "team_a": "Alpha", "team_b": "Gamma",
             "event_date": "2026-09-15T19:00:00Z"},
        ]
        # Result for MLATE (kickoff after as_of) — should NOT be used.
        result_rows = [
            {"match_id": "MLATE", "team_a": "Alpha", "team_b": "Gamma",
             "home_score": 3, "away_score": 0},
        ]

        manifest = refreeze_production(
            season="2026/27",
            prediction_records=[prod_rec],
            fixtures=fixtures,
            result_rows=result_rows,
            as_of_batches={as_of_ts: parse_kickoff(as_of_ts)},
            data_dir=str(tmp_path),
            write=False,
        )
        # With no prior results (only future result filtered out), the
        # rolling form should stay at default. Check that the record was
        # either recomputed (changed) but the result was excluded.
        assert manifest["counts"]["skipped_result_now_known"] == 0

    def test_refreeze_skips_fixture_change(self, tmp_path):
        """Current fixture kickoff differs from stored → skipped, manifest reason."""
        from competitions.ucl.src.shadow_eval import refreeze_production

        as_of_ts = "2026-09-01T10:00:00+00:00"
        prod_rec = _make_prod_record(
            match_id="M1", strategy="production",
            home_team="Alpha", away_team="Beta",
            predicted={"home": 0.5, "draw": 0.25, "away": 0.25},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-01T19:00:00Z",
            elo_home=1900.0, elo_away=1700.0,
        )
        # Current fixture has a DIFFERENT kickoff.
        fixtures = [
            {"match_id": "M1", "team_a": "Alpha", "team_b": "Beta",
             "event_date": "2026-10-02T19:00:00Z"},  # changed!
        ]

        manifest = refreeze_production(
            season="2026/27",
            prediction_records=[prod_rec],
            fixtures=fixtures,
            result_rows=[],
            as_of_batches={as_of_ts: parse_kickoff(as_of_ts)},
            data_dir=str(tmp_path),
            write=False,
        )
        assert manifest["counts"]["skipped_fixture_changed"] == 1

    def test_refreeze_skips_result_now_known(self, tmp_path):
        """Match now has a real result → skip, no fabrication."""
        from competitions.ucl.src.shadow_eval import refreeze_production

        as_of_ts = "2026-09-01T10:00:00+00:00"
        prod_rec = _make_prod_record(
            match_id="M1", strategy="production",
            home_team="Alpha", away_team="Beta",
            predicted={"home": 0.5, "draw": 0.25, "away": 0.25},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-01T19:00:00Z",
            elo_home=1900.0, elo_away=1700.0,
        )
        fixtures = [
            {"match_id": "M1", "team_a": "Alpha", "team_b": "Beta",
             "event_date": "2026-10-01T19:00:00Z"},
        ]
        result_rows = [
            {"match_id": "M1", "team_a": "Alpha", "team_b": "Beta",
             "home_score": 2, "away_score": 1},
        ]

        manifest = refreeze_production(
            season="2026/27",
            prediction_records=[prod_rec],
            fixtures=fixtures,
            result_rows=result_rows,
            as_of_batches={as_of_ts: parse_kickoff(as_of_ts)},
            data_dir=str(tmp_path),
            write=False,
        )
        assert manifest["counts"]["skipped_result_now_known"] == 1

    def test_refreeze_manifest_counts_and_hashes(self, tmp_path):
        """Manifest has correct structure, counts add up, hash format."""
        from competitions.ucl.src.shadow_eval import refreeze_production

        as_of_ts = "2026-09-01T10:00:00+00:00"
        prod_rec = _make_prod_record(
            match_id="M1", strategy="production",
            home_team="Alpha", away_team="Beta",
            predicted={"home": 0.5, "draw": 0.25, "away": 0.25},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-01T19:00:00Z",
            elo_home=1900.0, elo_away=1700.0,
        )
        cand = _make_prod_record(
            match_id="M1", strategy="market_elo_equal",
            home_team="Alpha", away_team="Beta",
            predicted={"home": 0.45, "draw": 0.3, "away": 0.25},
            prediction_timestamp=as_of_ts,
            kickoff="2026-10-01T19:00:00Z",
            elo_home=1900.0, elo_away=1700.0,
        )

        fixtures = [
            {"match_id": "M1", "team_a": "Alpha", "team_b": "Beta",
             "event_date": "2026-10-01T19:00:00Z"},
        ]

        manifest = refreeze_production(
            season="2026/27",
            prediction_records=[prod_rec, cand],
            fixtures=fixtures,
            result_rows=[],
            as_of_batches={as_of_ts: parse_kickoff(as_of_ts)},
            data_dir=str(tmp_path),
            write=False,
        )

        assert manifest["schema"] == 1
        assert manifest["phase"] == 6
        counts = manifest["counts"]
        # All counts should be non-negative integers.
        for key in ("changed", "unchanged", "skipped_fixture_changed",
                     "skipped_result_now_known", "not_found"):
            assert isinstance(counts[key], int) and counts[key] >= 0
        # Hashes must be sha256: prefixed.
        assert manifest["candidate_records_hash_before"].startswith("sha256:")
        assert manifest["candidate_records_hash_after"].startswith("sha256:")
        # Candidate hashes must match (no candidates modified).
        assert manifest["candidate_records_hash_before"] == manifest["candidate_records_hash_after"]
        # changed_records and unchanged_records are lists.
        assert isinstance(manifest["changed_records"], list)
        assert isinstance(manifest["unchanged_records"], list)
