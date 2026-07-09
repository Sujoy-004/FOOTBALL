"""Scrape UCL 2025/26 results from Wikipedia.

Fetches league phase (144 matches) and knockout phase (playoffs + bracket)
from Wikipedia and outputs to results.json / knockout_results.json format.

Usage:
    python -m competitions.ucl.src.wikipedia_scraper [--output-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LEAGUE_PHASE_URL = (
    "https://en.wikipedia.org/wiki/"
    "2025%E2%80%9326_UEFA_Champions_League_league_phase"
)
KNOCKOUT_PHASE_URL = (
    "https://en.wikipedia.org/wiki/"
    "2025%E2%80%9326_UEFA_Champions_League_knockout_phase"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_ALIASES: dict[str, str] = {
    "paris saint-germain": "PSG",
    "psg": "PSG",
    "manchester city": "Man City",
    "man city": "Man City",
    "borussia dortmund": "Dortmund",
    "bayer leverkusen": "Bayer Leverkusen",
    "atlético madrid": "Atletico Madrid",
    "atletico madrid": "Atletico Madrid",
    "bodø/glimt": "Bodo/Glimt",
    "sporting cp": "Sporting",
    "sporting": "Sporting",
    "psv eindhoven": "PSV",
    "union saint-gilloise": "Union SG",
    "qarabağ": "Qarabag",
    "qarabag": "Qarabag",
    "club brugge": "Club Brugge",
    "slavia prague": "Slavia Prague",
    "eintracht frankfurt": "Eintracht Frankfurt",
    "athletic bilbao": "Athletic Bilbao",
    "inter milan": "Inter",
    "tottenham hotspur": "Tottenham",
    "newcastle united": "Newcastle",
    "real madrid": "Real Madrid",
    "bayern munich": "Bayern",
    "olympiacos": "Olympiacos",
    "juventus": "Juventus",
    "copenhagen": "Copenhagen",
    "barcelona": "Barcelona",
    "chelsea": "Chelsea",
    "arsenal": "Arsenal",
    "liverpool": "Liverpool",
    "atalanta": "Atalanta",
    "napoli": "Napoli",
    "ajax": "Ajax",
    "benfica": "Benfica",
    "monaco": "Monaco",
    "marseille": "Marseille",
    "pafos": "Pafos",
    "villarreal": "Villarreal",
    "galatasaray": "Galatasaray",
    "kairat": "Kairat",
}


def _normalise(name: str) -> str:
    cleaned = re.sub(r"[\[\(].*?[\]\)]", "", name).strip()
    cleaned = cleaned.replace("\u2011", "-").replace("\u2013", "-")
    cleaned = cleaned.replace("\u00a0", " ").replace("\u2010", "-")
    key = cleaned.lower().strip()
    return _ALIASES.get(key, cleaned)


def _find_matchday_sections(soup: BeautifulSoup) -> list[tuple[str, list[str]]]:
    results: list[tuple[str, list[str]]] = []

    for h3 in soup.find_all("h3"):
        heading_text = h3.get_text(" ", strip=True)
        if not re.search(r"Matchday\s+[1-8]", heading_text):
            continue

        parent_section = h3.find_parent("section")
        if not parent_section:
            continue

        lines: list[str] = []
        for table in parent_section.find_all("table", class_="fevent"):
            first_row = table.find("tr")
            if not first_row:
                continue
            cells = first_row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            home_raw = cells[0].get_text(" ", strip=True)
            score_raw = cells[1].get_text(" ", strip=True)
            away_raw = cells[2].get_text(" ", strip=True)
            score_raw = score_raw.replace("\u2013", "-").replace("\u2011", "-")
            m_score = re.match(r"(\d+)\s*[-–]\s*(\d+)", score_raw)
            if not m_score:
                continue
            h_str, a_str = m_score.groups()
            line = f"{home_raw} {h_str}-{a_str} {away_raw}"
            lines.append(line)

        if lines:
            results.append((heading_text, lines))

    return results


def scrape_league_phase() -> list[dict[str, Any]]:
    logger.info("Fetching league phase from %s", LEAGUE_PHASE_URL)
    resp = requests.get(LEAGUE_PHASE_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    sections = _find_matchday_sections(soup)

    matches: list[dict[str, Any]] = []
    for md_label, lines in sections:
        md_num = int(re.search(r"\d+", md_label).group())
        md_index = 0
        for line in lines:
            m = re.match(r"^(.+?)\s+(\d+)\s*[-]\s*(\d+)\s+(.+)$", line)
            if not m:
                continue
            home_raw, h_str, a_str, away_raw = m.groups()
            home = _normalise(home_raw.strip())
            away = _normalise(away_raw.strip())
            h, a = int(h_str), int(a_str)
            md_index += 1
            match_id = f"MD{md_num:02d}_{md_index:02d}"
            matches.append({
                "match_id": match_id,
                "team_a": home,
                "team_b": away,
                "home_score": h,
                "away_score": a,
            })

    logger.info("Scraped %d league matches across %d matchdays",
                len(matches), len(sections))
    return matches


# ── Knockout phase ────────────────────────────────────────────────────────────

def _find_ko_summary_tables(soup: BeautifulSoup) -> list[tuple[str, list[str]]]:
    round_map = {
        "Knockout phase play-offs": "playoff",
        "Round of 16": "R16",
        "Quarter-finals": "QF",
        "Semi-finals": "SF",
        "Final": "FINAL",
    }
    results: list[tuple[str, list[str]]] = []

    for section in soup.find_all("section"):
        h2 = section.find("h2")
        if not h2:
            continue
        heading_text = h2.get_text(" ", strip=True)
        rnd_name = None
        for key, val in round_map.items():
            if key in heading_text:
                rnd_name = val
                break
        if not rnd_name:
            continue

        for table in section.find_all("table"):
            if "sports-series" in table.get("class", []):
                rows: list[str] = []
                for tr in table.find_all("tr"):
                    cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                    if len(cells) >= 3:
                        rows.append("\t".join(cells))
                if rows:
                    results.append((rnd_name, rows))
                break
        else:
            if rnd_name == "FINAL":
                fevent = section.find("table", class_="fevent")
                if fevent:
                    all_rows = fevent.find_all("tr")
                    if all_rows:
                        first_cells = [c.get_text(" ", strip=True) for c in all_rows[0].find_all(["td", "th"])]
                        row_text = "\t".join(first_cells) if len(first_cells) >= 3 else ""
                        pen_info = ""
                        if len(all_rows) > 1:
                            last_cells = [c.get_text(" ", strip=True) for c in all_rows[-1].find_all(["td", "th"])]
                            pen_text = " ".join(last_cells)
                            m_pen = re.search(r"(\d+)\s*[-–]\s*(\d+)", pen_text)
                            if m_pen:
                                pen_info = f"{m_pen.group(1)}-{m_pen.group(2)}"
                        if row_text:
                            if pen_info:
                                row_text += f"\tpenalties:{pen_info}"
                            results.append((rnd_name, [row_text]))

    return results


def _parse_tab_row(cells: list[str]) -> list[str]:
    """Clean tab-separated cells: strip, remove en-dashes, clean markers."""
    out = []
    for c in cells:
        c = c.replace("\u2013", "-").replace("\u00a0", " ")
        c = re.sub(r"\s+", " ", c).strip()
        out.append(c)
    return out


def _parse_playoff_ties(rows: list[str]) -> list[dict[str, Any]]:
    ties: list[dict[str, Any]] = []
    for row in rows:
        cells = row.split("\t")
        if len(cells) < 5:
            continue
        cells = _parse_tab_row(cells)
        if "Tooltip" in cells[1] or "Agg" in cells[1] or "Team" in cells[0]:
            continue

        a_raw = cells[0]
        agg_raw = cells[1]
        b_raw = cells[2]

        m_agg = re.match(r"(\d+)[-–]\s*(\d+)", agg_raw)
        if not m_agg:
            continue

        a = _normalise(a_raw)
        b = _normalise(b_raw)
        agg_a, agg_b = int(m_agg.group(1)), int(m_agg.group(2))
        ties.append({
            "tie_num": len(ties) + 1,
            "team_a": a,
            "team_b": b,
            "aggregate_a": agg_a,
            "aggregate_b": agg_b,
            "winner": a if agg_a > agg_b else b,
        })

    return ties


def _parse_round_ties(rows: list[str], rnd: str) -> list[dict[str, Any]]:
    ties: list[dict[str, Any]] = []
    for row in rows:
        cells = row.split("\t")
        if len(cells) < 5 and rnd != "FINAL":
            continue
        if rnd == "FINAL" and len(cells) < 3:
            continue

        cells = _parse_tab_row(cells)

        if len(cells) >= 5:
            # Two-leg format: team_a, agg, team_b, leg1, leg2
            if "Tooltip" in cells[1] or "Agg" in cells[1] or "Team" in cells[0]:
                continue
            a_raw = cells[0]
            agg_raw = cells[1]
            b_raw = cells[2]
            m_agg = re.match(r"(\d+)[-–]\s*(\d+)", agg_raw)
            if not m_agg:
                continue
            a = _normalise(a_raw)
            b = _normalise(b_raw)
            agg_a, agg_b = int(m_agg.group(1)), int(m_agg.group(2))
            ties.append({
                "team_a": a,
                "team_b": b,
                "score_a": agg_a,
                "score_b": agg_b,
                "winner": a if agg_a > agg_b else b,
            })
        elif len(cells) >= 3 and rnd == "FINAL":
            a_raw = cells[0]
            score_raw = cells[1]
            b_raw = cells[2]
            pen_info = ""
            if len(cells) > 3 and cells[3].startswith("penalties:"):
                pen_info = cells[3].replace("penalties:", "")
            m_score = re.match(r"(\d+)[-–]\s*(\d+)", score_raw)
            if not m_score:
                continue
            a = _normalise(a_raw)
            b = _normalise(b_raw)
            sa, sb = int(m_score.group(1)), int(m_score.group(2))
            winner = a if sa > sb else b if sb > sa else a
            tie = {
                "team_a": a,
                "team_b": b,
                "score_a": sa,
                "score_b": sb,
                "winner": winner,
            }
            if sa == sb:
                if pen_info:
                    m_p = re.match(r"(\d+)[-–]\s*(\d+)", pen_info)
                    if m_p:
                        pen_a, pen_b = int(m_p.group(1)), int(m_p.group(2))
                        pen_winner = a if pen_a > pen_b else b
                        tie["winner"] = pen_winner
                        tie["penalties"] = {"winner": pen_winner, "score": pen_info}
                else:
                    tie["penalties"] = {"winner": None, "score": ""}
            ties.append(tie)

    return ties


def scrape_knockout_phase() -> dict[str, Any]:
    logger.info("Fetching knockout phase from %s", KNOCKOUT_PHASE_URL)
    resp = requests.get(KNOCKOUT_PHASE_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    summary_tables = _find_ko_summary_tables(soup)

    result: dict[str, Any] = {
        "playoff": [],
        "rounds": {"R16": [], "QF": [], "SF": [], "FINAL": []},
        "champion": "",
    }

    for rnd_name, rows in summary_tables:
        if rnd_name == "playoff":
            result["playoff"] = _parse_playoff_ties(rows)
        elif rnd_name in ("R16", "QF", "SF"):
            result["rounds"][rnd_name] = _parse_round_ties(rows, rnd_name)
        elif rnd_name == "FINAL":
            finals = _parse_round_ties(rows, "FINAL")
            result["rounds"]["FINAL"] = finals
            if finals:
                result["champion"] = finals[0]["winner"]

    logger.info(
        "Scraped %d playoff ties, %d R16, %d QF, %d SF, %d FINAL",
        len(result["playoff"]),
        len(result["rounds"]["R16"]),
        len(result["rounds"]["QF"]),
        len(result["rounds"]["SF"]),
        len(result["rounds"]["FINAL"]),
    )
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def _get_default_data_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Scrape UCL 2025/26 results from Wikipedia"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=_get_default_data_dir(),
        help="Output directory (default: data/)",
    )
    parser.add_argument(
        "--league-only", action="store_true",
        help="Only scrape league phase",
    )
    parser.add_argument(
        "--ko-only", action="store_true",
        help="Only scrape knockout phase",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    if not args.ko_only:
        league = scrape_league_phase()
        path = os.path.join(args.output_dir, "results.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"matches": league}, f, indent=2, ensure_ascii=False)
        logger.info("Wrote %d league matches to %s", len(league), path)

    if not args.league_only:
        ko = scrape_knockout_phase()
        path = os.path.join(args.output_dir, "knockout_results.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"matches": ko}, f, indent=2, ensure_ascii=False)
        logger.info("Wrote knockout data to %s", path)


if __name__ == "__main__":
    main()
