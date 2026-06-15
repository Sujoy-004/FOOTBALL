"""Constants for the World Cup predictor."""

import os
from pathlib import Path

K_FACTOR: int = 60
"""Default K-factor for World Cup finals matches (eloratings.net standard)."""

DEFAULT_ELO: int = 1500
"""Starting Elo rating for new teams not yet in the system."""

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
"""Directory containing JSON state files (teams.json, bracket.json, played.json)."""

API_URL: str = "https://sports.bzzoiro.com/api/events/?league_id=27&limit=200"
"""BSD (Bzzoiro Sports Data) API endpoint for World Cup matches (post-filtered for finished status in fetcher)."""

WC_START_DATE: str = "2026-06-11"
"""Tournament start date for historical catch-up URL construction."""

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

# ─── Elo Sync Constants ──────────────────────────────────────────────────

ELORATINGS_TSV_URL: str = "https://www.eloratings.net/World.tsv"
"""URL for eloratings.net World Cup Elo data in TSV format (D-05)."""

ELO_SYNC_INTERVAL_HOURS: int = 24
"""How often to re-sync from eloratings.net in hours (D-02)."""

ELO_SYNC_CATCHUP_HOURS: int = 36
"""If last sync older than this, catch up immediately instead of waiting for next window (D-03)."""

ELO_SYNC_RETRY_BACKOFFS: tuple[float, ...] = (1.0, 2.0, 4.0)
"""Exponential backoff in seconds between eloratings.net fetch retries (D-17)."""

ELO_SYNC_TIMEOUT: int = 15
"""HTTP timeout in seconds for eloratings.net fetch requests."""

ELO_DRIFT_TOLERANCE: int = 10
"""Drift below this threshold in points is ignored during sync (D-11)."""

ELO_BLEND_THRESHOLD: int = 30
"""Drift above this threshold triggers overwrite+flag; below triggers 50%% blend (D-11)."""

ELO_BLEND_FACTOR: float = 0.5
"""Blend factor when drift is between tolerance and threshold (D-11)."""

ELO_STALENESS_WARN_HOURS: tuple[int, ...] = (24, 48, 72, 168)
"""Staleness thresholds in hours for graduated warnings: green, info, yellow, red, critical (D-16)."""

ELORATINGS_TEAM_CODES: dict[str, str] = {
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "BA": "Bosnia and Herzegovina",
    "BE": "Belgium",
    "BR": "Brazil",
    "CA": "Canada",
    "CD": "DR Congo",
    "CH": "Switzerland",
    "CI": "Ivory Coast",
    "CO": "Colombia",
    "CV": "Cape Verde",
    "CW": "Curaçao",
    "CZ": "Czech Republic",
    "DE": "Germany",
    "DZ": "Algeria",
    "EC": "Ecuador",
    "EG": "Egypt",
    "EN": "England",
    "ES": "Spain",
    "FR": "France",
    "GH": "Ghana",
    "HR": "Croatia",
    "HT": "Haiti",
    "IQ": "Iraq",
    "IR": "Iran",
    "JP": "Japan",
    "JO": "Jordan",
    "KR": "South Korea",
    "MA": "Morocco",
    "MX": "Mexico",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PA": "Panama",
    "PT": "Portugal",
    "PY": "Paraguay",
    "QA": "Qatar",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SN": "Senegal",
    "SQ": "Scotland",
    "TN": "Tunisia",
    "TR": "Türkiye",
    "US": "United States",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "ZA": "South Africa",
}
"""Mapping of eloratings.net 2-letter team codes (World.tsv col 2) to canonical project team names.
All 48 World Cup 2026 teams. Codes in alphabetical order."""
