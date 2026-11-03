# -*- coding: utf-8 -*-
"""Kernel + adapter tests for the seed+replay Elo engine.

Covers the decision-10 coverage areas for ``football_core.elo_replay``:
seed-date filtering (strictly-after only, including the exactly-equal
boundary), the goal-difference K multiplier, 0.75/0.25 penalty-shootout
weighting, chronological ordering, missing-seed honesty, undated-row
skipping, invalid winner rows, and offline reproducibility (urlopen
poisoned — the kernel makes no network calls by construction).

All vectors are hand-computed from the ``update_ratings``/``compute_k_factor``
formulas and asserted exactly (1-decimal rounding).
"""

from __future__ import annotations

import copy

import pytest

from football_core.elo_replay import ReplayOutcome, replay_elo


def _row(team_a, team_b, hs, aws, date, **extra):
    row = {"team_a": team_a, "team_b": team_b,
           "home_score": hs, "away_score": aws, "date": date}
    row.update(extra)
    return row


# ── Seed-date filtering ────────────────────────────────────────────────────


class TestSeedDateFiltering:
    """Rows at-or-before the seed's as-of are skipped; strictly-after replay."""

    def test_strictly_after_row_is_replayed(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "2026-09-30",
            [_row("A", "B", 2, 0, "2026-10-01")], base_k=60,
        )
        # K = 60 * 1.5 (gd 2) = 90; expected 0.5 → +90*0.5
        assert outcome.ratings == {"A": 1545.0, "B": 1455.0}
        assert outcome.replayed == 1 and outcome.skipped == 0
        assert outcome.as_of == "2026-10-01"

    def test_boundary_row_dated_exactly_as_of_is_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "2026-10-01",
            [_row("A", "B", 2, 0, "2026-10-01")], base_k=60,
        )
        assert outcome.ratings == {"A": 1500.0, "B": 1500.0}
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_row_before_as_of_is_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "2026-10-05",
            [_row("A", "B", 3, 0, "2026-10-02")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_empty_seed_as_of_replays_every_dated_row(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 2, 0, "2026-10-01")], base_k=60,
        )
        assert outcome.ratings == {"A": 1545.0, "B": 1455.0}
        assert outcome.as_of == "2026-10-01"

    def test_as_of_is_lex_max_of_seed_and_latest_row(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "2026-12-01",
            [_row("A", "B", 2, 0, "2026-10-01")], base_k=60,
        )
        assert outcome.replayed == 0  # skipped: at-or-before
        assert outcome.as_of == "2026-12-01"

    def test_as_of_empty_when_neither_seed_nor_row_carries_a_date(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "", [_row("A", "B", 2, 0, "")], base_k=60,
        )
        assert outcome.as_of == ""
        assert outcome.replayed == 0 and outcome.skipped == 1


# ── Goal-difference multiplier + shootout weighting ───────────────────────


class TestKFactorScaling:
    """compute_k_factor's G multiplier scales the base K per row."""

    def test_one_goal_result_uses_base_k(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 1, 0, "2026-10-01")], base_k=30,
        )
        # base_k=30, G(gd≤1)=1.0 → K=30; expected 0.5 → +15.
        assert outcome.ratings == {"A": 1515.0, "B": 1485.0}

    def test_two_goal_result_multiplies_by_1_5(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 2, 0, "2026-10-01")], base_k=30,
        )
        # K = int(round(30 * 1.5)) = 45.
        assert outcome.ratings == {"A": 1522.5, "B": 1477.5}

    def test_big_goal_diff_uses_11_plus_gd_over_8(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 5, 0, "2026-10-01")], base_k=60,
        )
        # G = (11+5)/8 = 2.0 → K = 120.
        assert outcome.ratings == {"A": 1560.0, "B": 1440.0}


class TestShootoutWeighting:
    """pk_winner passes through to update_ratings' 0.75/0.25 result."""

    def test_pk_winner_takes_precedence(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 1, 1, "2026-10-01", winner="A", pk_winner="A")],
            base_k=60,
        )
        assert outcome.ratings == {"A": 1515.0, "B": 1485.0}
        assert outcome.replayed == 1

    def test_pk_winner_for_away_side(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 0, 0, "2026-10-01", winner="B", pk_winner="B")],
            base_k=60,
        )
        assert outcome.ratings == {"A": 1485.0, "B": 1515.0}


# ── Ordering ──────────────────────────────────────────────────────────────


