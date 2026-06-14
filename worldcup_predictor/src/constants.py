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

GROUP_COUNT: int = 12
"""Number of groups in the 48-team format (A–L)."""

TEAMS_PER_GROUP: int = 4
"""Number of teams in each group."""

MATCHES_PER_GROUP: int = 6
"""Number of round-robin matches per group (n*(n-1)/2 for n=4)."""

ANNEX_C_ENTRIES: int = 495
"""Number of entries in Annex C third-place lookup table = C(12,8)."""

ANNEX_C_WINNER_GROUPS: tuple[str, ...] = ("A", "B", "D", "E", "G", "I", "K", "L")
"""Group winners that host third-place teams in R32 (derivable from Annex C structure; hardcoded for convenience)."""

EXPECTED_GOALS_BASE_RATE: float = 1.25
"""Base expected goals per team per match at Elo-neutral conditions (Elo=1500 vs Elo=1500).
Used by groups.py Poisson model. Historical World Cup group stage average."""
