"""Unit tests for the shared evaluation report renderer.

Pins every mandatory section, the disclosure text, the ÷3 statement, the
market-only comparison, the ordered-score block, the tournament-level TRPS
block (and its honest fallback), the verdict line, the recorded seed, and
the absence of significance wording.
"""

from __future__ import annotations

from football_core.evaluation_report import (
    DISCLOSURES,
    render_evaluation_markdown,
    render_disclosures,
)


def _make_results() -> dict:
    """Build a synthetic results dict that exercises every section."""
    return {
        "meta": {
            "generated_at": "2026-10-16T00:00:00Z",
            "dataset": "test/data (2019/20-2023/24)",
            "method": "replay: prior-only context",
            "seed": 20260601,
        },
        "per_season": {
            "2019_20": {
                "n": 380,
                "odds_n": 380,
                "elo_covered_n": 380,
                "all": {
                    "ensemble": {"n": 380, "log_loss": 1.01, "brier": 0.20, "ece": 0.07},
                    "uniform": {"n": 380, "uniform_log_loss": 1.0986, "uniform_brier": 0.2222},
                    "elo_only": {"n": 380, "log_loss": 1.10},
                },
                "odds": {
                    "n": 380,
                    "ensemble": {"n": 380, "log_loss": 1.01},
                    "market_odds_only": {"n": 380, "log_loss": 0.98},
                },
                "window": {
                    "freq": {"n": 114, "log_loss": 1.08},
                },
            },
            "2020_21": {
                "n": 380,
                "odds_n": 380,
                "elo_covered_n": 380,
                "all": {
                    "ensemble": {"n": 380, "log_loss": 1.01, "brier": 0.20, "ece": 0.04},
                    "uniform": {"n": 380, "uniform_log_loss": 1.0986, "uniform_brier": 0.2222},
                    "elo_only": {"n": 380, "log_loss": 1.10},
                },
                "odds": {
                    "n": 380,
                    "ensemble": {"n": 380, "log_loss": 1.01},
                    "market_odds_only": {"n": 380, "log_loss": 0.98},
                },
                "window": {
                    "freq": {"n": 114, "log_loss": 1.08},
                },
            },
        },
        "holdout": {
            "split": "single fixed chronological (D-02)",
            "cutoff": "2020-12-31T23:59:59Z",
            "n_train": 1000,
            "n_test": 144,
            # Real harness shape: the recorded seed lives under the bootstrap
            # block, not as a flat ``holdout["seed"]`` key.
            "bootstrap": {"n_boot": 2000, "seed": 20260601},
            "comparisons": {
                "ensemble_vs_uniform": {"delta": -0.08, "2.5": -0.12, "97.5": -0.04, "mde": 0.058, "n": 144},
                "ensemble_vs_freq": {"delta": -0.06, "2.5": -0.10, "97.5": -0.02, "mde": 0.058, "n": 144},
                "ensemble_vs_elo_only": {"delta": -0.07, "2.5": -0.11, "97.5": -0.03, "mde": 0.058, "n": 144},
                "ensemble_vs_market_only": {"delta": 0.03, "2.5": 0.01, "97.5": 0.05, "mde": 0.058, "n": 144},
            },
            "ordered": {
                "rps": 0.185,
                "ordered_brier": 0.0925,
                "order": ["home", "draw", "away"],
                "note": "secondary, not a gate",
            },
            "tournament_trps": {
                "trps": 0.042,
                "n_tournaments": 2,
                "per_tournament": [
                    {"season": "2021_22", "trps": 0.040},
                    {"season": "2022_23", "trps": 0.044},
                ],
                "construction": "teams ranked by summed test-match points",
                "order": "rank 1 = top",
                "note": "tournament-level TRPS block (roadmap criterion 1); secondary, not a gate",
            },
            "classwise_ece": {
                "home": 0.07,
                "draw": 0.06,
                "away": 0.08,
                "macro": 0.07,
                "withheld": [],
            },
            "verdict": {
                "verdict": "skill declared",
                "won_by": None,
                "mde": 0.058,
                "n": 144,
            },
        },
        "ablation": {
            "overall": {
                "n": 760,
                "full": {"n": 760, "log_loss": 1.01, "brier": 0.20, "ece": 0.06},
                "without_odds": {"n": 760, "log_loss": 1.05, "brier": 0.21, "ece": 0.07},
            },
        },
        "weights_learned": {
            "stability": {"vs_production": {"pearson": 0.458}},
            "per_season": {
                "2020/21": {
                    "train_pool_n": 380,
                    "weights": {"market_odds": 0.27, "refined_elo": 0.24, "rolling_form": 0.245, "rest_days": 0.243},
                    "evaluation": {"n": 380, "log_loss": 1.0129, "brier": 0.20, "ece": 0.07},
                },
            },
        },
    }