class TestChronologicalOrdering:
    """Out-of-order input produces the same final ratings as sorted input.

    Elo updates are order-dependent, so this only matches when the kernel
    actually sorts by (date, team_a, team_b) before replaying.
    """

    _ROWS = [
        _row("A", "B", 2, 0, "2026-10-01"),   # A beats B, gd 2 → K 90
        _row("A", "C", 0, 3, "2026-10-02"),   # C beats A, gd 3 → K 105
        _row("B", "A", 1, 1, "2026-10-03"),   # draw
    ]

    def test_out_of_order_input_matches_sorted_input(self):
        seed = {"A": 1500.0, "B": 1500.0, "C": 1500.0}
        ordered = replay_elo(seed, "", self._ROWS, base_k=60)
        reversed_rows = list(reversed(self._ROWS))
        shuffled = replay_elo(seed, "", reversed_rows, base_k=60)
        assert ordered.ratings == shuffled.ratings
        assert ordered.replayed == shuffled.replayed == 3

    def test_expected_exact_chain(self):
        # Sorted chain, computed by hand with the update formula
        # (expected_a = 1/(1+10^((elo_b - elo_a)/400)), result 1/0.5/0,
        # rounded to 1 decimal per update_ratings):
        #   d1: A beats B, gd 2 → K = 90 → A 1545.0, B 1455.0
        #   d2: C beats A, gd 3 → K = int(round(60*(11+3)/8)) = 105
        #       expected_a = 1/(1+10^((1500-1545)/400)) = 0.564416
        #       A = 1545 - 105*0.564416 = 1485.7, C = 1500 + 105*0.564416 = 1559.3
        #   d3: B/A draw, K = 60 — A now rates 1485.7 vs B 1455.0
        #       expected_B = 1/(1+10^((1485.7-1455.0)/400)) = 0.455939
        #       B = 1455 + 60*(0.5-0.455939) = 1457.6 (gains: upset-ish draw)
        #       A = 1485.7 - 60*(0.5-0.455939) = 1483.1
        seed = {"A": 1500.0, "B": 1500.0, "C": 1500.0}
        ordered = replay_elo(seed, "", self._ROWS, base_k=60)
        assert ordered.ratings == {"A": 1483.1, "B": 1457.6, "C": 1559.3}
        # Final chain is deterministic — re-run gives byte-identical ratings.
        assert replay_elo(seed, "", self._ROWS, base_k=60).ratings == ordered.ratings


# ── Missing-seed honesty ─────────────────────────────────────────────────


class TestMissingSeedBehavior:
    """Rows naming unseeded teams are skipped; nothing is fabricated."""

    def test_unseeded_team_row_skipped(self):
        seed = {"A": 1500.0, "B": 1500.0}
        before = copy.deepcopy(seed)
        outcome = replay_elo(
            seed, "2026-01-01",
            [_row("A", "C", 3, 0, "2026-02-01")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1
        assert outcome.ratings == {"A": 1500.0, "B": 1500.0}
        assert seed == before, "the caller's seed dict must not be mutated"

    def test_no_candidates_run_to_completion(self):
        outcome = replay_elo({"A": 1500.0}, "", [], base_k=60)
        assert outcome.ratings == {"A": 1500.0}
        assert outcome.replayed == 0 and outcome.skipped == 0
        assert outcome.as_of == ""


# ── Invalid rows ─────────────────────────────────────────────────────────


class TestInvalidRowsSkipped:
    """Undated and inconsistent-winner rows fail closed."""

    def test_undated_row_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 2, 0, "")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_equal_scores_with_explicit_winner_and_no_pk_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 1, 1, "2026-10-01", winner="A")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_winner_against_score_direction_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 0, 2, "2026-10-01", winner="A")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_unknown_winner_token_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 1, 0, "2026-10-01", winner="Ghost")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_unknown_pk_winner_token_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", 1, 1, "2026-10-01", pk_winner="Ghost")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_non_numeric_scores_skipped(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("A", "B", None, 0, "2026-10-01")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_derived_winner_when_key_absent(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "",
            [_row("B", "A", 0, 2, "2026-10-01")], base_k=60,
        )
        # Winner-derived from scores: A won as the away-designated team_b.
        assert outcome.ratings["A"] == 1545.0


# ── Offline reproducibility ──────────────────────────────────────────────


class TestOfflineReproducibility:
    """No urlopen/socket usage: identical inputs → byte-identical outcome."""

    def test_kernel_runs_with_network_poisoned(self, monkeypatch):
        def _no_network(*_a, **_k):
            raise AssertionError("elo_replay must never touch the network")

        monkeypatch.setattr("urllib.request.urlopen", _no_network)
        monkeypatch.setattr("socket.socket", _no_network)
        seed = {"A": 1500.0, "B": 1500.0, "C": 1500.0}
        outcome = replay_elo(
            seed, "2026-01-01",
            self._ROWS if hasattr(self, "_ROWS") else
            [_row("A", "B", 2, 0, "2026-10-01")],
            base_k=60,
        )
        assert outcome.replayed >= 1

    def test_replay_frozen_dataclass_and_deterministic(self, monkeypatch):
        def _no_network(*_a, **_k):
            raise AssertionError("elo_replay must never touch the network")

        monkeypatch.setattr("urllib.request.urlopen", _no_network)
        rows = [_row("A", "B", 2, 0, "2026-10-01"),
                _row("B", "A", 1, 1, "2026-10-02")]
        seed = {"A": 1500.0, "B": 1500.0}
        one = replay_elo(seed, "2026-01-01", rows, base_k=30)
        two = replay_elo(seed, "2026-01-01", rows, base_k=30)
        assert one == two
        assert isinstance(one, ReplayOutcome)
        # Frozen dataclass: fields cannot be rebound.
        with pytest.raises(AttributeError):
            one.replayed = 99
