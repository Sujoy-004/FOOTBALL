"""UCL display functions — formatted output for simulation results.

D-17 (relaxed for Phase 8): Primarily imports from competitions.ucl.result
and stdlib. Signal types imported from football_core.signal for breakdown
and value-play display. No imports from competitions.ucl.src.

Exports:
    - print_summary(result: SimulationResult) -> None
    - print_league_table(result: SimulationResult) -> None
    - print_playoff_rounds(result: SimulationResult) -> None
    - print_knockout_bracket(result: SimulationResult) -> None
    - print_odds(result: SimulationResult) -> None
    - print_validation_summary(validation_result: dict) -> None
    - show_breakdown(blended_predictions, mode) -> None
    - print_value_plays(blended_predictions) -> None
    - _supports_color() -> bool
    - _ansi(code: str) -> callable
"""

from __future__ import annotations

import sys

from competitions.ucl.result import SimulationResult
from football_core.signal import BlendedPrediction

# ── Module-level constants ──────────────────────────────────────────────

NO_COLOR: bool = False  # Set by main.py when stdout is not a TTY
_SECTION_SEP: str = "=" * 60

# ANSI color codes (D-10: green=top_8, yellow=playoff, red=eliminated)
_GREEN: str = "32"
_YELLOW: str = "33"
_RED: str = "31"
_BOLD: str = "1"


# ── ANSI helpers ────────────────────────────────────────────────────────


def _supports_color() -> bool:
    """Return True if stdout is a TTY and NO_COLOR is not set (D-11)."""
    return sys.stdout.isatty() and not NO_COLOR


def _ansi(code: str):
    """Return a wrapper function that adds ANSI escape codes around text.

    If color is not supported, returns text unchanged.
    """
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper


_green = _ansi(_GREEN)      # top-8 zone
_yellow = _ansi(_YELLOW)    # playoff zone
_red = _ansi(_RED)          # eliminated zone
_bold = _ansi(_BOLD)        # section headings and column headers


def _zone_color(zone: str):
    """Return the ANSI color wrapper for a given qualification zone.

    Args:
        zone: One of "top_8", "playoff", "eliminated".

    Returns:
        A callable that wraps text in the zone's ANSI color,
        or the identity function for unknown zones.
    """
    if zone == "top_8":
        return _green
    elif zone == "playoff":
        return _yellow
    elif zone == "eliminated":
        return _red
    return lambda x: x  # identity for unknown zones


# ── Display functions (D-06: summary first, league table second) ────────


def print_summary(result: SimulationResult) -> None:
    """Print simulation summary metadata (D-06 position 1).

    Includes iteration count, random seed, and snapshot date.
    """
    print()
    print(f"==== Simulation Summary ====")
    print()
    print(f"  Iterations: {result.n_iterations}")
    print(f"  Seed: {result.seed}")
    print(f"  Snapshot: {result.snapshot_date}")
    print()


def print_league_table(result: SimulationResult) -> None:
    """Print formatted 36-row league table with ANSI zone coloring (D-06 position 2).

    Columns: Pos, Team, Pts, GD, GS, Zone (D-07).
    Zone color: green for top_8, yellow for playoff, red for eliminated (D-10).
    Auto-detects terminal color support (D-11).
    """
    print()
    print(f"==== League Table ====")
    print()

    # ── Header row (bold) ──
    print(
        f"  {_bold('Pos')}  "
        f"{_bold('Team'):<28} "
        f"{_bold('Pts')} "
        f"{_bold('GD')} "
        f"{_bold('GS')} "
        f"{_bold('Zone')}"
    )

    # ── Separator ──
    print("-" * 48)

    # ── Data rows (sorted by position ascending) ──
    for entry in result.standings:
        zone_label = entry["zone"].upper()
        color_fn = _zone_color(entry["zone"])

        pos_str = f"{entry['position']:>2}."
        team_str = f"{entry['team']:<24}"
        pts_str = f"{entry['pts']:>3}"
        gd_str = f"{entry['gd']:>+4}"
        gs_str = f"{entry['gs']:>3}"
        zone_str = color_fn(f"{zone_label:<10}")

        print(f"{pos_str}  {team_str} {pts_str} {gd_str} {gs_str} {zone_str}")

    print()


