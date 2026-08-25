"""Root test configuration.

Makes the competitions' legacy ``src.*`` import style resolvable when root
tests import the web layer directly, independent of pytest collection
order. Both competition packages ship a ``src`` package and World Cup code
uses bare ``from src.x import ...``, so the worldcup directory must end up
BEFORE the ucl directory on sys.path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_wc = str(ROOT / "competitions" / "worldcup")
_ucl = str(ROOT / "competitions" / "ucl")

for entry in (_wc, _ucl):
    while entry in sys.path:
        sys.path.remove(entry)
# Insert ucl first, then worldcup, so worldcup wins for the bare "src" name.
sys.path.insert(0, _ucl)
sys.path.insert(0, _wc)
