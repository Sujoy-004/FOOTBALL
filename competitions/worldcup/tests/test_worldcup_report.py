"""Tests for the World Cup evaluation driver.

Pins the WC-specific behaviour: the weight-key mapping, the confidence-ECE
choice (D-10), the honest-failure path (D-04), and the absence of fabricated
numbers or significance wording. All tests use ``tmp_path`` synthetic data or
the honest-failure path — none depend on live acquisition numbers.
"""

from __future__ import annotations

import json
import os

import pytest

from competitions.worldcup.historical_backfill import evaluate


# ─────────────────────────── helpers ───────────────────────────


def _make_match(
    match_id: str,
    team_a: str,
    team_b: str,
    home_score: int,
    away_score: int,
    event_date: str,
    *,
    odds: tuple[float, float, float] | None = None,
    round_label: str = "group",
    stage: str = "group",
    winner: str | None = None,
    pk_winner: str | None = None,
) -> dict:
    """Build a minimal match dict for the synthetic corpus."""
    m: dict = {
        "match_id": match_id,
        "team_a": team_a,
        "team_b": team_b,
        "home_score": home_score,
        "away_score": away_score,
        "event_date": event_date,
        "round": round_label,
        "stage": stage,
        "winner": winner,
        "pk_winner": pk_winner,
    }
    if odds is not None:
        m["odds_home"] = odds[0]
        m["odds_draw"] = odds[1]
        m["odds_away"] = odds[2]
    return m