# ── Playoff display (D-06 position 3) ──────────────────────────────────


def print_playoff_rounds(result: SimulationResult) -> None:
    """Print 8 playoff ties with aggregate scores and advancing winners (D-06 position 3).

    ET/Pens shown only when triggered (D-08).
    """
    print()
    print("==== Playoff Results ====")
    print()

    for tie_num in sorted(result.playoff_ties):
        tie = result.playoff_ties[tie_num]
        winner = result.playoff_winners[tie_num]
        team_a = tie["winner"]
        team_b = tie["loser"]
        agg_a = tie["aggregate_a"]
        agg_b = tie["aggregate_b"]

        # Build aggregate display with optional ET/Pens suffix
        agg_display = f"{agg_a}-{agg_b} agg"
        if tie.get("et_played"):
            agg_display = f"{agg_a}-{agg_b} agg ({tie['et_a']}-{tie['et_b']} ET)"
        if tie.get("penalties_played"):
            if tie.get("et_played"):
                agg_display = f"{agg_a}-{agg_b} agg ({tie['et_a']}-{tie['et_b']} ET, {tie['penalty_a']}-{tie['penalty_b']} pens)"
            else:
                agg_display = f"{agg_a}-{agg_b} agg ({tie['penalty_a']}-{tie['penalty_b']} pens)"

        print(f"  Tie {tie_num}: {team_a} {agg_display}  {team_b} -> {winner} advances")

    print()


# ── Bracket display (D-06 position 4, D-08 format) ─────────────────────


def print_knockout_bracket(result: SimulationResult) -> None:
    """Print round-by-round match list (NOT ASCII tree — D-08).

    Rounds in order: R16 → QF → SF → FINAL.
    Two-legged ties show aggregate scores; FINAL shows single score.
    """
    print()
    print("==== Knockout Bracket ====")
    print()

    round_order = ["R16", "QF", "SF", "FINAL"]
    for round_name in round_order:
        print(f"  {_bold(f'--- {round_name} ---')}")

        matches = result.bracket_rounds.get(round_name, [])
        for m in matches:
            team_a = m["team_a"]
            team_b = m["team_b"]
            r = m["result"]

            if r.get("is_final"):
                # Single-match final
                score_line = f"{r['score_a']}-{r['score_b']}"
                suffix = ""
                if r.get("et_played"):
                    suffix = f" ({r['et_a']}-{r['et_b']} ET"
                    if r.get("penalties_played"):
                        suffix += f", {r['penalty_a']}-{r['penalty_b']} pens)"
                    else:
                        suffix += ")"
                elif r.get("penalties_played"):
                    suffix = f" ({r['penalty_a']}-{r['penalty_b']} pens)"
                print(f"    {team_a} {score_line}{suffix} {team_b}")
            else:
                # Two-legged tie with aggregate scores
                agg_a = r["aggregate_a"]
                agg_b = r["aggregate_b"]
                score_line = f"{agg_a}-{agg_b} agg"
                suffix = ""
                if r.get("et_played"):
                    suffix = f" ({r['et_a']}-{r['et_b']} ET"
                    if r.get("penalties_played"):
                        suffix += f", {r['penalty_a']}-{r['penalty_b']} pens)"
                    else:
                        suffix += ")"
                elif r.get("penalties_played"):
                    suffix = f" ({r['penalty_a']}-{r['penalty_b']} pens)"
                print(f"    {team_a} {score_line}{suffix}  {team_b}")

    print()


# ── Signal breakdown display (Phase 8, D-07) ──────────────────────────


