"""Entry point for the World Cup Dynamic Predictor.

Loads teams, bracket, and played matches from JSON files,
validates the bracket structure, and prints a startup summary.
"""

import json
import sys

from src import state


def main() -> None:
    """Load all state, validate bracket, and print a startup summary."""
    print("=== World Cup Dynamic Predictor ===")

    try:
        teams = state.load_teams()
        print(f"Loaded {len(teams)} teams")

        bracket = state.load_bracket()
        print(f"Validated bracket: {len(bracket)} matches")

        played = state.load_played()
        print(f"Played matches: {len(played)}")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error: File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Corrupt JSON file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
