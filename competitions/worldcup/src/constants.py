"""Constants for the World Cup predictor.

Extends football_core.constants with WC-specific values."""

import os
from pathlib import Path

from football_core.constants import (
    K_FACTOR,
    DEFAULT_ELO,
    MAX_EXPECTED_GOALS,
    HOME_ADVANTAGE_MULTIPLIER,
    POISSON_TABLE_BITS,
    POISSON_TABLE_SIZE,
    EXPECTED_GOALS_BASE_RATE,
    ELO_SYNC_RETRY_BACKOFFS,
    ELO_SYNC_TIMEOUT,
    ELO_DRIFT_TOLERANCE,
    ELO_BLEND_THRESHOLD,
    ELO_BLEND_FACTOR,
    ELO_STALENESS_WARN_HOURS,
    ELORATINGS_TSV_URL,
    API_TIMEOUT,
)

# ─── Multi-League Framework (Phase 19) ─────────────────────────────────────

DEFAULT_LEAGUE_ID: int = 27
"""Default BSD league ID (World Cup 2026)."""

LEAGUES: dict[int, str] = {
    27: "World Cup 2026",
}
"""Static catalog of BSD league IDs to league names (World Cup only)."""


def api_url_for_league(league_id: int) -> str:
    """Build BSD events API URL for a given league ID."""
    return f"https://sports.bzzoiro.com/api/events/?league_id={league_id}&limit=200"


# ─── World-Cup-specific Constants ───────────────────────────────────────────

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
"""Directory containing JSON state files (teams.json, bracket.json, played.json)."""

API_URL: str = "https://sports.bzzoiro.com/api/events/?league_id=27&limit=200"
"""BSD API endpoint for World Cup matches."""

WC_START_DATE: str = "2026-06-11"
"""Tournament start date for historical catch-up URL construction."""

POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "60"))
"""Default polling interval in seconds between API fetch cycles."""

GROUP_COUNT: int = 12
"""Number of groups in the 48-team format (A–L)."""

TEAMS_PER_GROUP: int = 4
"""Number of teams in each group."""

MATCHES_PER_GROUP: int = 6
"""Number of round-robin matches per group (n*(n-1)/2 for n=4)."""

ANNEX_C_ENTRIES: int = 495
"""Number of entries in Annex C third-place lookup table = C(12,8)."""

ANNEX_C_WINNER_GROUPS: tuple[str, ...] = ("A", "B", "D", "E", "G", "I", "K", "L")
"""Group winners that host third-place teams in R32."""

TREND_THRESHOLD: float = 0.005
"""Minimum probability change (0.5 pp) to display a trend arrow in the probability table."""

# ─── Elo Sync Constants ──────────────────────────────────────────────────

ELO_SYNC_INTERVAL_HOURS: int = 24
"""How often to re-sync from eloratings.net in hours (D-02)."""

ELO_SYNC_CATCHUP_HOURS: int = 36
"""If last sync older than this, catch up immediately instead of waiting for next window (D-03)."""

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

# ─── Signal Ingestion Constants (Phase 13) ────────────────────────────

ODDS_CACHE_TTL_HOURS: int = 12
"""How long odds cache is valid in hours (D-06: resolved to 12h per research)."""

CATBOOST_CACHE_TTL_HOURS: int = 24
"""How long CatBoost cache is valid in hours (D-06: resolved to 24h per research)."""

ODDS_CACHE_FILE: str = "odds_cache.json"
"""Filename for market odds cache in data/ directory (D-04)."""

CATBOOST_CACHE_FILE: str = "catboost_cache.json"
"""Filename for CatBoost prediction cache in data/ directory (D-04)."""

PREDICTION_LEDGER_FILE: str = "predictions_ledger.json"
"""Filename for permanent prediction ledger in data/ directory (Phase 14a).
Unlike TTL caches, the ledger accumulates all predictions ever fetched,
keyed by match_id, and is never deleted."""

PREDICTION_HISTORY_SCHEMA_VERSION: int = 2
"""Schema version for prediction_history.json. v1=flat (Phase 12b), v2=compound (Phase 13+)."""

PROBABILITY_LOG_FILE: str = "probability_log.json"
"""Filename for rolling probability log in data/ directory (Phase 20).
Array of snapshot dicts appended after every _run_iteration(). Never pruned."""

# ─── Blender Constants (Phase 14) ──────────────────────────────────────────

CALIBRATION_PARAMS_FILE: str = "calibration_params.json"
"""Filename for fitted Platt scaling parameters (Phase 14).
Stored as {signal_key: {A: float, B: float, n_matches: int, brier: float, fitted_at: str}}."""

COLD_START_THRESHOLD: int = 30
"""Minimum matches before Platt scaling fitting activates (D-03/D-04).
Below this, identity calibration (p_calibrated = p_raw) is used."""

BRIER_WINDOW_SIZE: int = 50
"""Rolling window for per-signal Brier computation used in blend weights (D-08).
All recorded matches used when history < window size."""

# ─── Context Signal Constants (Phase 15) ───────────────────────────────────

FORM_WINDOW_SIZE: int = 5
"""Default rolling window size for form residual computation (Phase 15, D-02).
Number of most-recent matches per team used to compute average form residual.
If a team has fewer than this, use whatever is available. If 0, signal unavailable."""

