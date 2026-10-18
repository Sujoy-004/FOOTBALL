"""Logical-role → filename maps for the canonical store stamps (D-03).

RECON-03 requires the freshness stamp to key on the LOGICAL ROLE, never on the
physical filename or the file contents, so a role survives canonicalisation
rekeying. Each competition owns one plain map here; ``ROLES`` is the lookup a
migration plan uses (``ROLES["ucl"]``).

The maps mirror the availability maps already served by the apps
(``web/ucl_app.py`` ``_UCL_STORE_FILES``, ``web/laliga_app.py``
``_LALIGA_STORE_FILES``) so the stamp and the availability view can never
disagree about which store a role means. No logic, no imports beyond
``__future__``.
"""

from __future__ import annotations

#: World Cup 2026 canonical stores (teams/groups/bracket + the played ledger).
WC_ROLES: dict[str, str] = {
    "teams": "teams.json",
    "groups": "groups.json",
    "bracket": "bracket.json",
    "annex_c": "annex_c.json",
    "played": "played.json",
    "played_groups": "played_groups.json",
}

#: UEFA Champions League 2026/27 canonical stores (season-routed).
UCL_ROLES: dict[str, str] = {
    "league_results": "results.json",
    "fixtures": "fixtures.json",
    "knockout_results": "knockout_results.json",
}

#: LaLiga 2026/27 canonical stores (season-routed).
LALIGA_ROLES: dict[str, str] = {
    "fixtures": "fixtures.json",
    "results": "results.json",
}

#: Competition id -> role map, for a migration plan's ``ROLES["ucl"]`` lookup.
ROLES: dict[str, dict[str, str]] = {
    "worldcup": WC_ROLES,
    "ucl": UCL_ROLES,
    "laliga": LALIGA_ROLES,
}
