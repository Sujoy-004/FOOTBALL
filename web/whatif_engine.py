import re, json, math
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "competitions" / "ucl" / "data"


def load_teams_list():
    p = DATA_DIR / "teams.json"
    if p.exists():
        return list(json.loads(p.read_text(encoding="utf-8")).keys())
    return []


# Condition patterns -> signal adjustments
# Each pattern: {signal: multiplier} or {signal: fixed_delta}
CONDITION_MAP = [
    # Injuries / absences
    (r"(?i)\b(injured|injury|out|suspended|missing|absent)\b", {"lineup_strength": 0.30, "form": 0.70}),
    (r"(?i)\b(star player|key player|best player|captain)\b.*?\b(injured|out|suspended|missing)\b", {"lineup_strength": 0.15, "form": 0.60}),

    # Form conditions
    (r"(?i)\b(in form|on fire|great form|excellent|incredible|strong form)\b", {"form": 1.60}),
    (r"(?i)\b(poor form|slump|bad form|struggling|out of form)\b", {"form": 0.40}),

    # Defense conditions
    (r"(?i)\b(defense\s+.*\bweak\b|weak\s+.*\bdefense\b|leaky defense|vulnerable|defensive issues|poor defense)\b", {"defensive_quality": 0.30}),
    (r"(?i)\b(defense\s+.*\bstrong\b|strong\s+.*\bdefense\b|solid defense|organized|defensive masterclass|clean sheet)\b", {"defensive_quality": 1.60}),
    (r"(?i)\bweak\b", {"defensive_quality": 0.50, "form": 0.75}),
    (r"(?i)\b(weakened|getting weak|weaker)\b", {"defensive_quality": 0.30, "form": 0.65}),
    (r"(?i)\bstrong\b", {"defensive_quality": 1.35, "form": 1.15}),

    # Manager conditions
    (r"(?i)\b(manager sacked|new manager|coach fired|interim coach)\b", {"manager_effect": 0.20}),
    (r"(?i)\b(tactical master|great manager|experienced coach)\b", {"manager_effect": 1.50}),
    (r"(?i)\b(park the bus|defensive tactic|counter attack|counter-attacking)\b", {"defensive_quality": 1.50, "form": 0.70}),
    (r"(?i)\b(attacking|aggressive|high press|possession football)\b", {"form": 1.35, "defensive_quality": 0.70}),

    # Odds / market conditions
    (r"(?i)\b(underdog|underdog win|giant killing|upset)\b", {"form": 1.30, "defensive_quality": 1.30}),
    (r"(?i)\b(heavy favorite|favorite|dominant)\b", {"form": 1.20, "lineup_strength": 1.20}),

    # Weather / external
    (r"(?i)\b(rain|wet pitch|heavy rain|storm|bad weather)\b", {"defensive_quality": 1.20, "form": 0.80}),
    (r"(?i)\b(heat|hot|high temperature|humidity)\b", {"form": 0.80, "defensive_quality": 0.80}),
    (r"(?i)\b(home crowd|home advantage|home game|host nation)\b", {"form": 1.20, "lineup_strength": 1.15}),
    (r"(?i)\b(away|away game|hostile crowd)\b", {"form": 0.80, "lineup_strength": 0.85}),

    # Fatigue / schedule
    (r"(?i)\b(tired|fatigue|cramped schedule|short rest|extra time)\b", {"form": 0.60, "lineup_strength": 0.70}),

    # Momentum
    (r"(?i)\b(winning streak|on a roll|confident|momentum)\b", {"form": 1.45}),
    (r"(?i)\b(losing streak|demoralized|low confidence)\b", {"form": 0.35}),
]


class ScenarioParseResult:
    def __init__(self):
        self.adjustments = {}  # {signal_name: multiplier}
        self.target_team = None
        self.confidence = 0.0
        self.explanation_parts = []
        self.matched_patterns = []

    def add_adjustment(self, sig, multiplier):
        current = self.adjustments.get(sig, 1.0)
        self.adjustments[sig] = round(current * multiplier, 4)

    def to_dict(self):
        return {
            "target_team": self.target_team,
            "adjustments": self.adjustments,
            "confidence": round(self.confidence, 2),
            "explanation": " | ".join(self.explanation_parts) if self.explanation_parts else "No specific scenario detected.",
            "n_patterns_matched": len(self.matched_patterns),
        }


