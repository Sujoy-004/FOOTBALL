"""Euro 2024 display/output — competition-specific printing."""


def print_header() -> None:
    print()
    print("=" * 60)
    print("    UEFA EURO 2024 DYNAMIC PREDICTOR")
    print("=" * 60)
    print()


def print_probability_table(probs: dict, prev_probs: dict | None = None) -> None:
    print(f"{'Team':<25} {'QF':>8} {'SF':>8} {'Final':>8} {'Champ':>8}")
    print("-" * 60)
    sorted_teams = sorted(probs.items(), key=lambda x: x[1]["champion"], reverse=True)
    for team, p in sorted_teams:
        print(f"{team:<25} {p['qf']:>7.1%} {p['sf']:>7.1%} {p['final']:>7.1%} {p['champion']:>7.1%}")
    print()


def print_simulation_duration(elapsed: float) -> None:
    print(f"Simulation: {elapsed:.2f}s")


def print_shutdown_banner(probs: dict) -> None:
    print()
    print("=" * 60)
    print("  FINAL PROBABILITIES")
    print("=" * 60)
    print_probability_table(probs)
    print("Euro 2024 Predictor — shutting down.")
    print()


def print_match_alert(m: dict) -> None:
    team_a = m.get("team_a", "?")
    team_b = m.get("team_b", "?")
    score_a = m.get("home_score", m.get("score_a", "?"))
    score_b = m.get("away_score", m.get("score_b", "?"))
    print(f"New result: {team_a} {score_a}-{score_b} {team_b}")


def print_heartbeat() -> None:
    print(".", end="", flush=True)
