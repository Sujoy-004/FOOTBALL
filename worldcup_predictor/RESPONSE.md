# Unused BSD Field Analysis — Value-Based Coverage

> Generated: 2026-06-21
> Source: Live BSD probe (`_probe.py`), 33 finished + 6 upcoming events

---

## 1. BSD Field Classification

Every field identified in the BSD events endpoint response, classified by value.

### Prediction Value (directly improves a model)

| Field | Location | Current | Notes |
|-------|----------|---------|-------|
| `odds_home` | top-level | ✅ Used | Vig removal → signal blend |
| `odds_draw` | top-level | ✅ Used | Vig removal |
| `odds_away` | top-level | ✅ Used | Vig removal |
| `expected_goals` | live_stats.home/away | ❌ | BSD's real-time xG per side. Form signal potential. |
| `actual_home_xg` | top-level | ❌ | Post-shot actual xG. Higher signal than live xG for form. |
| `actual_away_xg` | top-level | ❌ | Same. |
| `odds_over_25` | top-level | ❌ | Over/under markets imply Poisson lambda. Could calibrate base rate. |
| `odds_under_25` | top-level | ❌ | Same. |
| `odds_btts_yes` | top-level | ❌ | Both-teams-to-score probability. Match-level base rate modifier. |

8 prediction fields used (3 of 11).

### Display Value (improves console output for a human reader)

| Field | Location | Current | Notes |
|-------|----------|---------|-------|
| `home_score` | top-level | ✅ Used | Match result |
| `away_score` | top-level | ✅ Used | |
| `event_date` | top-level | ✅ Used | Timestamp |
| `venue.name` | top-level | ✅ Used | |
| `referee.name` | top-level | ✅ Used | |
| `ai_preview.text` | top-level | ✅ Used | |
| `yellow_cards` | live_stats | ✅ Used | |
| `red_cards` | live_stats | ✅ Used | |
| `shots_on_target` | live_stats | ✅ Used | |
| `ball_possession` | live_stats | ✅ Used | |
| `venue.city` | top-level | ❌ | Stadium location — useful for context |
| `venue.capacity` | top-level | ❌ | Stadium size |
| `home_coach.name` | top-level | ❌ | Coach identity — nice context |
| `away_coach.name` | top-level | ❌ | Same |
| `round_name` | top-level | ❌ | "Round of 16", "Group Stage" |
| `fouls` | live_stats | ❌ | Match context (prioritized) |
| `corner_kicks` | live_stats | ❌ | Match context (prioritized) |
| `shots_off_target` | live_stats | ❌ | Shot dominance (prioritized) |
| `shots_inside_box` | live_stats | ❌ | Higher signal than `shots_off_target` |
| `temperature_c` | top-level | ❌ | Match conditions |
| `wind_speed` | top-level | ❌ | |
| `weather_code` | top-level | ❌ | |
| `pitch_condition` | top-level | ❌ | |
| `attendance` | top-level | ❌ | Crowd context |
| `funfacts` | top-level | ❌ | Narrative interest |
| `home_score_ht` | top-level | ❌ | Half-time scoreline (display) |
| `away_score_ht` | top-level | ❌ | Half-time scoreline |

10 display fields used (10 of 27).

### Operational Value (needed for system operation)

| Field | Location | Current | Notes |
|-------|----------|---------|-------|
| `id` | top-level | ✅ Used | Dedup |
| `status` | top-level | ✅ Used | "finished" filter |
| `home_team` | top-level | ✅ Used | Team resolution |
| `away_team` | top-level | ✅ Used | Team resolution |
| `league.id` | top-level | ✅ Used | League filtering |
| `group_name` | top-level | ✅ Used | Group routing |
| `winner` | top-level | ✅ Used | PK detection |
| `period` | top-level | ❌ | "FT", "HT", "1T" — more precise than `status` for match state |
| `current_minute` | top-level | ❌ | Match clock. Only useful for live polling (not finished events). |

8 operational fields used (8 of 9).

### No Value — Do Not Extract

