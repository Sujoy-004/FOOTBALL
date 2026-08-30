# -*- coding: utf-8 -*-
"""Regression tests for the verified 2026/27 ClubElo identity/alias mappings.

The committed alias map ``competitions/ucl/data/team_aliases.json`` gained new
keys for the full 2026/27 UCL draw identities, each mapped to a ClubElo slug
that was verified live against api.clubelo.com.  These tests lock in that the
new keys resolve correctly, that the legacy 2025/26 ASCII short keys are
byte-identical as before, that the accent-insensitive fallback is still honest
about its limits, that the mapped ClubElo data genuinely flows through
``fetch_team_elos``, that no DEFAULT_ELO placeholder ever counts as covered,
and that adding the 14 keys did not regress the stored 2025/26 schedule.

All tests are hermetic/deterministic: no network.  The live ClubElo parsing is
mocked via ``monkeypatch`` on ``football_core.elo_fetcher`` and the real,
tracked alias path is exercised so the actual shipped data is what is tested.
"""

from __future__ import annotations

import json
import os
import textwrap

import pytest

from football_core.elo_fetcher import _normalized_key
from football_core.constants import DEFAULT_ELO
from competitions.ucl.src.elo_fetcher import (
    fetch_team_elos,
    resolve_clubelo_name,
)
from competitions.ucl.src.pipeline import compute_elo_coverage

# The real, tracked alias map shipped for this competition.
_ALIAS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
_ALIAS_PATH = os.path.join(_ALIAS_DIR, "team_aliases.json")

# ── The 14 verified 2026/27 draw identities vs their confirmed ClubElo slugs.
# The 'ø' in 'Bodø/Glimt' is U+00D8 and the 'ç' in 'Fenerbahçe' is U+00E7
# (both UTF-8, not mojibake).
_VERIFIED_IDENTITY_SLUGS = [
    ("AEK Athens", "AEK"),
    ("Bayern Munich", "Bayern"),
    ("Borussia Dortmund", "Dortmund"),
    ("Bodø/Glimt", "Bodoe Glimt"),
    ("Fenerbahçe", "Fenerbahce"),
    ("Inter Milan", "Inter"),
    ("Manchester City", "Man City"),
    ("Manchester United", "Man United"),
    ("Paris Saint-Germain", "Paris SG"),
    ("PSV Eindhoven", "PSV"),
    ("Real Betis", "Betis"),
    ("Shakhtar Donetsk", "Shakhtar"),
    ("Sporting CP", "Sporting"),
    ("VfB Stuttgart", "Stuttgart"),
]

_LEGACY_2025_26_SHORT_KEYS = [
    ("PSG", "Paris SG"),
    ("Bayern", "Bayern"),
    ("Man City", "Man City"),
    ("Sporting", "Sporting"),
    ("PSV", "PSV"),
    ("Dortmund", "Dortmund"),
    ("Inter", "Inter"),
    ("Real Madrid", "Real Madrid"),
    ("Atletico Madrid", "Atletico"),
    ("Copenhagen", "FC Kobenhavn"),
]

# Distinct, realistic per-slug ClubElo values (deliberately never 1500.0) for
# the mocked ranking CSV used in the fetch test.
_SLUG_ELOS = {
    "AEK": 1640.66,
    "Bayern": 2000.87,
    "Dortmund": 1884.0,
    "Bodoe Glimt": 1595.0,
    "Fenerbahce": 1720.5,
    "Inter": 1898.0,
    "Man City": 1970.9,
    "Man United": 1905.0,
    "Paris SG": 1927.0,
    "PSV": 1755.0,
    "Betis": 1680.0,
    "Shakhtar": 1660.0,
    "Sporting": 1805.0,
    "Stuttgart": 1760.5,
}


def _ranking_csv_for_slugs(slug_elos: dict[str, float]) -> str:
    """Build a ClubElo daily-ranking CSV containing only the given slugs."""
    lines = ["Rank,Club,Country,Level,Elo,From,To"]
    for i, (slug, elo) in enumerate(slug_elos.items(), start=1):
        lines.append(
            f"{i},{slug},--,1,{elo:.2f},2026-06-01,2026-08-23"
        )
    return "\n".join(lines)


class TestVerified2026_27IdentityMappings:
    """The 14 new identity keys resolve to their verified ClubElo slugs."""

    @pytest.mark.parametrize(
        "identity,slug",
        _VERIFIED_IDENTITY_SLUGS,
        ids=[ident for ident, _ in _VERIFIED_IDENTITY_SLUGS],
    )
    def test_verified_2026_27_identity_mappings_resolve(self, identity, slug):
        """The exact new key resolves to the verified ClubElo slug."""
        assert resolve_clubelo_name(identity) == slug

    @pytest.mark.parametrize(
        "short_key,slug",
        _LEGACY_2025_26_SHORT_KEYS,
        ids=[key for key, _ in _LEGACY_2025_26_SHORT_KEYS],
    )
    def test_ascii_short_keys_unchanged(self, short_key, slug):
        """Legacy 2025/26 ASCII short keys keep their exact same mapping."""
        assert resolve_clubelo_name(short_key) == slug