def show_breakdown(
    blended_predictions: list[BlendedPrediction] | None = None,
    mode: str = "summary",
) -> None:
    """Display signal breakdown information per D-07.

    Two modes:
    - "summary": Display average weights across all predictions, signal utilization stats
    - "match": Display per-match signal probabilities and weight contributions

    Args:
        blended_predictions: List of BlendedPrediction from EnsembleEngine.
            If None or empty, shows a placeholder message.
        mode: "summary" or "match". Default "summary".
    """
    print()
    print(f"==== Signal Breakdown ({mode}) ====")
    print()

    if not blended_predictions:
        print("  No blended predictions available. Run with signal blending enabled.")
        print()
        return

    if mode == "summary":
        # Compute average weights and utilization across all predictions
        all_weights: dict[str, list[float]] = {}
        for bp in blended_predictions:
            for sig, weight in bp.weights_applied.items():
                if sig not in all_weights:
                    all_weights[sig] = []
                all_weights[sig].append(weight)

        print(f"  {'Signal':<20} {'Avg Weight':>10} {'In Blend':>9}")
        print("  " + "-" * 41)
        for sig in sorted(all_weights.keys()):
            avg_w = sum(all_weights[sig]) / len(all_weights[sig])
            in_blend = len(all_weights[sig])
            print(f"  {sig:<20} {avg_w:>10.4f} {in_blend:>9}")
        print()

    elif mode == "match":
        # Per-match display
        for i, bp in enumerate(blended_predictions):
            print(f"  --- Match {i + 1} ---")
            print(f"  Blended: home={bp.home_prob:.4f}  draw={bp.draw_prob:.4f}  "
                  f"away={bp.away_prob:.4f}")
            print(f"  {'Signal':<20} {'Home':>6} {'Draw':>6} {'Away':>6} {'Weight':>7}")
            print("  " + "-" * 47)
            for sig in sorted(bp.signal_breakdown.keys()):
                sd = bp.signal_breakdown[sig]
                print(f"  {sig:<20} {sd['home']:>6.3f} {sd['draw']:>6.3f} "
                      f"{sd['away']:>6.3f} {sd['weight']:>7.4f}")
            print()


def print_value_plays(
    blended_predictions: list[BlendedPrediction] | None = None,
) -> None:
    """Display value detection — model_prob minus market_implied_prob.

    Per D-04 Tier 3: Value detection display shows where the ensemble's
    prediction differs significantly from market odds (indicating potential
    value).

    Requires that 'market_odds' exists in the signal_breakdown and that
    the blended prediction probabilities differ meaningfully from market.

    Args:
        blended_predictions: List of BlendedPrediction from EnsembleEngine.
            If None or empty, shows a placeholder.
    """
    print()
    print("==== Value Plays (model - market) ====")
    print()

    if not blended_predictions:
        print("  No predictions available for value analysis.")
        print()
        return

    found_value = False
    for i, bp in enumerate(blended_predictions):
        if "market_odds" not in bp.signal_breakdown:
            continue

        md = bp.signal_breakdown["market_odds"]
        market_home = md["home"]
        market_draw = md["draw"]
        market_away = md["away"]

        # Value delta for each outcome
        delta_home = bp.home_prob - market_home
        delta_draw = bp.draw_prob - market_draw
        delta_away = bp.away_prob - market_away

        # Only show significant deltas (|delta| > 5%)
        sig_deltas = []
        for outcome, delta, market_prob, model_p in [
            ("HOME", delta_home, market_home, bp.home_prob),
            ("DRAW", delta_draw, market_draw, bp.draw_prob),
            ("AWAY", delta_away, market_away, bp.away_prob),
        ]:
            if abs(delta) > 0.05:
                sig_deltas.append((outcome, delta, market_prob, model_p))

        if sig_deltas:
            found_value = True
            print(f"  Match {i + 1}:")
            for outcome, delta, mkt, model_p in sig_deltas:
                direction = "OVER" if delta > 0 else "UNDER"
                print(f"    {outcome}: model={model_p:.3f} "
                      f"market={mkt:.3f} "
                      f"delta={delta:+.3f} ({direction}VALUE)")
    if not found_value:
        print("  No significant value plays detected (|delta| <= 5%).")

    print()


# ── Validation display (Phase 4, D-02) ────────────────────────────────