class TestMandatorySections:
    """Every mandatory section heading appears in the output."""

    def test_header(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "# UCL Out-of-Sample Model Evaluation" in md

    def test_population_counts(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "## Population counts" in md

    def test_cross_season_results(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "## Cross-season results" in md

    def test_holdout(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "## Holdout" in md

    def test_ordered_score(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "ordered_brier" in md

    def test_tournament_trps(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "Tournament-level TRPS" in md
        assert "n_tournaments" in md

    def test_calibration(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "## Calibration" in md

    def test_ablation(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "## Leave-one-signal-out ablation" in md

    def test_learned_weights(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "## Learned weights by training window" in md

    def test_verdict(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "### Verdict" in md
        assert "skill declared" in md

    def test_disclosures(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "## Disclosures" in md


class TestBaselineColumns:
    """The cross-season table prints the uniform-thirds baseline as a number."""

    def test_uniform_ll_is_rendered(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        # The uniform LL must be the harness key (``uniform_log_loss``), not a
        # defensive dash from looking up the wrong key.
        assert "1.0986" in md


class TestLearnedWeightsShape:
    """The learned-weights table reads weights_learned['per_season']."""

    def test_window_row_rendered(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "2020/21" in md
        assert "1.0129" in md  # the per-window evaluation.log_loss

    def test_stability_summary_not_rendered_as_window(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        # The sibling summary must not be printed as a fake window row.
        assert "| stability |" not in md
        assert "| per_season |" not in md


class TestDisclosures:
    """All four D-17 disclosures appear with stable substrings."""

    def test_squad_value_surrogate(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "squad_value" in md
        assert "4-signal" in md

    def test_odds_non_transfer(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "does not transfer" in md or "does **not** transfer" in md

    def test_small_n_ece_withheld(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "withheld" in md
        assert "20 observations" in md

    def test_brier_div_3(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "multi_class_brier" in md
        assert "÷3" in md or "divides by 3" in md
        assert "ordered_brier = rps/2" in md


class TestMarketOnly:
    """The market-only comparison is printed."""

    def test_market_only_in_comparisons(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "ensemble − market_only" in md or "market_only" in md

    def test_market_only_loss_printed(self):
        """When the ensemble loses to market-only, the loss is printed."""
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "Market-only loss" in md


class TestOrderedScore:
    """The ordered-score block contains ordered_brier and 'not a gate'."""

    def test_ordered_brier(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "ordered_brier" in md

    def test_not_a_gate(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "not a gate" in md


class TestTournamentTRPS:
    """The tournament-level TRPS block under its own heading."""

    def test_heading_distinct_from_ordered(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "Tournament-level TRPS" in md
        # The match-level heading must not collide
        assert "Match-level ordered score" in md

    def test_per_tournament_list(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "2021_22" in md
        assert "2022_23" in md

    def test_available_false_fallback(self):
        """An available:false block renders the reason, never blank."""
        results = _make_results()
        results["holdout"]["tournament_trps"] = {
            "available": False,
            "reason": "no tournament with ≥2 comparable teams on the test population",
        }
        md = render_evaluation_markdown(results, competition="UCL")
        assert "no tournament with ≥2 comparable teams" in md
        # Must not be an empty table
        assert "| Season | TRPS |" not in md


class TestVerdict:
    """The verdict line matches the D-16 rule."""

    def test_skill_declared(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "skill declared" in md

    def test_not_declared(self):
        results = _make_results()
        results["holdout"]["verdict"] = {
            "verdict": "not declared",
            "won_by": "market_only",
            "mde": 0.058,
            "n": 144,
        }
        md = render_evaluation_markdown(results, competition="UCL")
        assert "not declared" in md
        assert "market_only" in md


class TestSeed:
    """The recorded seed is printed, resolving the real harness shape."""

    def test_seed_printed(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "20260601" in md

    def test_seed_from_bootstrap_block(self):
        """The harness records the seed at ``holdout['bootstrap']['seed']``."""
        results = _make_results()
        results["meta"].pop("seed", None)
        # No flat holdout seed; only the bootstrap block carries it.
        assert "seed" not in results["holdout"]
        md = render_evaluation_markdown(results, competition="UCL")
        assert "20260601" in md

    def test_flat_seed_takes_precedence(self):
        results = _make_results()
        results["holdout"]["seed"] = 5551212
        md = render_evaluation_markdown(results, competition="UCL")
        assert "5551212" in md


class TestNoSignificanceWording:
    """The output contains neither 'significantly' nor 'demonstrably'."""

    def test_no_significantly(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "significantly" not in md

    def test_no_demonstrably(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "demonstrably" not in md


class TestDefensive:
    """A results dict missing holdout renders without raising."""

    def test_missing_holdout(self):
        results = _make_results()
        del results["holdout"]
        md = render_evaluation_markdown(results, competition="UCL")
        assert "—" in md  # defensive path renders em-dashes

    def test_missing_per_season(self):
        results = _make_results()
        del results["per_season"]
        md = render_evaluation_markdown(results, competition="UCL")
        assert "—" in md

    def test_empty_results(self):
        md = render_evaluation_markdown({}, competition="UCL")
        assert "—" in md


class TestNoPValue:
    """No p-value field is emitted."""

    def test_no_p_value(self):
        md = render_evaluation_markdown(_make_results(), competition="UCL")
        assert "p-value" not in md.lower() or "not a p-value" in md.lower()


class TestDisclosuresConstant:
    """The DISCLOSURES list has at least 4 entries."""

    def test_disclosures_count(self):
        assert len(DISCLOSURES) >= 4

    def test_render_disclosures(self):
        md = render_disclosures()
        assert "4-signal" in md
        assert "does not transfer" in md
        assert "withheld" in md
        assert "multi_class_brier" in md


class TestExtraDeclarations:
    """Extra declarations are rendered in their own section."""

    def test_extra_declarations(self):
        md = render_evaluation_markdown(
            _make_results(),
            competition="UCL",
            extra_declarations=["UCL ties are two-legged."],
        )
        assert "## Declarations" in md
        assert "two-legged" in md


class TestNoCompetitionsImport:
    """The module does not import competitions."""

    def test_no_imports(self):
        import football_core.evaluation_report as mod
        import inspect
        source = inspect.getsource(mod)
        assert "import competitions" not in source