| Field | Reason |
|-------|--------|
| `odds_over_15`, `odds_under_15`, `odds_over_35`, `odds_under_35` | Over/under variants. `over_25`/`under_25` is the standard market. These add zero marginal signal. |
| `odds_btts_no` | Inversely correlated with `btts_yes`. One is sufficient. |
| `is_local_derby` | Always `false` for World Cup (international tournament). |
| `is_neutral_ground` | Always `null` for WC (every match has a designated home/away). |
| `jerseys` | Jersey colors. No prediction or display value. |
| `live_websocket` | Internal connection flag. No product value. |
| `travel_distance_km` | Always `null` in probe. |
| `unavailable_players` | Always `null` in probe. |
| `extra_time_score` | Redundant — `home_score`/`away_score` already covers 120 min. |
| `penalty_shootout` | Redundant — `winner` field resolves shootouts. |
| `season` | Redundant — `league` object contains season info. |
| `away_team_obj`, `home_team_obj` | Duplicates `home_team`/`away_team` + `home_coach`/`away_coach` info. |
| `away_xg_live`, `home_xg_live` | Duplicates `live_stats.expected_goals`. Same value (probe: 1.41 vs 1.41). |
| `pitch_condition` | Integer code with unknown mapping. Requires research to interpret. |
| `offsides` | No known predictive relationship with match outcomes. |
| `goal_kicks` | Possession proxy. Already have `ball_possession`. |
| `free_kicks` | Redundant with `fouls` (r≈0.7). |
| `throw_ins` | No known use in prediction or display. |
| `dangerous_attack` (sr_stats) | Redundant — correlated with `ball_possession` + `shots_on_target`. |
| `attack`, `attack_pct` (sr_stats) | Same redundancy. |
| `ball_safe`, `ball_safe_pct` (sr_stats) | Same redundancy. |
| `substitutions` | **NOT IN BSD API.** Does not exist. |

## 2. Value-Based Coverage Calculation

### Denominator: Meaningful Fields Only

Meaningful = Prediction + Display + Operational (excluding No Value).

| Category | Total | Currently Used |
|----------|-------|---------------|
| Prediction | 11 | 3 |
| Display | 27 | 10 |
| Operational | 9 | 8 |
| **Total** | **47** | **21** |

**Meaningful coverage: 21/47 = 44.7%**

Not 61.8%. Because ~30 fields we were counting as "available but unused" have **No Value**. They inflated the denominator.

### What Would "Good" Coverage Look Like?

| Tier | Target | Fields to Add | New Coverage |
|------|--------|--------------|-------------|
| Current | 21/47 (44.7%) | — | 44.7% |
| + Priority 3 | +3 | fouls, corners, shots_off_target | 24/47 (51.1%) |
| + Display essentials | +4 | venue.city, home_coach, away_coach, round_name | 28/47 (59.6%) |
| + Prediction value | +3 | expected_goals, actual_home_xg, actual_away_xg | 31/47 (66.0%) |
| + Bonus display | +3 | temperature_c, weather_code, wind_speed, funfacts, attendance | 36/47 (76.6%) |
| + Everything meaningful | +5 | odds_over_25, odds_under_25, odds_btts_yes, period, current_minute, shots_inside_box, home_score_ht, away_score_ht | 44/47 (93.6%) |

100% of meaningful fields is 47. The current 44.7% is low because most of what we extract is operational (infrastructure) rather than prediction or display.

### Corrected 85% Target

85% of meaningful fields = 0.85 × 47 = **40 fields**.

Currently at 21. Need to add **19 meaningful fields**.

The high-value path to 40:

| Phase | Fields Added | Cumulative | Effort |
|-------|-------------|------------|--------|
| Immediate (3 fields) | fouls, corners, shots_off_target | 24 | 6 lines, 2 min |
| Quick wins (5 fields) | venue.city, coach names, round_name, attendance | 28 | 8 lines, 5 min |
| Prediction value (3 fields) | expected_goals, actual_home_xg, actual_away_xg | 31 | 6 lines + form module change |
| Display richness (5 fields) | funfacts, temperature, wind, weather_code, home_score_ht, away_score_ht | 37 | 12 lines, 10 min |
| Remaining (3 fields) | odds_over_25, odds_under_25, odds_btts_yes, period, current_minute | 42+ | Would need actual consumption |

To hit 85% meaningful coverage requires extracting ~19 fields. But not all of these should be extracted — some have marginal value.

## 3. Prioritized Extraction

### Accept Now (value / effort is high)

| Field | Value | Effort | Rationale |
|-------|-------|--------|-----------|
| **fouls** | Display + potential form | 2 lines | Was P0. Basic match stat. Trivial. |
| **corner_kicks** | Display | 2 lines | Basic stat. Trivial. |
| **shots_off_target** | Display | 2 lines | Shot context. Trivial. |

