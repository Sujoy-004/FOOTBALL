"""Unit tests for the knockout stage vocabulary helpers (Exchange 2).

The helpers are the single source of truth for stage ordering/labels served
with bracket payloads; generic consumers may import them from the worldcup
pipeline.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Import bootstrap (mirrors tests/conftest.py): worldcup must precede ucl on
# sys.path so the bare ``src`` name resolves to the World Cup package.
_UCL = str(ROOT / "competitions" / "ucl")
_WC = str(ROOT / "competitions" / "worldcup")
for _entry in (_UCL, _WC, str(ROOT)):
    while _entry in sys.path:
        sys.path.remove(_entry)
sys.path.insert(0, _UCL)
sys.path.insert(0, _WC)
sys.path.insert(0, str(ROOT))

from src.pipeline import bracket_stage_labels, bracket_stage_order


EXPECTED_ORDER = ["R32", "R16", "QF", "SF", "TPP", "FINAL"]


def test_bracket_stage_order_is_complete_and_ordered():
    """All six WC knockout stages present, in tournament play order."""
    assert bracket_stage_order() == EXPECTED_ORDER


def test_bracket_stage_order_includes_tpp_before_final():
    """Third-place play-off is part of the vocabulary, staged before Final."""
    order = bracket_stage_order()
    assert "TPP" in order
    assert order.index("TPP") < order.index("FINAL")


def test_bracket_stage_order_has_no_duplicates():
    order = bracket_stage_order()
    assert len(order) == len(set(order))


def test_bracket_stage_labels_cover_every_stage():
    """Labels are defined for exactly the canonical stage set."""
    labels = bracket_stage_labels()
    assert set(labels.keys()) == set(bracket_stage_order())


def test_bracket_stage_labels_are_non_empty_strings():
    for code, label in bracket_stage_labels().items():
        assert isinstance(label, str), f"label for {code} must be a string"
        assert label.strip(), f"label for {code} must be non-empty"


def test_stage_helpers_are_deterministic():
    assert bracket_stage_order() == bracket_stage_order()
    assert bracket_stage_labels() == bracket_stage_labels()
