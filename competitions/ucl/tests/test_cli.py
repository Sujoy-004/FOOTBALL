"""Unit tests for the ucl-predict CLI argument parser.

Tests all flag behaviors: defaults, individual flags, combined flags,
and non-int rejection.
"""

from competitions.ucl.main import _parse_args


def test_defaults():
    """Empty argv returns default values."""
    args = _parse_args([])
    assert args.iterations == 10000
    assert args.seed is None
    assert args.output is None


def test_iterations_flag():
    """-n flag overrides iterations default."""
    args = _parse_args(["-n", "5000"])
    assert args.iterations == 5000


def test_seed_flag():
    """--seed flag sets seed value."""
    args = _parse_args(["--seed", "42"])
    assert args.seed == 42


def test_output_flag():
    """-o flag sets output file path."""
    args = _parse_args(["-o", "results.json"])
    assert args.output == "results.json"


def test_all_flags_together():
    """All three flags combined return correct namespace."""
    args = _parse_args(["-n", "5000", "--seed", "42", "-o", "out.json"])
    assert args.iterations == 5000
    assert args.seed == 42
    assert args.output == "out.json"


def test_seed_rejects_non_int():
    """--seed with non-int value raises SystemExit."""
    try:
        _parse_args(["--seed", "abc"])
        assert False, "Should have raised SystemExit"
    except SystemExit:
        pass