def _write_season(
    base_dir: str,
    season: str,
    matches: list[dict],
    elo: dict[str, float] | None = None,
) -> None:
    """Write a minimal season dataset (matches.json + elo_ratings.json + PROVENANCE.json)."""
    season_dir = os.path.join(base_dir, season)
    os.makedirs(season_dir, exist_ok=True)
    with open(os.path.join(season_dir, "matches.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "season": season, "matches": matches}, f)
    with open(os.path.join(season_dir, "elo_ratings.json"), "w", encoding="utf-8") as f:
        json.dump(elo or {}, f)
    with open(os.path.join(season_dir, "PROVENANCE.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "season": season}, f)


def _build_synthetic_corpus(base_dir: str) -> None:
    """Build a tiny two-season corpus straddling the 2020-12-31 cutoff.

    2002 season: 5 matches in 2002 (train side).
    2026 season: 5 matches in 2026 (test side).
    All matches carry odds so the market-only baseline is computable.
    """
    teams_2002 = ["Brazil", "Germany", "Argentina", "France", "Spain"]
    teams_2026 = ["Argentina", "France", "Brazil", "Germany", "Spain"]

    matches_2002 = []
    for i in range(5):
        matches_2002.append(
            _make_match(
                f"2002_m{i + 1:03d}",
                teams_2002[i],
                teams_2002[(i + 1) % 5],
                2,
                1,
                f"2002-06-{10 + i:02d}T15:00:00Z",
                odds=(1.8, 3.4, 4.2),
            )
        )

    matches_2026 = []
    for i in range(5):
        matches_2026.append(
            _make_match(
                f"2026_m{i + 1:03d}",
                teams_2026[i],
                teams_2026[(i + 1) % 5],
                1,
                0,
                f"2026-06-{15 + i:02d}T15:00:00Z",
                odds=(2.1, 3.6, 3.8),
            )
        )

    _write_season(base_dir, "2002", matches_2002)
    _write_season(base_dir, "2026", matches_2026)


# ─────────────────────────── tests ───────────────────────────


class TestWCWeights:
    def test_wc_weights_maps_and_drops(self):
        """wc_weights() returns the mapped dict (no elo, no squad_value)."""
        w = evaluate.wc_weights()
        assert "elo" not in w
        assert "squad_value" not in w
        assert "refined_elo" in w
        assert set(w.keys()) == {"refined_elo", "market_odds", "rolling_form", "rest_days"}
        # All values should be 0.2 (uniform)
        for v in w.values():
            assert v == pytest.approx(0.2)

    def test_wc_weights_raises_on_unexpected_key(self, tmp_path, monkeypatch):
        """An unexpected key in the config raises ValueError."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "signal_weights.json"
        config_file.write_text(
            json.dumps({"weights": {"elo": 0.2, "market_odds": 0.2, "rolling_form": 0.2,
                                     "squad_value": 0.2, "rest_days": 0.2, "unknown_signal": 0.1}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(evaluate, "CONFIG_DIR", str(config_dir))
        with pytest.raises(ValueError, match="Unexpected weight key"):
            evaluate.wc_weights()


class TestHonestFailure:
    def test_honest_failure_emits_deferred(self, tmp_path):
        """run() on an empty dir writes deferred/provider-empty and fabricates nothing."""
        out_path = str(tmp_path / "eval_results.json")
        report_path = str(tmp_path / "EVALUATION.md")

        result = evaluate.run(
            historical_dir=str(tmp_path / "nonexistent"),
            out_path=out_path,
            report_path=report_path,
        )

        # Status dict
        assert result["status"] == "deferred/provider-empty"
        assert "reason" in result
        assert "excluded" in result

        # JSON artifact
        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["status"] == "deferred/provider-empty"

        # Report contains the literal
        with open(report_path, encoding="utf-8") as f:
            md = f.read()
        assert "deferred/provider-empty" in md

        # No matches.json or any dataset file was written under tmp_path
        for root, _dirs, files in os.walk(tmp_path):
            for fname in files:
                assert fname != "matches.json", f"fabricated matches.json at {root}"
                assert "score" not in fname.lower()
                assert "date" not in fname.lower()


class TestReportPathUsesConfidenceECE:
    def test_report_path_uses_confidence_ece(self, tmp_path):
        """A synthetic corpus produces a report with the confidence-ECE label and no classwise."""
        corpus_dir = str(tmp_path / "historical")
        _build_synthetic_corpus(corpus_dir)

        out_path = str(tmp_path / "eval_results.json")
        report_path = str(tmp_path / "EVALUATION.md")

        evaluate.run(
            historical_dir=corpus_dir,
            out_path=out_path,
            report_path=report_path,
            seasons=["2002", "2026"],
        )

        with open(report_path, encoding="utf-8") as f:
            md = f.read()

        # Mandatory sections
        assert "## Declarations" in md
        assert "## Population counts" in md
        assert "## Cross-season results" in md
        assert "## Holdout" in md
        assert "## Disclosures" in md

        # Four D-17 disclosures (the renderer always includes 5, but the first 4 are the core)
        assert "4-signal surrogate" in md
        assert "Odds non-transfer" in md
        assert "Small-n ECE" in md
        assert "Brier" in md

        # market-only present
        assert "market-only" in md or "market_only" in md

        # ordered_brier present
        assert "ordered_brier" in md

        # "not a gate" note
        assert "not a gate" in md

        # D-16 verdict sentence
        assert "### Verdict" in md

        # Confidence-ECE label
        assert "confidence (multi_class_ece)" in md

        # Does NOT contain classwise for the WC block
        assert "classwise" not in md.lower() or "classwise_ece" not in md

    def test_no_invented_corpus(self, tmp_path):
        """The driver writes only under out_path/report_path and never creates dataset files."""
        corpus_dir = str(tmp_path / "historical")
        _build_synthetic_corpus(corpus_dir)

        out_path = str(tmp_path / "eval_results.json")
        report_path = str(tmp_path / "EVALUATION.md")

        evaluate.run(
            historical_dir=corpus_dir,
            out_path=out_path,
            report_path=report_path,
            seasons=["2002", "2026"],
        )

        # The driver should NOT have created any new files under corpus_dir
        # beyond what _build_synthetic_corpus already wrote
        for root, _dirs, files in os.walk(corpus_dir):
            for fname in files:
                assert fname in ("matches.json", "elo_ratings.json", "PROVENANCE.json"), \
                    f"unexpected file created: {fname}"

    def test_no_significance_wording(self, tmp_path):
        """The rendered text contains neither 'significantly' nor 'demonstrably'."""
        corpus_dir = str(tmp_path / "historical")
        _build_synthetic_corpus(corpus_dir)

        out_path = str(tmp_path / "eval_results.json")
        report_path = str(tmp_path / "EVALUATION.md")

        evaluate.run(
            historical_dir=corpus_dir,
            out_path=out_path,
            report_path=report_path,
            seasons=["2002", "2026"],
        )

        with open(report_path, encoding="utf-8") as f:
            md = f.read()

        assert "significantly" not in md
        assert "demonstrably" not in md
