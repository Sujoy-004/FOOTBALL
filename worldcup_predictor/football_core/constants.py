"""Shared constants for football_core — no competition-specific values."""

K_FACTOR: int = 60
DEFAULT_ELO: int = 1500
MAX_EXPECTED_GOALS: float = 8.0
HOME_ADVANTAGE_MULTIPLIER: float = 1.05
POISSON_TABLE_BITS: int = 10
POISSON_TABLE_SIZE: int = 1 << POISSON_TABLE_BITS
EXPECTED_GOALS_BASE_RATE: float = 1.25

API_TIMEOUT: int = 10

ELO_SYNC_RETRY_BACKOFFS: tuple[float, ...] = (1.0, 2.0, 4.0)
ELO_SYNC_TIMEOUT: int = 15
ELO_DRIFT_TOLERANCE: int = 10
ELO_BLEND_THRESHOLD: int = 30
ELO_BLEND_FACTOR: float = 0.5
ELO_STALENESS_WARN_HOURS: tuple[int, ...] = (24, 48, 72, 168)
ELORATINGS_TSV_URL: str = "https://www.eloratings.net/World.tsv"