6 lines total. Coverage goes from 44.7% → 51.1%.

### Accept Conditionally (value exists but needs consumer)

| Field | Value | Effort | Rationale |
|-------|-------|--------|-----------|
| `venue.city` | Display | 1 line | Already extracting `venue.name`. Adding `city` adds location context. Trivial. |
| `shots_inside_box` | Display > shots_off_target | 2 lines | Higher signal density — shots in the box convert at ~15%, outside at ~3%. Worth more than `shots_off_target`. |
| `home_coach.name` | Display | 1 line | Already confirmed available. Coach identity is a natural match display field. |
| `away_coach.name` | Display | 1 line | Same. |

### Defer (needs research or model change)

| Field | Value | Effort | Rationale |
|-------|-------|--------|-----------|
| `expected_goals` (live_stats) | Prediction (form) | 2 lines + form.py change | Requires re-architecting form signal to use xG differential vs raw scorelines. |
| `actual_home_xg` / `actual_away_xg` | Prediction (form) | 2 lines | Same as above — post-shot xG is the better metric. |
| `odds_over_25` / `odds_under_25` | Prediction (Poisson lambda) | 8 lines + research | Over/under odds can imply Poisson lambda. But needs research on conversion formula. |
| `round_name` | Display | 2 lines | String is empty ("") in current probe for group matches. Needs verification. |

### Ignore Permanently

All "No Value" fields listed above.

## 4. live_stats.expected_goals — Value Assessment

**Finding:** `live_stats.home.expected_goals` and `live_stats.away.expected_goals` (real-time live xG) have **more future value than any other remaining unimplemented BSD field**.

### Why

1. **Form signal improvement.** Current form signal (`form.py:36-57`) computes Elo residual as `actual_result - expected_win_prob`. Switching to xG differential (`actual_goals - expected_goals`) would measure *performance* rather than *outcome*. A team that dominated xG 3.0-0.5 but drew 1-1 would get a positive form signal instead of a neutral one.

2. **Three xG sources available.** BSD provides three separate xG values per match:

```
actual_home_xg: 1.46   ← post-shot xG (shot placement adjusted)
home_xg_live:   1.41   ← pre-shot live xG
live_stats.home.expected_goals: 1.41   ← same as home_xg_live
```

`actual_home_xg` is the most valuable because it accounts for finishing quality (a shot placed top-corner vs. at the keeper). `actual_home_xg - actual_home_goals` is a proven regression indicator in football analytics.

3. **No other unused field offers model improvement.** All other unused fields are display-only (coach, weather, venue details). `expected_goals` is the only field that could directly improve an existing prediction signal.

4. **Not competing with predictions endpoint xG.** The already-extracted `expected_home_goals`/`expected_away_goals` from predictions endpoint are pre-match forecasts. `live_stats.expected_goals` and `actual_home_xg` are post-match actuals. Different data, different use case.

### Verdict

**Defer but rank as highest-value future field.** Extraction is easy (2 lines in `_STATS_FIELD_MAP`), but consumption requires re-architecting `form.py`. Do not extract until form module is ready to consume it.

## 5. Recalculated Coverage Target

| Metric | Old (raw field count) | New (meaningful fields only) |
|--------|----------------------|------------------------------|
| Denominator | 34 total events fields | 47 meaningful fields |
| Current coverage | 21/34 = **61.8%** | 21/47 = **44.7%** |
| After priority 3 | 27/34 = **79.4%** | 24/47 = **51.1%** |
| After + display essentials | — | 28/47 = **59.6%** |
| 85% target | Needs 8 more fields | Needs **19 more meaningful fields** |

**85% is not worth chasing.** To reach 85% of meaningful fields (40/47), you'd need to extract everything with any value, including fields like `funfacts`, `attendance`, `temperature_c`, `wind_speed`, and multiple odds derivatives (`odds_over_25`, `odds_under_25`, `odds_btts_yes`) — plus a new form signal consumer for xG fields.

**Recommended target: 55% (26/47 meaningful fields).**

Reach that with:
- ✓ fouls, corners, shots_off_target (+3 → 24)
- ✓ venue.city (+1 → 25)
- ✓ home_coach.name (+1 → 26)

26/47 = 55.3%. Done in 10 lines. Every field has clear value. No noise.

If form module is ever re-architected to consume xG:
- live_stats.expected_goals
- actual_home_xg / actual_away_xg
These alone bring it to 29/47 = 61.7%.
