"""Root test configuration.

Makes the competitions' legacy ``src.*`` import style resolvable when root
tests import the web layer directly, independent of pytest collection
order (competitions/*/tests/conftest.py does the same for its own tests).

Insertion order matters: both competition packages ship a ``src`` package
and World Cup code uses bare ``from src.x import ...``, so the worldcup
directory must end up FIRST on sys.path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for rel in ("competitions/ucl", "competitions/worldcup"):
    candidate = str(ROOT / rel)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

assert sys.path.index(str(ROOT / "competitions" / "worldcup")) < \
    sys.path.index(str(ROOT / "competitions" / "ucl"))