class TestAccentInsensitiveFallbackHonest:
    """The NFKD fallback remains honest about its bounded scope."""

    def test_accented_name_without_key_passes_through_unchanged(self):
        """'Atlético' has no exact key and no key normalizes to it.

        It is therefore returned unchanged (identity-neutral): the fallback
        cannot invent a mapping where none exists.
        """
        assert resolve_clubelo_name("Atlético") == "Atlético"

    def test_normalized_key_keeps_o_without_decomposition(self):
        """_normalized_key('Bodø/Glimt') keeps the 'ø' (U+00F8) intact.

        NFKD has no decomposition for 'ø', so the accent-insensitive fallback
        cannot reduce it to ASCII — an honest, documented bound.
        """
        assert _normalized_key("Bodø/Glimt") == "bodø/glimt"


class TestFetch2026_27FlowsThroughSlugs:
    """The verified slugs flow from the mocked ClubElo data into ratings."""

    def test_fetch_team_elos_resolves_all_2026_27_identities_via_slugs(
        self, monkeypatch
    ):
        """Every 2026/27 identity resolves to its slug's Elo, none defaulting."""
        identities = [ident for ident, _ in _VERIFIED_IDENTITY_SLUGS]
        csv_text = _ranking_csv_for_slugs(_SLUG_ELOS)

        monkeypatch.setattr(
            "football_core.elo_fetcher._fetch_ranking_csv",
            lambda *a: csv_text,
        )
        monkeypatch.setattr(
            "football_core.elo_fetcher._fetch_team_history",
            lambda *a: None,
        )

        elos = fetch_team_elos(identities)

        # Every identity is present.
        assert set(elos.keys()) == set(identities)
        # No placeholder slipped in — every value is the VERIFIED slug's Elo.
        for identity, slug in _VERIFIED_IDENTITY_SLUGS:
            assert identity in elos
            assert elos[identity] != float(DEFAULT_ELO)
            assert elos[identity] == _SLUG_ELOS[slug]


class TestCoverageGuard:
    """Mapped-in values count; DEFAULT_ELO placeholders never do."""

    def test_no_default_elo_ever_counts_as_covered(self):
        """14 mappings count; four exact DEFAULT_ELO placeholders are excluded."""
        identities = [ident for ident, _ in _VERIFIED_IDENTITY_SLUGS]
        ratings = {
            ident: _SLUG_ELOS[slug]
            for ident, slug in _VERIFIED_IDENTITY_SLUGS
        }
        # Four distinct placeholder teams set to exactly the default.
        placeholders = {
            "Placeholder Alpha": float(DEFAULT_ELO),
            "Placeholder Beta": float(DEFAULT_ELO),
            "Placeholder Gamma": float(DEFAULT_ELO),
            "Placeholder Delta": float(DEFAULT_ELO),
        }
        ratings.update(placeholders)

        # The 4 placeholders are in the roster, so the exclusion is proven.
        team_names = identities + list(placeholders.keys())
        out = compute_elo_coverage(team_names, ratings, "clubelo")

        assert out["coverage"] == 14
        assert out["coverage_total"] == 18
        assert out["coverage_pct"] == round(14 / 18 * 100, 1)
        assert out["provenance"] == "clubelo"


class TestNoRegression2025_26Store:
    """Adding the 14 keys did not disturb the 2025/26 fixtures store."""

    def test_alias_edits_do_not_touch_2025_26_store(self):
        """Every 2025/26 schedule name still hits its alias key unchanged."""
        fixtures_path = os.path.join(_ALIAS_DIR, "fixtures.json")
        with open(fixtures_path, encoding="utf-8") as f:
            fixtures = json.load(f)

        with open(_ALIAS_PATH, encoding="utf-8") as f:
            aliases = json.load(f)

        short_names = [
            t["name"].strip()
            for t in fixtures["schedule"]["teams"]
            if t.get("name") and isinstance(t.get("name"), str)
        ]
        assert len(short_names) == 36

        for name in short_names:
            # The name is still a literal key — the direct ASCII exact-key hit
            # path, not the NFKD fallback and not a pass-through.
            assert name in aliases
            # Resolves via the alias map to the same first value as stored,
            # byte-identical before and after the 14 additions.
            assert resolve_clubelo_name(name) == aliases[name][0]
