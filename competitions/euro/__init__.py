"""Euro 2024 Predictor — uses worldcup_predictor.src for generic modules."""
import sys
from pathlib import Path

_wc_path = str(Path(__file__).resolve().parent.parent.parent / "worldcup_predictor")
if _wc_path not in sys.path:
    sys.path.insert(0, _wc_path)
