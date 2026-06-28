"""UEFA Champions League 2025/26 competition package."""
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from competitions.ucl.result import SimulationResult
from competitions.ucl.main import main

__all__ = [
    "SimulationResult",
    "main",
]
