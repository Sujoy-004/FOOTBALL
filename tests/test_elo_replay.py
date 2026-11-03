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

    def test_bare_date_seed_skips_same_day_timestamped_row(self):
        """A bare-date seed covers its whole day: a timestamped row on that
        day is at-or-before the seed's precision and must not replay.
        """
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "2026-10-01",
            [_row("A", "B", 2, 0, "2026-10-01T21:00:00")], base_k=60,
        )
        assert outcome.replayed == 0 and outcome.skipped == 1

    def test_bare_date_seed_replays_next_day_timestamped_row(self):
        outcome = replay_elo(
            {"A": 1500.0, "B": 1500.0}, "2026-10-01",
            [_row("A", "B", 2, 0, "2026-10-02T12:00:00")], base_k=60,
        )
        assert outcome.replayed == 1 and outcome.skipped == 0

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


# ═════════════════════════════════════════════════════════════════════════════
# ── World Cup adapter: competitions/worldcup/src/elo_runtime.py ─────────────
# ═════════════════════════════════════════════════════════════════════════════


class TestWorldCupAdapter:
    """teams.json seed + played stores → replay_elo, mirroring apply_elo_update.

    Row contract mirrored from ``football_core.elo.apply_elo_update`` (locked):
    ``pk_winner`` carries the row winner ONLY when the row is decided
    (``is_draw`` False with a non-empty winner) — so every decided match
    weights 0.75/0.25 exactly as the locked predictor path does — and the
    per-row mean-reversion base is ``constants.K_FACTOR`` (60).
    """

    def _write_wc_data(self, dp, teams=None, played_groups=None, played=None):
        import json
        dp.mkdir(parents=True, exist_ok=True)
        (dp / "teams.json").write_text(
            json.dumps(teams if teams is not None else {}), encoding="utf-8")
        if played_groups is not None:
            (dp / "played_groups.json").write_text(
                json.dumps(played_groups), encoding="utf-8")
        if played is not None:
            (dp / "played.json").write_text(
                json.dumps(played), encoding="utf-8")

    def test_groups_win_replays_with_goal_diff_k(self, tmp_path):
        """2-0 win: K = int(round(60 * 1.5)) = 90 → A +45, B -45 (equal seed)."""
        self._write_wc_data(
            tmp_path,
            teams={"A": {"elo": 1500}, "B": {"elo": 1500}},
            played_groups={"GS_01": {
                "match_id": "GS_01", "team_a": "A", "team_b": "B",
                "winner": "A", "is_draw": False,
                "home_score": 2, "away_score": 0,
                "completed_at": "2026-06-11T19:00:00Z"}},
        )
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        ratings = computed_baseline_elos(tmp_path)
        # Locked apply_elo_update semantics: a decided row (is_draw False) is
        # a pk rewrite → 0.75/0.25, K = int(round(60*1.5)) = 90 → ±22.5.
        assert ratings == {"A": 1522.5, "B": 1477.5}

    def test_penalty_shootout_weights_075_025(self, tmp_path):
        """Decided matched-scores row → pk path: 0.75/0.25 (locked semantics)."""
        self._write_wc_data(
            tmp_path,
            teams={"A": {"elo": 1500}, "B": {"elo": 1500}},
            played={"R16_01": {
                "match_id": "R16_01", "team_a": "A", "team_b": "B",
                "winner": "A", "is_draw": False,
                "home_score": 1, "away_score": 1,
                "completed_at": "2026-06-28T19:00:00Z"}},
        )
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        ratings = computed_baseline_elos(tmp_path)
        # K(gd 0) = 60; result_a = 0.75 → A +60*0.25, B -15.
        assert ratings == {"A": 1515.0, "B": 1485.0}

    def test_draw_row_replays_without_score_change(self, tmp_path):
        """is_draw=True → result 0.5 with equal seed → ratings unchanged."""
        self._write_wc_data(
            tmp_path,
            teams={"A": {"elo": 1500}, "B": {"elo": 1500}},
            played_groups={"GS_02": {
                "match_id": "GS_02", "team_a": "A", "team_b": "B",
                "winner": None, "is_draw": True,
                "home_score": 1, "away_score": 1,
                "completed_at": "2026-06-12T19:00:00Z"}},
        )
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        ratings = computed_baseline_elos(tmp_path)
        assert ratings == {"A": 1500.0, "B": 1500.0}

    def test_mixed_stores_merge_and_absent_team_skipped(self, tmp_path):
        """Both stores feed the kernel; a team outside teams.json is skipped,
        never fabricated — its opponent's value still counts."""
        self._write_wc_data(
            tmp_path,
            teams={"A": {"elo": 1500}, "B": {"elo": 1500}},
            played_groups={"GS_03": {
                "match_id": "GS_03", "team_a": "A", "team_b": "B",
                "winner": "A", "is_draw": False,
                "home_score": 1, "away_score": 0,
                "completed_at": "2026-06-13T19:00:00Z"}},
            played={"R16_02": {
                "match_id": "R16_02", "team_a": "A", "team_b": "Ghost",
                "winner": "A", "is_draw": False,
                "home_score": 3, "away_score": 1,
                "completed_at": "2026-07-01T19:00:00Z"}},
        )
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        ratings = computed_baseline_elos(tmp_path)
        # K(1) = 60, pk rewrite (decided row) → ±0.25K = ±15; the Ghost row
        # is kernel-skipped (missing seed team).
        assert ratings == {"A": 1515.0, "B": 1485.0}

    def test_no_seed_file_yields_empty(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        assert computed_baseline_elos(tmp_path) == {}

    def test_missing_ratings_skipped_honestly(self, tmp_path):
        """A teams.json entry without a numeric elo is dropped from the seed
        (no 1500 fill); its rows are kernel-skipped and the surviving seed
        teams keep their (unreplayed) seed values.
        """
        self._write_wc_data(
            tmp_path,
            teams={"A": {"elo": 1500}, "B": {"pot": 2}},
            played={"R16_03": {
                "match_id": "R16_03", "team_a": "A", "team_b": "B",
                "winner": "A", "is_draw": False,
                "home_score": 2, "away_score": 0,
                "completed_at": "2026-07-02T19:00:00Z"}},
        )
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        assert computed_baseline_elos(tmp_path) == {"A": 1500.0}

    def test_teams_json_never_rewritten(self, tmp_path):
        """The seed file is a committed fact: the adapter never writes it."""
        self._write_wc_data(
            tmp_path,
            teams={"A": {"elo": 1500}, "B": {"elo": 1500}},
            played_groups={"GS_04": {
                "match_id": "GS_04", "team_a": "A", "team_b": "B",
                "winner": "A", "is_draw": False,
                "home_score": 2, "away_score": 0,
                "completed_at": "2026-06-11T19:00:00Z"}},
        )
        before = (tmp_path / "teams.json").read_text(encoding="utf-8")
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        computed_baseline_elos(tmp_path)
        assert (tmp_path / "teams.json").read_text(encoding="utf-8") == before

    def test_deterministic_across_calls(self, tmp_path):
        self._write_wc_data(
            tmp_path,
            teams={"A": {"elo": 1600}, "B": {"elo": 1500}},
            played={"R16_05": {
                "match_id": "R16_05", "team_a": "A", "team_b": "B",
                "winner": "B", "is_draw": False,
                "home_score": 0, "away_score": 2,
                "completed_at": "2026-07-03T19:00:00Z"}},
        )
        from competitions.worldcup.src.elo_runtime import computed_baseline_elos
        assert computed_baseline_elos(tmp_path) == computed_baseline_elos(tmp_path)


# ═════════════════════════════════════════════════════════════════════════════
# ── LaLiga adapter: competitions/laliga/src/pipeline (single code path) ─────
# ═════════════════════════════════════════════════════════════════════════════


class TestLaLigaAdapter:
    """elo_seed.json + season results → one _elo_replay path for all callers.

    The seed file is NEVER rewritten (committed input); provenance derives
    from the kernel's replayed count; only ``status == "finished"`` rows
    are candidates, with explicit winner pass-through.
    """

    def _write_seed(self, dp, ratings, snapshot_date="2026-09-21"):
        import json
        dp.mkdir(parents=True, exist_ok=True)
        (dp / "elo_seed.json").write_text(
            json.dumps({"snapshot_date": snapshot_date, "ratings": ratings}),
            encoding="utf-8")

    def test_missing_seed_is_unavailable(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [])
        ratings, provenance, as_of = lp._elo_replay(str(tmp_path))
        assert (ratings, provenance, as_of) == ({}, "unavailable", "")

    def test_corrupt_seed_is_unavailable(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "elo_seed.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [])
        ratings, provenance, as_of = lp._elo_replay(str(tmp_path))
        assert (ratings, provenance, as_of) == ({}, "unavailable", "")

    def test_finished_row_replays_after_seed_date(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        self._write_seed(tmp_path, {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0})
        row = {"match_id": "564635", "home_team": "FC Barcelona",
               "away_team": "Sevilla FC", "home_score": 3, "away_score": 1,
               "status": "finished", "winner": "FC Barcelona",
               "event_date": "2026-10-02T21:00:00"}
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [row])
        ratings, provenance, as_of = lp._elo_replay(str(tmp_path))
        assert provenance == "self_calculated"
        assert as_of == "2026-10-02T21:00:00"
        # gd 2 → G 1.5 → K = int(round(30*1.5)) = 45. Non-equal seed:
        # expected_a = 1/(1+10^((1580-1620)/400)) = 0.55731 →
        # Barcelona +45*0.44269 = +19.9, Sevilla -19.9.
        assert ratings["FC Barcelona"] == 1639.9
        assert ratings["Sevilla FC"] == 1560.1

    def test_non_finished_rows_never_replay(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        self._write_seed(tmp_path, {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0})
        row = {"match_id": "564636", "home_team": "FC Barcelona",
               "away_team": "Sevilla FC", "home_score": None, "away_score": None,
               "status": "scheduled", "winner": None,
               "event_date": "2026-10-02T21:00:00"}
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [row])
        ratings, provenance, _as_of = lp._elo_replay(str(tmp_path))
        assert provenance == "seeded"
        assert ratings == {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0}

    def test_undated_finished_row_fails_closed(self, tmp_path, monkeypatch):
        """A finished row without event_date cannot be chronologically placed
        against the seed — the kernel skips it (fail closed), provenance stays
        seeded."""
        import competitions.laliga.src.pipeline as lp

        self._write_seed(tmp_path, {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0})
        row = {"match_id": "564637", "home_team": "FC Barcelona",
               "away_team": "Sevilla FC", "home_score": 2, "away_score": 1,
               "status": "finished", "winner": "FC Barcelona",
               "event_date": ""}
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [row])
        ratings, provenance, _as_of = lp._elo_replay(str(tmp_path))
        assert provenance == "seeded"
        assert ratings == {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0}

    def test_seed_file_never_rewritten(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        self._write_seed(tmp_path, {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0})
        before = (tmp_path / "elo_seed.json").read_text(encoding="utf-8")
        row = {"match_id": "564638", "home_team": "FC Barcelona",
               "away_team": "Sevilla FC", "home_score": 2, "away_score": 0,
               "status": "finished", "winner": "FC Barcelona",
               "event_date": "2026-09-20"}  # at-or-before seed date → skipped
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [row])
        lp._elo_replay(str(tmp_path))
        assert (tmp_path / "elo_seed.json").read_text(encoding="utf-8") == before

    def test_row_before_seed_date_keeps_seed_values(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        self._write_seed(tmp_path, {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0})
        row = {"match_id": "564639", "home_team": "FC Barcelona",
               "away_team": "Sevilla FC", "home_score": 2, "away_score": 0,
               "status": "finished", "winner": "FC Barcelona",
               "event_date": "2026-09-21T21:00:00"}  # == snapshot date → skip
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [row])
        ratings, provenance, _as_of = lp._elo_replay(str(tmp_path))
        assert provenance == "seeded"
        assert ratings == {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0}

    def test_load_elo_ratings_value_view(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        self._write_seed(tmp_path, {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0})
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [])
        assert lp.load_elo_ratings(str(tmp_path)) == {
            "FC Barcelona": 1620.0, "Sevilla FC": 1580.0}

    def test_elo_source_reports_kernel_provenance(self, tmp_path, monkeypatch):
        import competitions.laliga.src.pipeline as lp

        self._write_seed(tmp_path, {"FC Barcelona": 1620.0, "Sevilla FC": 1580.0})
        monkeypatch.setattr(lp, "load_results", lambda *a, **k: [])
        assert lp.elo_source(str(tmp_path)) == {"provenance": "seeded", "as_of": "2026-09-21"}