def parse_scenario(text, match_ta, match_tb, blend_weights):
    """Parse scenario text and return signal adjustments.

    Returns: ScenarioParseResult
    """
    result = ScenarioParseResult()
    teams_list = load_teams_list()
    team_names_lower = {t.lower(): t for t in teams_list}

    text_lower = text.lower()

    # Detect target team
    for t_lower, t_orig in team_names_lower.items():
        if t_lower in text_lower and (t_orig == match_ta or t_orig == match_tb):
            result.target_team = t_orig
            result.confidence += 0.3
            result.explanation_parts.append(f"detected: {t_orig}")
            break

    # Check for player names (common ones)
    player_map = {
        "messi": "Argentina", "ronaldo": "Portugal", "neymar": "Brazil",
        "mbappe": "France", "haaland": "Norway", "de bruyne": "Belgium",
        "kane": "England", "lewandowski": "Poland", "salah": "Egypt",
        "modric": "Croatia", "kroos": "Germany", "muller": "Germany",
        "griezmann": "France", "pogba": "France", "sterling": "England",
    }
    for player, team in player_map.items():
        if player in text_lower:
            result.target_team = team
            result.confidence += 0.2
            result.explanation_parts.append(f"player {player} -> {team}")
            break

    # Match patterns
    for pattern, adjustments in CONDITION_MAP:
        if re.search(pattern, text):
            result.matched_patterns.append(pattern)
            for sig, mult in adjustments.items():
                result.add_adjustment(sig, mult)
            # Derive explanation from the pattern
            label = pattern.replace("(?i)", "").replace(r"\(|\)|\|", "").strip()
            short = label[:40]
            result.explanation_parts.append(short)

    # If no team detected and no patterns matched
    if not result.target_team and not result.matched_patterns:
        result.confidence = 0.0
        return result

    # Average confidence boost from patterns
    if result.matched_patterns:
        result.confidence = min(1.0, result.confidence + 0.2 * len(result.matched_patterns))

    return result


def apply_adjustments(original_signals, adjustments, target_team, match_ta, match_tb):
    """Apply scenario adjustments to original signal probabilities.

    Returns:
        adjusted_signals: {signal_name: {probability, delta, was_adjusted}}
        blended_before: float
        blended_after: float
    """
    if not original_signals:
        return {"error": "no signal data", "adjusted_signals": {}, "blended_before": 0.5, "blended_after": 0.5}

    total_w = 0
    weighted_p = 0
    for sk, sv in original_signals.items():
        w = sv.get("weight", 0)
        p = sv.get("probability", 0.5)
        if w > 0:
            total_w += w
            weighted_p += w * p
    blended_before = weighted_p / total_w if total_w > 0 else 0.5

    adjusted = {}
    total_w_after = 0
    weighted_p_after = 0
    for sk, sv in original_signals.items():
        w = sv.get("weight", 0)
        p = sv.get("probability", 0.5)

        was_adjusted = False
        if adjustments and target_team:
            adj_mult = adjustments.get(sk, 1.0)
            if adj_mult != 1.0:
                # adj_mult < 1.0 = weaken target → push their prob AWAY from 0.5
                # adj_mult > 1.0 = strengthen target → push their prob toward 0.5
                if adj_mult < 1.0:
                    eff = min(1.0 / max(adj_mult, 0.05), 5.0)
                else:
                    eff = adj_mult
                if target_team == match_ta:
                    new_p = 0.5 + (p - 0.5) * eff
                else:
                    p_b = 1.0 - p
                    new_p_b = 0.5 + (p_b - 0.5) * eff
                    new_p = 1.0 - new_p_b
                new_p = max(0.01, min(0.99, new_p))
                delta = new_p - p
                was_adjusted = True
            else:
                new_p = p
                delta = 0
        else:
            new_p = p
            delta = 0

        adjusted[sk] = {
            "probability": round(new_p, 4),
            "delta": round(delta, 4),
            "weight": w,
            "was_adjusted": was_adjusted,
        }
        if w > 0:
            total_w_after += w
            weighted_p_after += w * new_p

    blended_after = weighted_p_after / total_w_after if total_w_after > 0 else 0.5

    return {
        "adjusted_signals": adjusted,
        "blended_before": round(blended_before, 4),
        "blended_after": round(blended_after, 4),
        "delta": round(blended_after - blended_before, 4),
    }


