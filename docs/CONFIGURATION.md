<!-- generated-by: gsd-doc-writer -->
# Configuration

This project uses **command-line arguments** and **environment variables** for
configuration. There are no YAML, TOML, or INI configuration files — settings
are provided at invocation time, sourced from the environment, or persisted
via a lightweight JSON file for league preference (see "League ID resolution"
under `wc-predict` below).

---

## Configuration Mechanisms

| Mechanism | Scope | Persistence |
|-----------|-------|-------------|
| CLI arguments | Per-invocation | None — supplied each run |
| Environment variables | Per-session | Optional `.env` file (loaded via `python-dotenv`) |
| File-based config | None | Not used |

### Environment variable loading

The `wc-predict` and `euro-predict` tools call `load_dotenv()` at startup,
which reads a `.env` file from the current working directory. The
`ucl-predict` tool does **not** load `.env` — the `BSD_API_KEY` must be set
in the shell environment or passed via `--api-key`.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BSD_API_KEY` | **Required** for `wc-predict`; **Required** for `ucl-predict` with `--mode live`; optional for `euro-predict` | — | API key for the BSD (Bzzoiro Sports Data) API. Used to fetch live match data, odds, and CatBoost predictions. |
| `POLL_INTERVAL` | Optional | `60` | Polling interval in seconds between API fetch cycles (World Cup predictor only). |

### BSD_API_KEY

The BSD API provides live match events, market odds, and CatBoost
predictions. Each tool handles a missing key differently:

- **`wc-predict`** — Exits immediately with an error if `BSD_API_KEY` is not
  set. Also validates the key by making a test request; exits with an error
  if the API returns HTTP 401.
- **`ucl-predict`** — Requires `BSD_API_KEY` only with `--mode live`.
  With `--validate`, the validation suite runs without the key; only
  BSD-specific validation is skipped (optional). For default
  `--mode simulate`, the key is optional (used only for BSD fixture
  fallback when `--fixture-source auto`).
- **`euro-predict`** — Logs a warning and runs with **Elo-only simulation**
  when the key is missing. No hard failure.

To obtain a key, register at <https://sports.bzzoiro.com/register/>.

**Setting via `.env` file:**

Create a file named `.env` in the project root (or the directory from which
you run the tool) with the following content:

```
BSD_API_KEY=your_api_key_here
```

The `.env` file is listed in `.gitignore` and must never be committed.

**Setting via shell environment (PowerShell):**

```powershell
$env:BSD_API_KEY = "your_api_key_here"
```

**Setting via shell environment (bash):**

```bash
export BSD_API_KEY="your_api_key_here"
```

### POLL_INTERVAL

Controls how frequently the World Cup predictor polls the BSD API for new
matches. Only consumed by `competitions/worldcup/src/constants.py`.

```python
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
```

<!-- VERIFY: Value is environment-dependent — the default 60s is set in source. -->

---

## CLI Reference

All three tools use Python's `argparse` and can be invoked directly with
`python -m competitions.<tool>.main [args]`.

### wc-predict (World Cup)

**Entry point:** `competitions/worldcup/main.py`

**Invocation:**

```bash
python -m competitions.worldcup.main [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--once` | flag | `False` | Run a single fetch → simulate → print cycle, then exit |
| `--no-color` | flag | `False` | Disable ANSI color output (overrides terminal auto-detection) |
| `--seed N` | `int` | `None` | Random seed for reproducible simulation |
| `--ai-preview` | flag | `False` | Display BSD AI prediction previews after simulation output |
| `--match-detail` | `str` / flag | `None` | Display per-match signal breakdown. Use `--match-detail` to show table, or `--match-detail MATCH_ID` to show a focus card for a specific match |
| `--league ID` | `int` | `27` (from `DEFAULT_LEAGUE_ID` constant; `config.json` may override) | BSD league ID (default: 27 for World Cup; see `--list-leagues` for available leagues) |
| `--list-leagues` | flag | `False` | Print all available league IDs and names, then exit |

**League ID resolution order:**
1. `DEFAULT_LEAGUE_ID` constant (`27`) as the starting default
2. `config.json` file (auto-created with `{"league_id": 27}` on first run) — persisted preference
3. CLI `--league` flag — one-off override (not persisted to `config.json`)

**Default behavior:** Runs continuously, polling the BSD API every
`POLL_INTERVAL` seconds and re-simulating after each new match. Press
`Ctrl+C` for a graceful shutdown with final probabilities.

**Required environment variable:** `BSD_API_KEY`

### ucl-predict (UEFA Champions League)

**Entry point:** `competitions/ucl/main.py`

**Invocation:**

```bash
python -m competitions.ucl.main [options]
```

  | Argument | Type | Default | Description |
  |----------|------|---------|-------------|
  | | **Simulation options** | | |
  | `-n N`, `--iterations N` | `int` | `10000` | Number of Monte Carlo iterations |
  | `-s N`, `--seed N` | `int` | `None` | Random seed for reproducible simulation (auto-generated if omitted) |
  | `--use-glicko` | flag | `False` | Enable Bayesian/Glicko-1 uncertainty propagation; samples team strengths from N(μ, σ²) per MC iteration |
  | `-o FILE`, `--output FILE` | `str` | `None` | Write JSON output to FILE (stdout still prints text) |
  | | **Data source options** | | |
  | `--fixture-source {auto,repo,bsd}` | `str` | `auto` | Fixture source: `auto` (try BSD, fallback repo), `repo` (force repo fixtures), `bsd` (force BSD, fail if unavailable) |
  | `--api-key KEY` | `str` | `None` | BSD API key (overrides `BSD_API_KEY` env var) |
  | `--mode {simulate,replay,live}` | `str` | `simulate` | Simulation mode: `simulate` (full synthetic), `replay` (from JSON file), `live` (from BSD API) |
  | `--replay-data FILE` | `str` | `None` | JSON file path with played match results (required for `--mode replay`) |
  | | **Analysis options** | | |
  | `--validate` | flag | `False` | Cross-check predictions against real BSD match results via multi-tier validation suite |
  | `--tier {cross-tournament,walk-forward,replay,all}` | `str` | `all` | Validation tier to run (`all` runs all three tiers) |
  | `--what-if TEAM.PARAM=VALUE` | `str` (append) | `None` | Counterfactual analysis — modify a parameter and re-run simulation. Repeatable. Supported: `elo` (e.g., `Arsenal.elo=1960`) |
  | `--report FILE` | `str` | `None` | Write structured report to FILE (JSON with simulation, signal breakdown, validation, and counterfactual results) |
  | `--calibrate` | flag | `False` | Run weight calibration offline using replay data (requires `--replay-data`) |
  | `--calibrate-temp FILE` | `str` | `None` | Run temperature calibration on replay data and save to `config/calibration.json` |
  | `--validate-calibrated` | flag | `False` | Run validation pipeline with temperature calibration applied; incompatible with `--validate` |
  | | **Signal options** | | |
  | `--weights K=V,K=V` | `str` | `None` | Override blend weights (e.g., `elo=0.4,market=0.3,form=0.2,squad=0.1`); auto-normalized |
  | `--show-breakdown [mode]` | `str` | `None` | Show signal breakdown: `summary` (default, avg weights) or `match` (per-match probabilities) |
  | | **Calibration & Uncertainty options** | | |
  | `--calibrated [mode]` | `str` | `auto` | Control temperature calibration: `on` (force), `off` (skip), `auto` (use config if T != 1.0) |
  | `--show-ci [mode]` | `str` | `auto` | Control confidence interval display: `on`, `off`, `auto` (show when calibration active) |
  | | **Diagnostic options** | | |
  | `--verbose` | flag | `False` | Enable debug-level logging to stderr |

**Default behavior:** Runs a single Monte Carlo simulation with 10,000
iterations, prints formatted output, and optionally exports JSON.

**Mode behavior:**
- **`simulate`** (default) — Full synthetic simulation with no real match results.
  `BSD_API_KEY` is optional; only used for BSD fixture fallback when
  `--fixture-source auto` is set and the BSD API is reachable.
- **`replay`** — Loads played match results from `--replay-data FILE` and uses
  them to constrain the simulation. `--replay-data` is **required**.
- **`live`** — Fetches real match results from the BSD API. `BSD_API_KEY` is
  **required** (or `--api-key`).

**Environment variable:** `BSD_API_KEY` is optional for `simulate` mode,
required for `--mode live` only (the validation suite runs without the key).

### euro-predict (UEFA Euro 2024)

**Entry point:** `competitions/euro/main.py`

**Invocation:**

```bash
python -m competitions.euro.main [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--once` | flag | `False` | Run a single fetch → simulate → print cycle, then exit |
| `--seed N` | `int` | `None` | Random seed for reproducible simulation |

**Default behavior:** Runs continuously, polling the BSD API every 60
seconds and re-simulating after each new match. Press `Ctrl+C` for a
graceful shutdown with final probabilities.

**Environment variable:** `BSD_API_KEY` is optional — the tool runs
Elo-only simulation when the key is missing.

---

## Required vs Optional Settings

The following table summarises which settings cause the application to
behave differently or fail when absent:

| Setting | Tool(s) | Behaviour When Missing |
|---------|---------|-----------------------|
| `BSD_API_KEY` | `wc-predict` | **Hard failure** — exits with code 1 after printing an error message |
| `BSD_API_KEY` | `ucl-predict` (with `--validate`) | **No hard failure** — BSD validation step is optional, suite runs without key |
| `BSD_API_KEY` | `ucl-predict` (with `--mode live`) | **Hard failure** — exits with code 1 |
| `BSD_API_KEY` | `euro-predict` | **Graceful degradation** — runs Elo-only simulation with a warning |
| `--replay-data FILE` | `ucl-predict` (with `--mode replay`) | **Hard failure** — exits with code 1 if missing |
| `POLL_INTERVAL` | `wc-predict` | **Uses default** — 60 seconds |

---

## Defaults (Source-Code Values)

Settings with defaults are resolved in the source code itself. No external
defaults file is used.

| Variable | Default Value | Set In |
|----------|---------------|--------|
| `API_TIMEOUT` | `10` (seconds) | `football_core/constants.py` line 11 |
| `POLL_INTERVAL` | `60` | `competitions/worldcup/src/constants.py` line 53 |
| `--seed` (wc-predict) | `None` | `competitions/worldcup/main.py` line 275 |
| `--seed` (euro-predict) | `None` | `competitions/euro/main.py` line 36 |
| `--iterations` (ucl-predict) | `10000` | `competitions/ucl/main.py` line 215 |
| `--league` (wc-predict) | `27` (from `DEFAULT_LEAGUE_ID`) | `competitions/worldcup/src/constants.py` line 28 |
| `--no-color` (wc-predict) | `False` | `competitions/worldcup/main.py` line 267 |
| `--once` (wc-predict) | `False` | `competitions/worldcup/main.py` line 260 |
| `--once` (euro-predict) | `False` | `competitions/euro/main.py` line 34 |
| `--ai-preview` (wc-predict) | `False` | `competitions/worldcup/main.py` line 279 |
| `--validate` (ucl-predict) | `False` | `competitions/ucl/main.py` line 258 |
| `--fixture-source` (ucl-predict) | `auto` | `competitions/ucl/main.py` line 236 |
| `--mode` (ucl-predict) | `simulate` | `competitions/ucl/main.py` line 246 |
| `--use-glicko` (ucl-predict) | `False` | `competitions/ucl/main.py` line 223 |
| `--tier` (ucl-predict) | `all` | `competitions/ucl/main.py` line 265 |
| `--calibrate` (ucl-predict) | `False` | `competitions/ucl/main.py` line 283 |
| `--calibrated` (ucl-predict) | `auto` | `competitions/ucl/main.py` line 322 |
| `--show-ci` (ucl-predict) | `auto` | `competitions/ucl/main.py` line 330 |
| `--verbose` (ucl-predict) | `False` | `competitions/ucl/main.py` line 339 |
| `--validate-calibrated` (ucl-predict) | `False` | `competitions/ucl/main.py` line 294 |

---

## Per-Environment Overrides

The project does **not** use environment-specific config files
(`.env.development`, `.env.production`, etc.). All configuration is
supplied at invocation time.

**Production vs development** is determined by which CLI arguments and
environment variables you supply:

- **Development / exploration:** Use `--once` with a fixed `--seed` for
  reproducible, single-run simulations.
- **Live production:** Run without `--once` to enable continuous polling;
  ensure `BSD_API_KEY` is set.
- **CI / testing:** Set `BSD_API_KEY` to a valid test key; use `--seed` for
  deterministic output.
