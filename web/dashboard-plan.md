# Production Tabbed Dashboard — Plan

## Backend (server.py)
- Add `GET /api/bracket/full` — resolves all 5 rounds (R32→R16→QF→SF→Final+TPP) with actual team names, scores, winners, and prediction probabilities

## Frontend — Complete `index.html` rewrite

Keep warm plum/cream palette, modern tabbed layout:

| Tab | Content | Data source |
|---|---|---|
| **Dashboard** | Champion % bar chart (top 10, animated CSS bars), top-4 team cards with QF/SF/Final/Champion rings, quick stats row, eval summary with color-coded Brier | `/api/data`, `/api/evaluation` |
| **Bracket** | Visual tree — 5 rounds as columns, match cards with team + score, winners highlighted, click for signal breakdown popup | `/api/bracket/full`, `/api/signal/{name}` |
| **Standings** | 12 group tables with green/amber/red rows, third-place cutoff | `/api/standings` |
| **Terminal** | Existing `$` prompt with all 18 commands, preserved as-is | all existing endpoints |

## Constraints
- No external libraries — pure CSS bars, CSS Grid bracket, vanilla JS
- All data from existing + minimal new API endpoints
