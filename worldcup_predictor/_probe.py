"""BSD API probe — capture raw event payloads before any processing."""
import json, os, sys
from datetime import datetime

import requests

API_KEY = os.environ.get("BSD_API_KEY", "REPLACED_BSD_API_KEY")
LEAGUE_ID = 27
WC_START = "2026-06-11"
TODAY = datetime.now().strftime("%Y-%m-%d")

def fetch_all_events(url: str) -> list[dict]:
    headers = {"Authorization": f"Token {API_KEY}"}
    all_events = []
    while url:
        print(f"  Fetching: {url}", file=sys.stderr)
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        all_events.extend(data.get("results", []))
        url = data.get("next")
    return all_events

# --- Historical: completed matches ---
hist_url = f"https://sports.bzzoiro.com/api/events/?league_id={LEAGUE_ID}&date_from={WC_START}&date_to={TODAY}&limit=200"
print("=== Fetching events from WC start to today ===", file=sys.stderr)
all_events = fetch_all_events(hist_url)
print(f"  Total events fetched: {len(all_events)}", file=sys.stderr)

# Filter league 27
events = [e for e in all_events if isinstance(e.get("league"), dict) and e["league"].get("id") == LEAGUE_ID]
print(f"  League {LEAGUE_ID} events: {len(events)}", file=sys.stderr)

finished = [e for e in events if e.get("status") == "finished"]
upcoming = [e for e in events if e.get("status") != "finished"]

print(f"  Finished: {len(finished)}", file=sys.stderr)
other_statuses = set(e.get("status") for e in events if e.get("status") != "finished")
print(f"  Other statuses: {other_statuses}", file=sys.stderr)
print(f"  Upcoming/other count: {len(upcoming)}", file=sys.stderr)

os.makedirs("_probe", exist_ok=True)

# Save completed match
if finished:
    cm = finished[0]
    mid = cm.get("id")
    home = cm.get("home_team", "?")
    away = cm.get("away_team", "?")
    print(f"\nCompleted match: id={mid} {home} vs {away} ({len(cm)} fields)", file=sys.stderr)
    with open("_probe/completed_match_raw.json", "w") as f:
        json.dump(cm, f, indent=2, default=str)
else:
    print("WARNING: No finished matches found", file=sys.stderr)

# Save upcoming match
if upcoming:
    um = upcoming[0]
    mid = um.get("id")
    home = um.get("home_team", "?")
    away = um.get("away_team", "?")
    print(f"Upcoming match: id={mid} {home} vs {away} ({len(um)} fields)", file=sys.stderr)
    with open("_probe/upcoming_match_raw.json", "w") as f:
        json.dump(um, f, indent=2, default=str)
else:
    print("WARNING: No upcoming matches found", file=sys.stderr)

# Also dump ALL field names from first finished event for full schema visibility
if finished:
    print("\n=== ALL FIELDS (completed match) ===", file=sys.stderr)
    for k, v in sorted(finished[0].items()):
        t = type(v).__name__
        val = str(v)[:120]
        print(f"  {k:35s} {t:10s} {val}", file=sys.stderr)

if upcoming:
    print("\n=== ALL FIELDS (upcoming match) ===", file=sys.stderr)
    for k, v in sorted(upcoming[0].items()):
        t = type(v).__name__
        val = str(v)[:120]
        print(f"  {k:35s} {t:10s} {val}", file=sys.stderr)

# Save the full results list too (meta info)
print(f"\nDone. {len(finished)} finished, {len(upcoming)} upcoming", file=sys.stderr)
print("Probe files saved to _probe/", file=sys.stderr)
