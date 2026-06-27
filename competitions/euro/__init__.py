"""Euro 2024 Predictor — uses football_core for generic tournament primitives."""
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_wc_pkg = str(Path(__file__).resolve().parent.parent / "worldcup")
if _wc_pkg not in sys.path:
    sys.path.insert(0, _wc_pkg)
