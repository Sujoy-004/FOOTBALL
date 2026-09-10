"""Canonical team-key mapping for the historical UCL backfill.

``canonical()`` maps ANY source spelling (openfootball cl.txt fixtures, the
ClubElo archive mirror, odds feeds) to a single canonical key. Keys are the
exact strings from ``data/team_aliases.json`` with the long-form 2026/27
production key preferred wherever an alias is ambiguous, plus a small stable
set of keys for clubs absent from the production fixtures (see
``_ADDED_CANONICAL_KEYS``).

Resolution order:
    1. case-insensitive reverse lookup of ``data/team_aliases.json``
       (an ambiguous alias resolves to its long-form 2026/27 key)
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

# Aliases that appear under more than one key must resolve to the long-form
# 2026/27 production key (see data/seasons/2026_27/fixtures.json).
_LONG_FORM: dict[str, str] = {
    "Bayern": "Bayern Munich",
    "FC Bayern München": "Bayern Munich",
    "Dortmund": "Borussia Dortmund",
    "Inter": "Inter Milan",
    "FC Internazionale Milano": "Inter Milan",
    "Man City": "Manchester City",
    "Manchester City FC": "Manchester City",
    "PSG": "Paris Saint-Germain",
    "Paris SG": "Paris Saint-Germain",
    "Paris Saint-Germain FC": "Paris Saint-Germain",
    "PSV": "PSV Eindhoven",
    "Sporting": "Sporting CP",
    "Sporting Clube de Portugal": "Sporting CP",
    "Bodoe Glimt": "Bodø/Glimt",
}

# Stable canonical keys for clubs absent from data/team_aliases.json.
_ADDED_CANONICAL_KEYS: tuple[str, ...] = (
    "Red Star Belgrade",
    "Dinamo Zagreb",
    "Zenit Saint Petersburg",
    "Lokomotiv Moscow",
    "Salzburg",
    "Genk",
    "Valencia",
    "Sevilla",
    "Lyon",
    "Rennes",
    "Celtic",
    "Rangers",
    "Midtjylland",
    "Ferencvaros",
    "Krasnodar",
    "Lazio",
    "AC Milan",
    "Malmö",
    "Young Boys",
    "Sheriff Tiraspol",
    "Ludogorets",
    "Braga",
    "Real Sociedad",
    "Antwerp",
    "Maccabi Haifa",
    "Viktoria Plzen",
    "Wolfsburg",
    "Union Berlin",
    "Borussia Monchengladbach",
    "Dynamo Kyiv",
    "Basaksehir",
    "Besiktas",
)

# Explicit spellings that survive neither the alias reverse lookup nor (on
# their own) normalisation: diacritic variants, latinized forms, and
# abbreviations as used by ClubElo / openfootball / odds feeds.
_CURATED: dict[str, str] = {
    # international / transliterated variants
    "Bayern München": "Bayern Munich",
    "Bayern Munchen": "Bayern Munich",
    "Olympiakos Piraeus": "Olympiacos",
    "Olympiacos Piraeus": "Olympiacos",
    "Crvena Zvezda": "Red Star Belgrade",
    "Red Star": "Red Star Belgrade",
    "FK Crvena Zvezda": "Red Star Belgrade",
    "Zenit Petersburg": "Zenit Saint Petersburg",
    "Zenit St Petersburg": "Zenit Saint Petersburg",
    "Zenit St. Petersburg": "Zenit Saint Petersburg",
    "Zenit": "Zenit Saint Petersburg",
    "Lokomotiv": "Lokomotiv Moscow",
    "Lokomotiv Moskva": "Lokomotiv Moscow",
    "Dinamo Kiev": "Dynamo Kyiv",
    "Dynamo Kiev": "Dynamo Kyiv",
    "Juve": "Juventus",
    "Internazionale": "Inter Milan",
    "Internazionale Milano": "Inter Milan",
    "Milan": "AC Milan",
    "Milan AC": "AC Milan",
    "Atlético": "Atletico Madrid",
    "Atlético Madrid": "Atletico Madrid",
    "Leipzig": "RB Leipzig",
    "Red Bull Leipzig": "RB Leipzig",
    "Red Bull Salzburg": "Salzburg",
    "RB Salzburg": "Salzburg",
    "FC Red Bull Salzburg": "Salzburg",
    "Borussia Mönchengladbach": "Borussia Monchengladbach",
    "Borussia M'gladbach": "Borussia Monchengladbach",
    "Borussia M. Gladbach": "Borussia Monchengladbach",
    "Bor. Mönchengladbach": "Borussia Monchengladbach",
    "Bor. Monchengladbach": "Borussia Monchengladbach",
    "Gladbach": "Borussia Monchengladbach",
    "Mönchengladbach": "Borussia Monchengladbach",
    "Monchengladbach": "Borussia Monchengladbach",
    "VfL Wolfsburg": "Wolfsburg",
    "KRC Genk": "Genk",
    "Racing Genk": "Genk",
    "Olympique Lyonnais": "Lyon",
    "Olympique Lyon": "Lyon",
    "Olympique Marseille": "Marseille",
    "Stade Rennais": "Rennes",
    "Stade Rennais FC": "Rennes",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Sporting Lisbon": "Sporting CP",
    "Sporting Lisboa": "Sporting CP",
    "SL Benfica": "Benfica",
    "Benfica Lisbon": "Benfica",
    "Ajax Amsterdam": "Ajax",
    "FC Copenhagen": "Copenhagen",
    "F.C. Copenhagen": "Copenhagen",
    "Kobenhavn": "Copenhagen",
    "København": "Copenhagen",
    "FC Midtjylland": "Midtjylland",
    "Malmö FF": "Malmö",
    "Malmo": "Malmö",
    "Malmo FF": "Malmö",
    "Malmoe": "Malmö",
    "Malmoe FF": "Malmö",
    "SC Braga": "Braga",
    "Sporting Braga": "Braga",
    "Sporting Clube de Braga": "Braga",
    "Glasgow Celtic": "Celtic",
    "Celtic FC": "Celtic",
    "Glasgow Rangers": "Rangers",
    "Rangers FC": "Rangers",
    "BSC Young Boys": "Young Boys",
    "YB Bern": "Young Boys",
    "Y.B. Bern": "Young Boys",
    "Young Boys Bern": "Young Boys",
    "GNK Dinamo Zagreb": "Dinamo Zagreb",
    "FK Krasnodar": "Krasnodar",
    "Ludogorets Razgrad": "Ludogorets",
    "Sheriff": "Sheriff Tiraspol",
    "FC Sheriff": "Sheriff Tiraspol",
    "SS Lazio": "Lazio",
    "Lazio Roma": "Lazio",
    "Atalanta Bergamo": "Atalanta",
    "Ferencváros": "Ferencvaros",
    "Ferencvárosi TC": "Ferencvaros",
    "Ferencvarosi TC": "Ferencvaros",
    "Viktoria Plzeň": "Viktoria Plzen",
    "Viktoria Pilsen": "Viktoria Plzen",
    "Maccabi Haifa FC": "Maccabi Haifa",
    "Real Sociedad de Futbol": "Real Sociedad",
    "FK Qarabag": "Qarabag",
    "Union Saint-Gilloise": "Union SG",
    "Union St. Gilloise": "Union SG",
    "St. Gilloise": "Union SG",
    "LOSC": "Lille",
    "Racing Club de Lens": "Lens",
    "1. FC Union Berlin": "Union Berlin",
    "Man Utd": "Manchester United",
    "Spurs": "Tottenham",
    "Tottenham Hotspur": "Tottenham",
    "Istanbul Basaksehir": "Basaksehir",
    "Istanbul Basakşehir": "Basaksehir",
    "Medipol Basaksehir": "Basaksehir",
    "Başakşehir": "Basaksehir",
    "Beşiktaş": "Besiktas",
    "Royal Antwerp": "Antwerp",
    "Antwerp FC": "Antwerp",
    "Royal Antwerp FC": "Antwerp",
    "FK Bodø/Glimt": "Bodø/Glimt",
    # ClubElo archive mirror (xgabora) abbreviated club names
    "Ath Madrid": "Atletico Madrid",
    "Ath Bilbao": "Athletic Bilbao",
    "Sp Lisbon": "Sporting CP",
    "Sp Braga": "Braga",
    "Lok Moskva": "Lokomotiv Moscow",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "MGladbach": "Borussia Monchengladbach",
    "M'gladbach": "Borussia Monchengladbach",
    "FC Krasnodar": "Krasnodar",
    "Sociedad": "Real Sociedad",
    "Buyuksehyr": "Basaksehir",
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
    long_form = _LONG_FORM.get(orig)
    if long_form is not None and long_form in keys:
        return long_form
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
        # Identity: a canonical key is always a resolvable spelling of itself,
        # so the reverse lookup is direction-consistent even when alias lists
        # are asymmetric (e.g. "Borussia Dortmund" -> "Dortmund" key but the
        # long form is the preferred canonical).
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


# Full source-name -> canonical table for provenance / reporting. Order is
# stable: json aliases (in file order), then curated spellings, then every
# canonical key itself.
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