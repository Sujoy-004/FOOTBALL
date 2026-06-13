"""Constants for the World Cup predictor."""

from pathlib import Path

K_FACTOR: int = 60
"""Default K-factor for World Cup finals matches (eloratings.net standard)."""

DEFAULT_ELO: int = 1500
"""Starting Elo rating for new teams not yet in the system."""

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
"""Directory containing JSON state files (teams.json, bracket.json, played.json)."""