def print_validation_summary(validation_result: dict) -> None:
    """Print validation accuracy summary table to stdout (Phase 4, D-02).

    Shows games played, Brier score, Log Loss, accuracy, and calibration ECE.
    Also shows market odds metrics if available.
    """
    print()
    print(f"==== Validation Results ====")
    print()

    pm = validation_result["prediction_metrics"]
    print(f"  Games matched: {pm['n']}")
    print(f"  Brier Score:   {pm['brier']:.4f}")
    print(f"  Log Loss:      {pm['log_loss']:.4f}")
    print(f"  Accuracy:      {pm['accuracy']:.2%}")
    print(f"  Calibration ECE: {validation_result['calibration']['ece']:.4f}")

    if "market_odds_metrics" in validation_result:
        om = validation_result["market_odds_metrics"]
        print()
        print(f"  Market Odds Comparison:")
        print(f"    Brier Score:   {om['brier']:.4f}")
        print(f"    Log Loss:      {om['log_loss']:.4f}")
        print(f"    Games with odds: {om['n']}")

    print()

    print()


# ── Odds display (D-06 position 5, D-09 format) ────────────────────────


def print_signal_breakdown(
    contributions: dict[str, float],
    champion_team: str,
    champion_prob: float,
) -> None:
    """Display per-signal contribution breakdown for champion prediction.

    Shows which signals drive the champion probability and by how much.
    Positive contributions (pushing probability up) shown in green,
    negative contributions (pulling probability down) shown in red.

    Contributions are normalized to sum to champion_prob. If contributions
    dict is empty, prints a placeholder message.

    Args:
        contributions: {signal_name: raw_contribution} from compute_signal_contributions().
        champion_team: Name of the champion team.
        champion_prob: Champion probability as percentage (0-100).
    """
    print()
    print("==== Prediction Breakdown ====")
    print()
    print(f"  Champion: {_bold(champion_team)} ({champion_prob:.1f}%)")
    print()

    if not contributions:
        print("  No signal contribution data available.")
        print()
        return

    # Normalize contributions so they sum to champion_prob
    total_raw = sum(contributions.values())
    if abs(total_raw) < 1e-9:
        print("  All signal contributions are near zero.")
        print()
        return

    normalized = {
        sig: round(val / total_raw * champion_prob, 1)
        for sig, val in contributions.items()
    }

    # Sort by absolute contribution descending
    sorted_signals = sorted(
        normalized.items(),
        key=lambda x: -abs(x[1]),
    )

    print(f"  Signal contribution for champion prediction:")
    print()
    for sig_name, contrib in sorted_signals:
        sign = "+" if contrib >= 0 else ""
        formatted = f"{sign}{contrib:.1f}%"
        if contrib >= 0:
            formatted = _green(formatted)
        else:
            formatted = _red(formatted)
        print(f"    {sig_name:<20} {formatted}")

    # Separator line (ASCII only per Windows compatibility)
    print(f"    {'-' * 33}")
    total_formatted = f"{champion_prob:.1f}%"
    print(f"    {'Total:':<20} {_bold(total_formatted)}")
    print()


def print_odds(result: SimulationResult) -> None:
    """Print champion/qualification odds for all 36 teams (D-06 position 5).

    Columns per D-09: Rank, Team, Champion %, Final %, SF %, QF %.
    Sorted by champion probability descending, with alphabetical tie-break.
    """
    print()
    print("==== Champion / Qualification Odds ====")
    print()

    # Sort teams by champion_prob descending, then alphabetically
    sorted_teams = sorted(
        result.teams.items(),
        key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]),
    )

    # Header row (bold)
    print(
        f"  {_bold('Rank'):>4}  "
        f"{_bold('Team'):<24} "
        f"{_bold('Champion'):>8} "
        f"{_bold('Final'):>8} "
        f"{_bold('SF'):>8} "
        f"{_bold('QF'):>8}"
    )

    # Separator
    print("  " + "-" * 64)

    # Data rows
    for rank, (team_name, team_data) in enumerate(sorted_teams, start=1):
        champ = team_data.get("champion_prob", 0.0)
        final = team_data.get("stage_final_prob", 0.0)
        sf = team_data.get("stage_sf_prob", 0.0)
        qf = team_data.get("stage_qf_prob", 0.0)

        print(
            f"  {rank:>4}  "
            f"{team_name:<24} "
            f"{champ:>7.1%} "
            f"{final:>7.1%} "
            f"{sf:>7.1%} "
            f"{qf:>7.1%}"
        )

    print()
