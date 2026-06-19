"""Tests for CLI argument parsing (Phase 6 — Plan 1)."""

from main import _parse_args


class TestParseArgs:
    """Unit tests for _parse_args()."""

    def test_defaults(self):
        """No flags → all defaults."""
        args = _parse_args([])
        assert args.once is False
        assert args.no_color is False
        assert args.seed is None

    def test_once_flag(self):
        """--once flag sets once=True."""
        args = _parse_args(["--once"])
        assert args.once is True

    def test_no_color_flag(self):
        """--no-color flag sets no_color=True."""
        args = _parse_args(["--no-color"])
        assert args.no_color is True

    def test_seed_flag(self):
        """--seed 42 sets seed=42."""
        args = _parse_args(["--seed", "42"])
        assert args.seed == 42

    def test_ai_preview_flag(self):
        """--ai-preview sets ai_preview=True."""
        args = _parse_args(["--ai-preview"])
        assert args.ai_preview is True

    def test_ai_preview_default(self):
        """Without --ai-preview, ai_preview is False."""
        args = _parse_args([])
        assert args.ai_preview is False

    def test_all_flags_together(self):
        """All flags work in combination."""
        args = _parse_args(["--once", "--no-color", "--seed", "123", "--ai-preview"])
        assert args.once is True
        assert args.no_color is True
        assert args.seed == 123
        assert args.ai_preview is True

    def test_seed_rejects_non_int(self):
        """--seed must be an integer → argparse raises SystemExit."""
        try:
            _parse_args(["--seed", "abc"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

    def test_unknown_flag_raises(self):
        """Unknown flags → SystemExit."""
        try:
            _parse_args(["--bogus"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

    def test_help_flag_prints_and_exits(self):
        """--help prints to stdout and exits."""
        try:
            _parse_args(["--help"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass
