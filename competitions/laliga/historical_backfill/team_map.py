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
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

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

# Character folds applied after NFKD decomposition (other marks are removed
# by the decomposition itself; these code points do not decompose).
_SPECIAL_FOLDS: dict[str, str] = {
    "ß": "ss",
    "ø": "o",
    "æ": "ae",
    "œ": "oe",
    "ł": "l",
    "đ": "d",
    "ı": "i",
}

_TAG_RE = re.compile(r"\s*\([a-z]{3}\)\s*$")
_WS_RE = re.compile(r"\s+")


def _plain(text: str) -> str:
    return text.strip().lower()


def _normalize(text: str) -> str:
    s = text.strip().lower()
    s = _TAG_RE.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for src, dst in _SPECIAL_FOLDS.items():
        s = s.replace(src, dst)
    return _WS_RE.sub(" ", s).strip()


def _load_aliases() -> dict[str, list[str]]:
    with open(_ALIASES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _prefer_long_form(orig: str, keys: list[str]) -> str:
    return max(keys, key=len)


# --- table construction (pure, deterministic, once at import) ---------------

ALIAS_REV: dict[str, str] = {}
CURATED_REV: dict[str, str] = {}
CANONICAL_KEYS: list[str] = []
NORM_REV: dict[str, str] = {}


def _build() -> None:
    raw = _load_aliases()

    alias_to_keys: dict[str, list[str]] = {}
    for canon in raw:
        # Identity: a canonical key is always a resolvable spelling of itself.
        alias_to_keys.setdefault(_plain(canon), []).append(canon)
        for alias in raw[canon]:
            alias_to_keys.setdefault(_plain(alias), []).append(canon)

    for canon in raw:
        for alias in raw[canon]:
            ALIAS_REV[_plain(alias)] = _prefer_long_form(alias, alias_to_keys[_plain(alias)])
        ALIAS_REV[_plain(canon)] = _prefer_long_form(canon, alias_to_keys[_plain(canon)])

    for source, canon in _CURATED.items():
        CURATED_REV[_plain(source)] = canon

    canonical_set: set[str] = set()
    for canon in ALIAS_REV.values():
        canonical_set.add(canon)
    for canon in raw:
        canonical_set.add(canon)
    for canon in _ADDED_CANONICAL_KEYS:
        canonical_set.add(canon)
    CANONICAL_KEYS.extend(sorted(canonical_set))

    for canon in CANONICAL_KEYS:
        NORM_REV.setdefault(_normalize(canon), canon)
    for canon in raw:
        for alias in raw[canon]:
            NORM_REV.setdefault(
                _normalize(alias),
                _prefer_long_form(alias, alias_to_keys[_plain(alias)]),
            )
    for source, canon in _CURATED.items():
        NORM_REV.setdefault(_normalize(source), canon)


_build()


def _resolve(team: str) -> str | None:
    plain = _plain(team)
    if not plain:
        return None
    key = ALIAS_REV.get(plain)
    if key is not None:
        return key
    key = CURATED_REV.get(plain)
    if key is not None:
        return key
    norm = _normalize(team)
    if not norm:
        return None
    return NORM_REV.get(norm)


def canonical(team: str) -> str:
    """Map an arbitrary source team spelling to its canonical key.

    Raises :class:`KeyError` if the team cannot be resolved.
    """
    if not isinstance(team, str) or not team.strip():
        raise KeyError(f"cannot canonicalise empty team key: {team!r}")
    key = _resolve(team)
    if key is None:
        raise KeyError(f"unmapped team key: {team!r}")
    return key


def is_known(team: str) -> bool:
    """True when *team* resolves to a canonical key (never raises)."""
    try:
        canonical(team)
    except KeyError:
        return False
    return True


# Full source-name -> canonical table for provenance / reporting.
canonical_map: dict[str, str] = {}

_raw = _load_aliases()
for _canon in _raw:
    for _alias in _raw[_canon]:
        canonical_map[_alias] = canonical(_alias)
for _source, _canon in _CURATED.items():
    canonical_map[_source] = _canon
for _key in CANONICAL_KEYS:
    canonical_map[_key] = canonical(_key)

del _raw, _canon, _alias, _source, _key