SIGNAL_LABELS = {
    "form": "current form",
    "lineup_strength": "lineup strength",
    "defensive_quality": "defensive quality",
    "manager_effect": "manager effect",
    "market_odds": "market odds",
    "catboost": "catboost model",
    "elo": "Elo rating",
}


def _describe_delta(delta_pct):
    """Return a qualitative description of a probability delta."""
    ad = abs(delta_pct)
    if ad < 0.5:
        return "negligible"
    if ad < 2.0:
        return "slight"
    if ad < 5.0:
        return "moderate"
    if ad < 10.0:
        return "significant"
    return "major"


def generate_instant_insight(ta, tb, target_team, original_signals, adjusted_signals, blended_before, blended_after, parsed_dict, team_strengths=None):
    """Generate natural language insight for instant what-if scenario."""
    lines = []
    delta = blended_after - blended_before
    delta_pct = delta * 100

    scenario = parsed_dict.get("explanation", "unknown scenario")
    n_matched = parsed_dict.get("n_patterns_matched", 0)

    # Opening line — scenario summary
    if target_team:
        target_team_friendly = target_team
        lines.append(f"Scenario: {scenario}")
    else:
        lines.append(f"Scenario: {scenario} (no specific team targeted)")

    # Which signals were adjusted and by how much
    if adjusted_signals:
        adj_lines = []
        for sk, sv in adjusted_signals.items():
            if sv.get("was_adjusted"):
                orig_p = original_signals.get(sk, {}).get("probability", 0.5) * 100
                new_p = sv["probability"] * 100
                lbl = SIGNAL_LABELS.get(sk, sk)
                delta_s = sv["delta"] * 100
                direction = "increases" if delta_s > 0 else "drops"
                adj_lines.append(f"{lbl} {direction} from {orig_p:.0f}% to {new_p:.0f}%")
        if adj_lines:
            lines.append("Signal changes: " + "; ".join(adj_lines))

    # Win probability impact
    before_p = blended_before * 100
    after_p = blended_after * 100

    if target_team and n_matched > 0:
        is_target_a = target_team == ta
        team_role = "win probability"  # for target team
        winner = ta if blended_after > 0.5 else tb
        winner_p = max(after_p, 100 - after_p)

        # Describe impact direction relative to target
        if is_target_a:
            target_direction = "improves" if delta > 0 else "weakens"
            rival = tb
        else:
            target_direction = "improves" if delta < 0 else "weakens"
            rival = ta

        qual = _describe_delta(delta_pct)
        lines.append(f"Impact: {target_team}'s position {target_direction} — win probability shifts from {before_p:.1f}% to {after_p:.1f}% ({qual} {delta_pct:+.1f}% delta).")
        lines.append(f"Outcome shifts toward {winner} ({winner_p:.0f}%).")

        # Context about which signal is most affected for this team
        if team_strengths and target_team:
            strongest_sig = None
            strongest_val = 0
            for sk, sv in adjusted_signals.items():
                if sv.get("was_adjusted"):
                    impact = abs(sv["delta"])
                    if impact > strongest_val:
                        strongest_val = impact
                        strongest_sig = sk
            if strongest_sig and strongest_val > 0.01:
                lbl = SIGNAL_LABELS.get(strongest_sig, strongest_sig)
                lines.append(f"Primary driver: {lbl} changed by {abs(strongest_val)*100:.1f}%.")
                # Add context about whether this matters
                if strongest_sig == "defensive_quality":
                    lines.append(f"Context: defensive quality is a strong indicator — this shift carries weight.")
                elif strongest_sig == "form":
                    lines.append(f"Context: form swings can compound across the knockout stage.")
                elif strongest_sig == "lineup_strength":
                    lines.append(f"Context: lineup strength reflects available personnel depth.")
                elif strongest_sig == "manager_effect":
                    lines.append(f"Context: manager changes can reshape team dynamics.")
    else:
        # No/low confidence scenario
        lines.append(f"Win probability shifts from {before_p:.1f}% to {after_p:.1f}% ({delta_pct:+.1f}% delta).")
        if n_matched == 0:
            lines.append("No specific condition patterns matched. Try describing the scenario more explicitly.")
        elif not target_team:
            lines.append("Target team not clearly identified. Mention the team name explicitly.")

    if n_matched > 0:
        conf = parsed_dict.get("confidence", 0)
        if conf < 0.3:
            lines.append(">> Analysis confidence is LOW. Be more specific about conditions.")
        elif conf < 0.6:
            lines.append(">> Analysis confidence: moderate — cross-check with full simulation for verification.")

    return " >> ".join(lines)


