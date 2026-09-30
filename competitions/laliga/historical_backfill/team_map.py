"""Canonical team-key mapping for the historical LaLiga backfill.

``canonical()`` maps ANY source spelling (football-data.co.uk SP1 fixture
files, the ClubElo archive mirror) to a single canonical key. Keys are the
exact strings from ``data/team_aliases.json`` (the long-form 2026/27
production key preferred wherever an alias is ambiguous), plus a small stable
set of keys for clubs absent from the production fixtures — i.e. clubs that
featured in La Liga 2019/20-2023/24 but are not in the 2026/27 20-team season
(see ``_ADDED_CANONICAL_KEYS``).

Resolution order:
    1. case-insensitive reverse lookup of ``data/team_aliases.json``
    2. explicit curated table (``_CURATED``) for spellings the alias file
       does not cover (diacritic variants, latinized forms, abbreviations)
    3. normalisation fallback: trailing 3-letter country tag stripped,
       diacritics folded, whitespace collapsed, then the alias / canonical
       lookups are re-run.

Unmappable input raises :class:`KeyError`; callers are expected to catch it
and fail loudly (unmapped teams are data errors). Building the tables is
pure and deterministic; importing this module has no side effects.

The resolution engine itself (and UCL's identical one) lives once in
``football_core.historical_backfill.TeamKeys``; this module is LaLiga's
curated-table configuration of it.
"""

from __future__ import annotations

import os

from football_core.historical_backfill import TeamKeys

_ALIASES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "team_aliases.json",
)

# Stable canonical keys for clubs absent from data/team_aliases.json (not in
# the 2026/27 20-team season but present in 2019/20-2023/24).
_ADDED_CANONICAL_KEYS: tuple[str, ...] = (
    "UD Almería",       # Almeria
    "Cádiz CF",         # Cadiz
    "SD Eibar",         # Eibar
    "Girona FC",        # Girona
    "Granada CF",       # Granada
    "SD Huesca",        # Huesca
    "UD Las Palmas",    # Las Palmas
    "CD Leganés",       # Leganes
    "RCD Mallorca",     # Mallorca
    "Real Valladolid CF",  # Valladolid
)

# Explicit spellings that survive neither the alias reverse lookup nor (on
# their own) normalisation: diacritic variants, latinized forms, and
# abbreviations as used by football-data.co.uk / ClubElo.
_CURATED: dict[str, str] = {
    # football-data.co.uk SP1 + ClubElo shared short spellings
    "Ath Bilbao": "Athletic Club",
    "Ath Madrid": "Club Atlético de Madrid",
    "Almeria": "UD Almería",
    "Cadiz": "Cádiz CF",
    "Celta": "RC Celta de Vigo",
    "Celta Vigo": "RC Celta de Vigo",
    "Eibar": "SD Eibar",
    "Espanol": "RCD Espanyol de Barcelona",
    "Girona": "Girona FC",
    "Granada": "Granada CF",
    "Huesca": "SD Huesca",
    "Las Palmas": "UD Las Palmas",
    "Leganes": "CD Leganés",
    "Mallorca": "RCD Mallorca",
    "Sociedad": "Real Sociedad de Fútbol",
    "Valladolid": "Real Valladolid CF",
    "Vallecano": "Rayo Vallecano de Madrid",
    # diacritic / latinized variants
    "Cadiz CF": "Cádiz CF",
    "Almeria CF": "UD Almería",
    "Eibar SD": "SD Eibar",
    "Huesca SD": "SD Huesca",
    "Leganes CD": "CD Leganés",
    "Las Palmas UD": "UD Las Palmas",
    "Mallorca RCD": "RCD Mallorca",
    "Valladolid Real": "Real Valladolid CF",
    "Girona FC": "Girona FC",
    "Granada CF": "Granada CF",
}

_KEYS = TeamKeys(_ALIASES_FILE, _CURATED, _ADDED_CANONICAL_KEYS)

# Full source-name -> canonical table for provenance / reporting.
canonical_map: dict[str, str] = _KEYS.canonical_map
CANONICAL_KEYS: list[str] = _KEYS.CANONICAL_KEYS
ALIAS_REV: dict[str, str] = _KEYS.ALIAS_REV
CURATED_REV: dict[str, str] = _KEYS.CURATED_REV
NORM_REV: dict[str, str] = _KEYS.NORM_REV

#: Map an arbitrary source team spelling to its canonical key.
#: Raises :class:`KeyError` if the team cannot be resolved.
canonical = _KEYS.canonical
#: True when *team* resolves to a canonical key (never raises).
is_known = _KEYS.is_known

__all__ = [
    "ALIAS_REV",
    "CANONICAL_KEYS",
    "CURATED_REV",
    "NORM_REV",
    "canonical",
    "canonical_map",
    "is_known",
]