TEAM_VALUES_FILE: str = "team_values.json"
"""Filename for squad market values data file in data/ directory (Phase 15).
Static file with per-team aggregate squad market values in EUR. NOT from BSD API
per user decision (BSD API key expired, 832 API calls, live dependency ruled out)."""

DEFAULT_FORM_K: float = 1.0
"""Default sigmoid steepness for form signal — TUNING PARAMETER (D-05).

Empirically validated from 19 played matches (2026-06-17):
- Every team has exactly 1 match (cold tournament)
- Observed form_delta range: [-1.01, +1.01], 95th percentile ±0.78
- Theoretical max (full 5-match window): [-2, +2]

k=1.0 gives:
- form_delta=0.78 (95th %ile): sigmoid(0.78) = 0.686 (±0.186 from 0.50)
- form_delta=1.01 (observed max): sigmoid(1.01) = 0.733

NOTE: Planner originally proposed k=0.6 based on incorrect assumption
that form_delta ∈ [-5, +5] (used sum instead of mean). Actual range is
[-2, +2] theoretical, [-1, +1] empirical. k=1.0 chosen after audit to
avoid suppressing an already-small signal.

This is a calibration constant, not an architecture decision.
Expected to change once real multi-signal accumulation data is available.
Platt scaling refines this as entries accumulate (>=30 threshold)."""

DEFAULT_LINEUP_K: float = 0.35
"""Default sigmoid steepness for lineup strength signal — TUNING PARAMETER (D-10).

Squad market values range from €7.5M (Panama) to €1.52B (France),
producing ln ratios in [-5.31, +5.31].

k=0.35 gives:
- Panama@France (203x, delta=-5.31): p=0.135
- USA@England (0.28x, delta=-1.26): p=0.392
- Brazil@Argentina (1.15x, delta=+0.14): p=0.512
- Extreme mismatch (200x): p=0.865 (no saturation)

Avoids saturation at boundary values. Differentiates strong mismatches
without extreme probabilities.

This is a calibration constant, not an architecture decision.
Expected to change once real data accumulates."""

FORM_CACHE_FILE: str = "form_cache.json"
"""Filename for form signal cache in data/ directory. Form is computed locally
(no API call) but follows same cache-dict schema as odds/catboost for consistency."""

LINEUP_CACHE_FILE: str = "lineup_cache.json"
"""Filename for lineup strength signal cache in data/ directory."""

MANAGER_CACHE_TTL_HOURS: int = 24
"""How long manager data cache is valid in hours.
Manager profiles change rarely (only on managerial changes)."""

MANAGER_CACHE_FILE: str = "manager_cache.json"
"""Filename for manager data cache in data/ directory.
Contains raw manager profiles used by both defensive_quality and manager_effect."""

DEFENSIVE_CACHE_FILE: str = "defensive_cache.json"
"""Filename for defensive quality signal cache in data/ directory."""

MANAGER_EFFECT_CACHE_FILE: str = "manager_effect_cache.json"
"""Filename for manager effect signal cache in data/ directory."""

AVAILABILITY_CACHE_TTL_HOURS: int = 6
"""How long player/availability data cache is valid in hours.
Shorter TTL because player availability changes rapidly with squad announcements."""

AVAILABILITY_CACHE_FILE: str = "availability_cache.json"
"""Filename for availability signal cache in data/ directory.
Player data (availability, injury_risk) from BSD /api/v2/players/."""

DEFAULT_DEFENSIVE_K: float = 2.0
"""Default sigmoid steepness for defensive quality signal.
clean_sheet_pct ∈ [0, 1] and xga_norm ∈ [0, 1], so composite ∈ [0, 1].
k=2.0 maps diff=0.5 to sigmoid(1.0)=0.73."""

DEFAULT_MANAGER_K: float = 2.0
"""Default sigmoid steepness for manager effect signal.
win_pct ∈ [0, 1], rating ∈ [0, ~1.1] with bonuses.
k=2.0 provides reasonable spread."""

DEFAULT_AVAILABILITY_K: float = 3.0
"""Default sigmoid steepness for availability signal.
Unavailability ∈ [0, 1]. k=3.0 maps diff=0.5 to sigmoid(1.5)=0.82."""

# ─── Governance Constants (Phase 16) ───────────────────────────────────

GOV_DATA_FILE: str = "versions.json"
"""Filename for version tracking state in data/ directory."""

GOV_RUNS_DIR: str = "runs"
"""Directory for run snapshots relative to data/."""

GOV_INTERVAL_HOURS: int = 1
"""How often to run governance checks (startup + hourly + on drift)."""

GOVERNANCE_INTERVAL_SECONDS: int = 3600
"""Governance runs at startup and hourly thereafter (1 hour = 3600 seconds)."""

GOV_DRIFT_SIGMA_THRESHOLD: float = 2.0
"""Number of standard deviations above reference baseline that triggers drift alert (D-09)."""

GOV_BACKTEST_TOURNAMENTS: list[str] = ["2018", "2022"]
"""Historical World Cups to backtest against (D-13)."""

GOV_RUN_SNAPSHOT_RETENTION: int = 1000
"""Maximum number of run snapshots to retain (the agent's discretion)."""