def generate_simulate_insight(baseline_champions, scenario_champions, scenario_text, match_ta, match_tb, iterations):
    """Generate natural language insight for simulate mode by comparing baseline vs scenario."""
    lines = []

    # Build per-team delta
    all_teams = set(list(baseline_champions.keys()) + list(scenario_champions.keys()))
    deltas = {}
    for team in all_teams:
        base = baseline_champions.get(team, {}).get("champion", 0) * 100
        scen = scenario_champions.get(team, {}).get("champion", 0) * 100
        deltas[team] = {"before": base, "after": scen, "delta": scen - base}

    sorted_teams = sorted(deltas.items(), key=lambda x: abs(x[1]["delta"]), reverse=True)

    winners = [(t, d) for t, d in sorted_teams if d["delta"] > 0.1]
    losers = [(t, d) for t, d in sorted_teams if d["delta"] < -0.1]

    n_sim = f"{iterations:,}"
    lines.append(f"Simulation ({n_sim} iterations): {scenario_text}")

    # Top gainers
    top_winners = sorted(winners, key=lambda x: x[1]["delta"], reverse=True)[:3]
    if top_winners:
        gain_strs = []
        for team, d in top_winners:
            gain_strs.append(f"{team} {d['before']:.1f}% → {d['after']:.1f}% ({d['delta']:+.1f}%)")
        lines.append("Gainers: " + ", ".join(gain_strs))

    # Top losers
    top_losers = sorted(losers, key=lambda x: x[1]["delta"])[:3]
    if top_losers:
        loss_strs = []
        for team, d in top_losers:
            loss_strs.append(f"{team} {d['before']:.1f}% → {d['after']:.1f}% ({d['delta']:+.1f}%)")
        lines.append("Losers: " + ", ".join(loss_strs))

    # Impact on the match teams
    if match_ta in deltas:
        d = deltas[match_ta]
        lines.append(f"Impact on {match_ta}: {d['before']:.1f}% → {d['after']:.1f}% champion prob ({d['delta']:+.1f}%)")
    if match_tb in deltas:
        d = deltas[match_tb]
        lines.append(f"Impact on {match_tb}: {d['before']:.1f}% → {d['after']:.1f}% champion prob ({d['delta']:+.1f}%)")

    # Overall assessment
    max_abs_delta = max(abs(d["delta"]) for d in deltas.values()) if deltas else 0
    if max_abs_delta > 5:
        lines.append("The scenario produces a meaningful shift in the tournament landscape.")
    elif max_abs_delta > 1:
        lines.append("The scenario has a measurable but limited effect on outcomes.")
    else:
        lines.append("The scenario has minimal impact on the overall tournament structure.")

    return " >> ".join(lines)


def handle_instant_scenario(text, match_ta, match_tb, original_signals, blend_weights, elo_prob=None, team_strengths=None):
    """Full pipeline: parse + apply for instant mode."""
    # Ensure elo signal is always present in original_signals
    if elo_prob is not None and "elo" not in original_signals:
        elo_w = blend_weights.get("elo", 0.1874)
        original_signals["elo"] = {"probability": elo_prob, "weight": elo_w}

    parsed = parse_scenario(text, match_ta, match_tb, blend_weights)
    adj_result = apply_adjustments(original_signals, parsed.adjustments, parsed.target_team, match_ta, match_tb)
    
    # Generate natural language insight
    insight = generate_instant_insight(
        match_ta, match_tb, parsed.target_team,
        original_signals, adj_result.get("adjusted_signals", {}),
        adj_result.get("blended_before", 0.5),
        adj_result.get("blended_after", 0.5),
        parsed.to_dict(),
        team_strengths=team_strengths,
    )
    adj_result["insight"] = insight

    return {
        **adj_result,
        "parsed": parsed.to_dict(),
    }
