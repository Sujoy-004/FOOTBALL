"""Euro 2024 competition constants."""

from pathlib import Path

COMPETITION_NAME: str = "UEFA Euro 2024"
COMPETITION_TYPE: str = "tournament"
SIMULATION_ITERATIONS: int = 50000
K_FACTOR: int = 60
EXPECTED_GOALS_BASE_RATE: float = 1.20
HOME_ADVANTAGE_MULTIPLIER: float = 1.05

DATA_DIR: Path = Path(__file__).resolve().parent / "data"
GROUP_COUNT: int = 6
TEAMS_PER_GROUP: int = 4
MATCHES_PER_GROUP: int = 6
THIRD_PLACE_ADVANCERS: int = 4

ROUND_ORDER: list[str] = ["R16", "QF", "SF", "FINAL"]
ROUND_KEYS: dict[str, str] = {"QF": "qf", "SF": "sf", "FINAL": "final"}

DEFAULT_LEAGUE_ID: int = 3
POLL_INTERVAL: int = 60
