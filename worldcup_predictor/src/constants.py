"""Constants for the World Cup predictor."""

import os
from pathlib import Path

K_FACTOR: int = 60
"""Default K-factor for World Cup finals matches (eloratings.net standard)."""

DEFAULT_ELO: int = 1500
"""Starting Elo rating for new teams not yet in the system."""

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
"""Directory containing JSON state files (teams.json, bracket.json, played.json)."""

API_URL: str = "https://sports.bzzoiro.com/api/events/?status=finished&league_id=27&limit=200"
"""BSD (Bzzoiro Sports Data) API endpoint for finished World Cup matches."""

API_TIMEOUT: int = 10
"""HTTP request timeout in seconds for Football-Data.org API calls."""

POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "60"))
"""Default polling interval in seconds between API fetch cycles (overridable via POLL_INTERVAL env var)."""
