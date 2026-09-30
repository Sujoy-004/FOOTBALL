"""LaLiga EA Sports — brain constants and composition-root paths.

20-team double round-robin (38 matchdays). Data source of record is
football-data.org (competition id ``PD``); BSD league id 3 exists but
returned an empty catalog when probed (Oct 2026), so live refresh uses
the FDO provider path unless the deployment forces BSD.
"""

from pathlib import Path

SRC_DIR = Path(__file__).parent
COMP_DIR = SRC_DIR.parent
DATA_DIR = COMP_DIR / "data"
CONFIG_DIR = COMP_DIR / "config"

# Fitted blend weights (schema-identical to competitions/ucl/config/signal_weights.json).
# Kept apart from CONFIG_DIR/"signal_weights.json", which is the deployed
# *engine* blend consumed by build_signal_engine and the backfill evaluation.
BLEND_CALIBRATION_PATH = CONFIG_DIR / "blend_calibration.json"
HISTORICAL_REPLAY_PATH = DATA_DIR / "historical" / "replay_2019_20_2023_24.json"

LALIGA_BSD_LEAGUE_ID = 3
LALIGA_FDO_COMPETITION_ID = "PD"

SHIPPED_SEASON = "2026/27"
SEASON_NAMESPACE = "laliga-season-fixture"

N_TEAMS = 20
N_MATCHDAYS = 38

GLOBAL_AVG_ELO = 1500.0