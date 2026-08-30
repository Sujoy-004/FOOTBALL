// ═══ UEFA Champions League Module ═══
import {
  destroyModalCharts, modalCharts,
  updateStatusBar, competitions, showSimPopup,
  buildTable, safeJson, renderBracketTree, renderAcquisitionPanel,
  openIntelModal, renderLoading, currentCompetition,
} from "./shared.js";

const API = "/ucl/api";
const appState = { data: null, standings: [], bracket: null, odds: [], signals: {}, simProjections: null, simMeta: null, simRunCount: 0, simBracket: null, simChampion: null, seasons: [], activeSeason: null };

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const sigLabels = {
  refined_elo: "Refined Elo", market_odds: "Market Odds", rolling_form: "Rolling Form",
  squad_value: "Squad Value", rest_days: "Rest Days",
};
const sigOrder = ["refined_elo", "rolling_form", "market_odds", "squad_value", "rest_days"];

export function init(comp) {
  loadAll({ label: "Loading UCL…" });
}

// ── Data loading (atomic, race-guarded transitions) ──────────────────
//
// Every season/competition transition runs through loadAll. Correctness
// properties, all enforced here:
//   1. ATOMIC   - appState is mutated only after EVERY fetch resolves, so no
//                 tab can show previous-season content under the new header.
//                 The three data tabs display a loader for the real fetch
//                 duration (no artificial delay).
//   2. ROLLBACK - on any failure the last fully-valid rendered state is
//                 restored. Because appState is committed all-at-once at the
//                 very end, the failed path leaves it untouched; re-rendering
//                 it restores the prior view verbatim, including the season
//                 <select> value (rebuilt from appState.seasons).
//   3. RACE GUARD - a monotonically increasing generation token is captured
//                 at request start and compared on every response boundary.
//                 Only the newest transition may commit or render; late
//                 responses from superseded (A->B->A) switches are discarded.
//                 The token check is paired with an "is UCL still the active
//                 competition" check so a late UCL response never renders into
//                 another competition's reused tab elements.

let _transitionGen = 0;

// True only while the UCL competition owns the shared tab-* elements. Uses the
// live `currentCompetition` binding exported by shared.js (set before init()).
function _isUclActive() {
  return !!(currentCompetition && currentCompetition.apiPrefix === API);
}

// A transition is stale if a newer one has started OR the user has navigated
// away from UCL. Stale transitions must neither mutate appState nor render.
function _stale(gen) {
  return gen !== _transitionGen || !_isUclActive();
}

// Show the shared loader in every tab that renders from appState, so there is
// no window where one tab shows stale data under the new selection.
function _showTransitionLoading(label) {
  ["tab-overview", "tab-standings", "tab-bracket"].forEach(function(id) {
    const el = document.getElementById(id);
    if (el && typeof renderLoading === "function") renderLoading(el, label);
  });
}

// Surface a transition failure without leaving a blank/half-rendered view.
// The valid previous view has already been re-rendered; this prepends a
// non-blocking notice above it. textContent -> no injection risk.
function _surfaceTransitionError(e, o) {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const what = (o && o.season) ? ("Could not switch to " + o.season)
    : "Could not refresh UCL data";
  const banner = document.createElement("div");
  banner.className = "stat-card";
  banner.style.cssText = "color:#ff6b6b;margin-bottom:8px";
  banner.textContent = what + " — "
    + (e && e.message ? e.message : "unknown error") + ". Showing last valid data.";
  tab.insertBefore(banner, tab.firstChild);
}

async function loadAll(opts) {
  const o = opts || {};
  const gen = ++_transitionGen;
  // Snapshot for rollback (shallow is enough: appState is never partially
  // mutated on the failure path, so the previous field values remain intact).
  const prev = Object.assign({}, appState);
  const label = o.label || (o.season ? "Loading " + o.season + "…" : "Loading…");

  _showTransitionLoading(label);

  try {
    // A season switch is part of the atomic unit: flip the backend active
    // season first, then load. If anything downstream fails we roll the UI
    // back to the previous season's still-intact state.
    if (o.season != null) {
      await safeJson(API + "/season", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ season: o.season }),
      });
      if (_stale(gen)) return;
    }

    const [d, s, br, ob, sig, ss] = await Promise.all([
      safeJson(API + "/data"),
      safeJson(API + "/standings"),
      safeJson(API + "/bracket"),
      safeJson(API + "/odds"),
      safeJson(API + "/signals"),
      safeJson(API + "/seasons"),
    ]);

    // Race guard: discard entirely if a newer transition started (or we left
    // UCL) while these requests were in flight. No mutation, no render.
    if (_stale(gen)) return;

    // Session persistence: a run completed against this server process must
    // survive reloads/navigation. On a season switch the prior season's sim
    // never carries over, so treat it as "none present" and re-hydrate the
    // target season's completed run if the backend reports one.
    const hadSim = o.season != null
      ? false
      : !!(prev.simProjections && prev.simProjections.length);
    let simPayload = null;
    if (d.simulation && d.simulation.request_state === "completed" && !hadSim) {
      try { simPayload = await safeJson(API + "/simulation"); }
      catch (e) { console.error("simulation hydration failed:", e); }
      if (_stale(gen)) return;
    }

    // ── Commit: single all-or-nothing mutation of shared state ──
    appState.data = d;
    appState.standings = s.standings || [];
    appState.bracket = br;
    appState.odds = ob.odds || [];
    appState.signals = sig.signals || {};
    appState.seasons = ss.seasons || [];
    appState.activeSeason = ss.active_season || d.season || null;
    if (o.season != null) {
      // New season: the previous season's projections are meaningless here.
      appState.simProjections = null;
      appState.simBracket = null;
      appState.simChampion = null;
      appState.simMeta = null;
      appState.simRunCount = 0;
    }
    if (simPayload) {
      try { _applySimulationPayload(simPayload, 0); }
      catch (e) { console.error("simulation apply failed:", e); }
    }
  } catch (e) {
    // Superseded / navigated-away transitions own nothing: stay silent.
    if (_stale(gen)) return;
    console.error("loadAll transition failed:", e);
    if (!appState.data) {
      // First load never succeeded: there is no valid state to roll back to.
      // Show an explicit error instead of a permanent loader (non-blank).
      const tab = document.getElementById("tab-overview");
      if (tab) tab.innerHTML = '<div class="stat-card" style="color:#ff6b6b">Failed to load UCL data: '
        + _esc(e.message) + '</div>';
      renderStandings();
      renderBracket();
      return;
    }
    // Roll back to the last fully-valid rendered state (appState is intact).
    renderOverview();
    renderStandings();
    renderBracket();
    updateStatus();
    _surfaceTransitionError(e, o);
    return;
  }

  renderOverview();
  renderStandings();
  renderBracket();
  updateStatus();
}

async function reloadData() {
  try {
    const [d, s, br, o, sig, ss] = await Promise.all([
      safeJson(API + "/data"),
      safeJson(API + "/standings"),
      safeJson(API + "/bracket"),
      safeJson(API + "/odds"),
      safeJson(API + "/signals"),
      safeJson(API + "/seasons"),
    ]);
    appState.data = d;
    appState.standings = s.standings || [];
    appState.bracket = br;
    appState.odds = o.odds || [];
    appState.signals = sig.signals || {};
    appState.seasons = ss.seasons || [];
    appState.activeSeason = ss.active_season || d.season || null;
  } catch (e) {
    console.error("reloadData failed:", e);
  }
  renderOverview(); renderStandings(); renderBracket(); updateStatus();
}

function updateStatus() {
  const d = appState.data;
  if (!d) return;
  const refresh = d.refresh || {};
  let notice = "";
  if (refresh.skipped_reason) {
    notice = '<span style="color:#e6a817">SNAPSHOT - showing stored data (live refresh skipped)</span>';
  } else if (refresh.stale) {
    notice = '<span style="color:#e6a817">STALE - live refresh failed; showing last known data</span>';
  }
  updateStatusBar(
    d.n_teams + " teams  |  " + (d.n_played || 0) + " matches played",
    notice
  );
}

// ── Overview ─────────────────────────────────────────────────────────

// Render the completed-run projections block: meta line + aggregate label
// + top-5 table. Shared by the live and completed-season overview paths so
// both carry the same Monte Carlo-aggregate wording.
function _uclProjectionBlock() {
  const m = appState.simMeta || {};
  const runs = appState.simRunCount || 0;
  let h = '<div class="dim" style="padding:2px 8px;font-size:11px;color:#8E44AD">'
    + 'SIMULATION &middot; ' + runs.toLocaleString()
    + ' RUNS' + (m.seed != null ? ' &middot; seed ' + m.seed : '')
    + ' - projected probabilities, not real results.</div>';
  h += '<div class="dim" style="padding:2px 8px;font-size:11px">'
    + 'Projected champion probability - Monte Carlo aggregate over '
    + runs.toLocaleString() + ' runs</div>';
  h += '<table class="eval-table"><tr><th>#</th><th>Team</th><th>Champion %</th></tr>';
  appState.simProjections.slice(0, 5).forEach(function(o, i) {
    const pct = ((o.champion_prob || 0) * 100).toFixed(1);
    h += '<tr><td class="num">' + (i + 1) + '</td><td>' + o.team
      + '</td><td class="num">' + pct + '%</td></tr>';
  });
  h += '</table>';
  return h;
}

async function renderOverview() {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const d = appState.data;
  if (!d) { tab.innerHTML = '<div class="dim">Loading...</div>'; return; }

  const standings = appState.standings || [];
  const signals = appState.signals || {};
  const sigKeys = Object.keys(signals);
  const nActive = sigOrder.filter(function(sk) { return signals[sk] !== undefined; }).length;
  // Authoritative competition phase from the backend (never inferred here).
  const phase = d.phase || {};
  const stage = phase.label || "Unknown";
  const simState = d.simulation || {};
  const availability = simState.availability || "available";
  const requestState = simState.request_state || "not_requested";

  // Stat cards: Teams / Matches Played / Stage  (WC-style hierarchy)
  let html = '<div class="chart-section" style="padding:6px 8px;margin-bottom:8px">'
    + '<div class="title" style="display:inline-block;margin-right:10px">Season</div>'
    + '<select id="uclSeasonSelect" style="background:#0d2430;color:#F6DBC0;border:1px solid rgba(21,61,76,.5);border-radius:4px;padding:4px 8px;font-size:11px">';
  (appState.seasons || []).forEach(function(s) {
    html += '<option value="' + _esc(s.season) + '"' + (s.active ? ' selected' : '') + '>' + _esc(s.season) + (s.historical ? ' (historical)' : '') + '</option>';
  });
  html += '</select></div>';

  let htmlStats = '<div class="stats-row">';
  htmlStats += '<div class="stat-card"><div class="val">' + (d.n_teams || 0) + '</div><div class="lbl">Teams</div></div>';
  htmlStats += '<div class="stat-card"><div class="val">' + (d.n_played || 0) + '</div><div class="lbl">Matches Played</div></div>';
  htmlStats += '<div class="stat-card"><div class="val" style="font-size:.75em">' + stage + '</div><div class="lbl">Stage</div></div>';
  htmlStats += '<div class="stat-card"><div class="val">' + nActive + ' / ' + sigOrder.length + '</div><div class="lbl">Signals Available</div></div>';
  if (d.snapshot_date) htmlStats += '<div class="stat-card"><div class="val" style="font-size:.8em">' + d.snapshot_date + '</div><div class="lbl">Season</div></div>';
  if (availability !== "not_needed" && d.n_played != null && d.n_unplayed != null) {
    htmlStats += '<div class="stat-card"><div class="val">' + d.n_played + '</div><div class="lbl">REAL MATCHES</div></div>';
    htmlStats += '<div class="stat-card"><div class="val">' + d.n_unplayed + '</div><div class="lbl">UPCOMING</div></div>';
  }
  htmlStats += '</div>';
  html += htmlStats + '\n';

  // Current leaders (compact top-8 preview)
  if (standings.length >= 4) {
    html += '<div class="chart-section"><div class="title">Current Leaders - Top 8</div>';
    html += '<table class="eval-table"><tr><th>#</th><th>Team</th><th>Pts</th><th>GD</th></tr>';
    standings.slice(0, 8).forEach(function(r) {
      const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
      html += '<tr><td class="num">' + r.position + '</td><td>' + r.team + '</td>'
        + '<td class="num">' + (r.pts !== undefined ? r.pts : '-') + '</td>'
        + '<td class="num">' + gd + '</td></tr>';
    });
    html += '</table></div>';
  }

  // Signal availability (WC-style status table)
  html += '<div class="chart-section"><div class="title">Signal Availability</div>';
  if (sigKeys.length > 0) {
    html += '<table class="eval-table"><tr><th>Signal</th><th>Status</th></tr>';
    sigOrder.forEach(function(sk) {
      const s = signals[sk];
      const available = s !== undefined;
      html += '<tr><td>' + (sigLabels[sk] || sk) + '</td><td>'
        + '<span class="' + (available ? 'dot-green' : 'dot-red') + '">&#9679;</span> '
        + (available ? 'Yes' : 'No') + '</td></tr>';
    });
    html += '</table>';
  } else {
    html += '<div class="dim">No signal data available.</div>';
  }
  html += '</div>';

  // ── Simulation section (Exchange 4 shared product contract) ──────
  // Driven by the backend's availability/request-state block; the UI never
  // infers eligibility and never fabricates outcomes for undecided stages.
  html += '<div class="chart-section"><div class="title">Simulation</div>';

  if (availability === "not_needed") {
    if (requestState === "completed" && appState.simProjections
        && appState.simProjections.length) {
      html += _uclProjectionBlock();
    }
    html += '<div class="dim" style="padding:4px 8px;font-size:12px">'
      + 'Season completed - results are factual. Per-match What-If '
      + 'available via bracket.</div>';
  } else if (requestState === "running") {
    html += '<div class="dim" style="padding:4px 8px;font-size:12px">'
      + 'A simulation is currently running. Reload in a moment to see its '
      + 'projections.</div>';
  } else {
    if (requestState === "completed" && appState.simProjections
        && appState.simProjections.length) {
      html += _uclProjectionBlock();
    } else if (requestState === "failed") {
      html += '<div class="dim" style="padding:4px 8px;font-size:12px;color:#ff6b6b">'
        + 'The last simulation failed. No projected probabilities exist.</div>';
    } else {
      html += '<div class="dim" style="padding:2px 8px;font-size:11px">'
        + 'No simulation has been run in this session, so no projected '
        + 'probabilities exist.</div>';
    }

    html += '<div class="dim" style="padding:2px 8px;font-size:11px">'
      + 'Current season: ' + (d.n_played || 0) + ' matches played, '
      + (d.n_unplayed != null ? d.n_unplayed : "?") + ' remaining</div>';

    // Control card: user chooses whether/how to simulate.
    html += '<div style="padding:6px 8px">';
    html += '<div style="margin-bottom:4px;font-size:11px;color:#15565B">Runs:'
      + '</div>'
      + '<button class="status-btn sim-preset" data-runs="1000">1K</button> '
      + '<button class="status-btn sim-preset active" data-runs="5000">5K</button> '
      + '<button class="status-btn sim-preset" data-runs="10000">10K</button> '
      + '<button class="status-btn sim-preset" data-runs="100000">100K</button> '
      + '<input type="number" id="uclSimCustom" placeholder="custom" min="1"'
      + ' max="1000000" style="width:90px;background:#0d2430;color:#F6DBC0;'
      + 'border:1px solid rgba(21,61,76,.4);border-radius:4px;padding:4px 6px;'
      + 'font-size:11px"> '
      + '<input type="number" id="uclSimSeed" placeholder="seed (auto)"'
      + ' style="width:110px;background:#0d2430;color:#F6DBC0;border:1px solid '
      + 'rgba(21,61,76,.4);border-radius:4px;padding:4px 6px;font-size:11px"> ';
    html += '<div style="margin-top:6px">'
      + '<button class="status-btn" id="uclSimStartBtn">&#9654; Run Simulation</button>'
      + '<span id="uclSimProgressLbl" class="dim" style="margin-left:8px;font-size:11px"></span></div>';
    html += '</div>';
  }
  html += '</div>';

  // ── Data acquisition status (truthful snapshot/live/stale report) ──
  html += '<div class="chart-section"><div class="title">Data Acquisition</div>';
  html += '<div id="uclAcqPanel"></div>';
  html += '</div>';

  tab.innerHTML = html;
  bindSimulationControls();
  const seasonSelect = document.getElementById("uclSeasonSelect");
  if (seasonSelect) seasonSelect.addEventListener("change", function() {
    // Delegate the whole switch to the atomic transition: the /season POST,
    // every data fetch, the sim-state reset and the render all run under one
    // generation token. A failed switch rolls the UI back to the previous
    // season (this <select> included, since it is rebuilt from appState) and
    // surfaces the error — never a blank or mislabeled view.
    loadAll({ season: seasonSelect.value });
  });
  renderAcquisitionPanel(document.getElementById("uclAcqPanel"), _buildAcquisition(d));
}

// Build the truthful acquisition object from /api/data (+ phase stores).
function _buildAcquisition(d) {
  const refresh = d.refresh || {};
  const phase = d.phase || {};
  const stores = phase.stores || {};
  const availability = d.availability || {};
  const attempted = refresh.attempted === true;
  const succeeded = refresh.success === true;
  const snapshotMode = !!refresh.skipped_reason;

  let mode, source, error = null, stale = false;
  if (snapshotMode) {
    mode = "snapshot";
    source = "Snapshot";
  } else {
    mode = "live";
    if (attempted && !succeeded) {
      // Fresh acquisition failed: rendering fell back to the last valid
      // snapshot. Say so explicitly instead of masquerading as LIVE.
      stale = true;
      error = refresh.error || "live refresh failed";
      source = "FALLBACK";
    } else {
      source = refresh.provider || "LIVE";
    }
  }

  // DataAvailability store value -> checklist state ('ok' only when the
  // backend reports the store as available; everything else is unavailable).
  const storeState = function(v) { return v === "available" ? "ok" : "unavailable"; };
  const koStore = stores.knockout_results || availability.knockout_results;

  const stages = [
    {
      key: "teams", label: "Teams",
      state: d.n_teams ? "ok" : "unavailable",
      count: d.n_teams != null ? d.n_teams : null,
    },
    {
      key: "league", label: "League results",
      state: (!attempted || succeeded) ? "ok" : "error",
      count: d.n_played != null ? d.n_played : null,
      detail: (attempted && !succeeded) ? (refresh.error || "refresh failed") : undefined,
    },
    {
      key: "playoff", label: "Knockout Playoffs",
      state: storeState(stores.playoff || koStore),
      count: null,
    },
    {
      key: "knockout", label: "Knockout results",
      state: storeState(koStore),
      count: null,
    },
    {
      key: "champion", label: "Champion",
      state: phase.champion ? "ok" : (koStore === "available" ? "pending" : "unavailable"),
      count: null,
    },
  ];

  return {
    competition: "UCL " + (d.lifecycle && d.lifecycle.season ? d.lifecycle.season : (d.season || "")),
    mode,
    source,
    updatedAt: refresh.last_refresh || null,
    error,
    stale,
    stages,
  };
}

// ── Simulation controls (shared product contract) ────────────────────

let _uclSimPolling = false;

function _selectedRuns() {
  const custom = document.getElementById("uclSimCustom");
  const customVal = custom && custom.value.trim() !== "" ? parseInt(custom.value) : NaN;
  if (Number.isFinite(customVal)) return customVal;
  const active = document.querySelector(".sim-preset.active");
  return active ? parseInt(active.dataset.runs) : 5000;
}

function bindSimulationControls() {
  document.querySelectorAll(".sim-preset").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll(".sim-preset").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      const custom = document.getElementById("uclSimCustom");
      if (custom) custom.value = "";
    });
  });
  const startBtn = document.getElementById("uclSimStartBtn");
  if (startBtn) startBtn.addEventListener("click", startUclSimulation);
}

function _applySimulationPayload(sim, fallbackRuns) {
  appState.simProjections = (sim.odds || []).slice()
    .sort(function(a, b) { return (b.champion_prob || 0) - (a.champion_prob || 0); });
  appState.simMeta = sim.simulation_meta || {};
  appState.simRunCount = (sim.simulation_meta && sim.simulation_meta.count) || fallbackRuns || 0;
  // Canonical bracket-shaped projection payload (stages keyed like /api/bracket).
  appState.simBracket = sim.bracket || null;
  appState.simChampion = sim.champion || null;
}

async function startUclSimulation() {
  if (_uclSimPolling) return;
  const runs = _selectedRuns();
  const seedInput = document.getElementById("uclSimSeed");
  const seedRaw = seedInput && seedInput.value.trim() !== "" ? parseInt(seedInput.value) : null;
  const lbl = document.getElementById("uclSimProgressLbl");
  const startBtn = document.getElementById("uclSimStartBtn");
  if (!Number.isFinite(runs) || runs < 1 || runs > 1000000) {
    if (lbl) lbl.textContent = "Runs must be between 1 and 1,000,000.";
    return;
  }
  _uclSimPolling = true;
  if (startBtn) startBtn.disabled = true;
  if (lbl) lbl.textContent = "Starting...";
  try {
    const body = seedRaw != null ? { iterations: runs, seed: seedRaw } : { iterations: runs };
    const resp = await safeJson(API + "/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.task_id) {
      // not_needed / validation_error: honest reason, no fake numbers.
      if (lbl) lbl.textContent = resp.message || resp.error || resp.status;
      return;
    }
    const t0 = Date.now();
    await new Promise(function(resolve, reject) {
      const poll = setInterval(async function() {
        try {
          const pr = await safeJson(API + "/simulation/progress/" + resp.task_id);
          if (pr.status === "not_found") { clearInterval(poll); reject(new Error(pr.error)); return; }
          if (pr.status === "completed") { clearInterval(poll); resolve(); return; }
          if (pr.status === "failed") { clearInterval(poll); reject(new Error(pr.error || "simulation failed")); return; }
          if (lbl) {
            let text = (pr.stage || "Simulating...");
            if (pr.total_iterations > 0) text += "  " + (pr.iteration || 0).toLocaleString() + "/" + pr.total_iterations.toLocaleString();
            text += "  (" + Math.round(pr.progress || 0) + "%)";
            const elapsedS = Math.round((Date.now() - t0) / 1000);
            if (elapsedS > 0) text += "  " + elapsedS + "s";
            lbl.textContent = text;
          }
        } catch (e) { clearInterval(poll); reject(e); }
      }, 250);
    });
    const sim = await safeJson(API + "/simulation");
    _applySimulationPayload(sim, runs);
    // The overview gate reads request_state from appState.data, which was
    // fetched before this run existed. Refetch so the just-completed run is
    // visible instead of being masked by the stale boot-time state.
    appState.data = await safeJson(API + "/data");
    renderOverview();
    renderBracket();
  } catch (e) {
    if (lbl) lbl.textContent = "Error: " + (e.message || "unknown");
  } finally {
    _uclSimPolling = false;
    const btn2 = document.getElementById("uclSimStartBtn");
    if (btn2) btn2.disabled = false;
  }
}

// ── Standings ────────────────────────────────────────────────────────

async function renderStandings() {
  const tab = document.getElementById("tab-standings");
  if (!tab) return;
  const st = appState.standings || [];
  if (!st.length) { tab.innerHTML = '<div style="color:#15565B;font-size:12px">No standings data.</div>'; return; }
  let html = '<div class="league-table-wrap"><table class="league-table">'
    + '<tr><th>Pos</th><th>Team</th><th>Pld</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Zone</th></tr>';
  st.forEach(function(r) {
    const zone = r.zone || "eliminated";
    const cls = zone === "top_8" ? "zone-top8" : zone === "playoff" ? "zone-playoff" : "";
    const zoneLabel = zone === "top_8" ? "TOP 8" : zone === "playoff" ? "PLAYOFF" : "OUT";
    const zoneCls = zone === "top_8" ? "top8" : zone === "playoff" ? "playoff" : "eliminated";
    const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
    const pld = (r.wins || 0) + (r.draws || 0) + (r.losses || 0);
    html += '<tr class="' + cls + '"><td class="num">' + r.position + '</td><td>' + r.team
      + '</td><td class="num">' + pld + '</td><td class="num">' + (r.wins || 0)
      + '</td><td class="num">' + (r.draws || 0) + '</td><td class="num">' + (r.losses || 0)
      + '</td><td class="num">' + (r.gs || 0) + '</td><td class="num">' + (r.ga || 0)
      + '</td><td class="num">' + gd + '</td><td class="num">'
      + (r.pts !== undefined && r.pts !== null ? r.pts : "?")
      + '</td><td><span class="zone-badge ' + zoneCls + '">' + zoneLabel + '</span></td></tr>';
  });
  html += '</table></div>';
  tab.innerHTML = html;
}

// ── Bracket / Competition Explorer ───────────────────────────────────

async function renderBracket() {
  const tab = document.getElementById("tab-bracket");
  if (!tab) return;
  const br = appState.bracket;
  if (!br) { tab.innerHTML = "<p>No bracket data.</p>"; return; }

  const stages = br.stages || {};
  const lmd = (stages.league && stages.league.matchdays) || br.league_matchdays || {};
  const lmdKeys = Object.keys(lmd).sort();

  let html = "";

  // Champion banner: only for a real champion on file in results mode.
  const availability = br.availability || (appState.data && appState.data.availability) || {};
  if (br.mode === "results" && br.champion && availability.knockout_results === "available") {
    html += '<div class="champ-banner">Champion: ' + _esc(br.champion) + "</div>";
  }

  // ── Section 1: League Phase (interactive matchday accordion) ──
  if (lmdKeys.length) {
    html += '<div class="chart-section"><div class="title">League Phase</div><div class="md-accordion">';
    const firstMid = lmdKeys[0];
    let mdHtml = "";
    lmdKeys.forEach(function(md, mdi) {
      const ms = lmd[md] || [];
      const isFirst = mdi === 0;
      mdHtml += '<div class="md-card"><div class="md-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">';
      mdHtml += '<span class="md-label">' + md.replace(/^MD/, "Matchday ") + '</span>';
      mdHtml += '<span class="md-count">' + ms.length + " matches</span>";
      mdHtml += '<span class="md-arrow">' + (isFirst ? "-" : "+") + "</span></div>";
      mdHtml += '<div class="md-body' + (isFirst ? " open" : "") + '">';
      ms.forEach(function(m) {
        const hs = m.home_score !== undefined && m.home_score !== null ? m.home_score : "-";
        const as_ = m.away_score !== undefined && m.away_score !== null ? m.away_score : "-";
        // Backend supplies explicit status on league rows (Exchange 2);
        // score presence remains the fallback for older payloads.
        const played = m.status ? m.status === "played" : (hs !== "-" && as_ !== "-");
        const statusDot = played
          ? '<span class="dot-green">\u25CF</span>'
          : '<span class="dot-orange">\u25CF</span>';
        const scoreStr = played ? hs + " - " + as_ : "vs";
        mdHtml += '<div class="md-row match-clickable"'
          + ' data-match-id="' + m.match_id + '"'
          + ' data-team-a="' + m.team_a + '"'
          + ' data-team-b="' + m.team_b + '"'
          + ' style="cursor:pointer;transition:background .15s;display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid rgba(21,61,76,.15)"'
          + ' onmouseover="this.style.background=\'rgba(22,160,133,0.1\)\'"'
          + ' onmouseout="this.style.background=\'\'">'
          + '<span class="md-team" style="flex:1;text-align:right">' + m.team_a + '</span>'
          + '<span class="md-score" style="margin:0 12px;font-weight:bold;min-width:40px;text-align:center">' + scoreStr + '</span>'
          + '<span class="md-team" style="flex:1">' + m.team_b + '</span>'
          + '<span style="font-size:10px;margin-left:8px">' + statusDot + '</span>'
          + '</div>';
      });
      mdHtml += '</div></div>';
    });
    html += mdHtml + '</div></div>';
  }

  // ── Section 2: Knockout (shared bracket renderer) ──
  html += '<div class="chart-section"><div class="title">Knockout Stage</div>';
  html += '<div id="uclKoHost"></div>';
  html += "</div>";

  tab.innerHTML = html;
  bindMatchClicks(tab);
  _renderUclKo();
}

function _renderUclKo() {
  const host = document.getElementById("uclKoHost");
  if (!host) return;
  const br = appState.bracket || {};
  const stages = br.stages || {};
  const d = appState.data || {};

  // Simulation projection payload shares the canonical stages shape under
  // sim.bracket; merge by match id below (REAL DATA ALWAYS WINS).
  const simActive = !!(d.simulation && d.simulation.request_state === "completed"
    && appState.simBracket && appState.simBracket.stages);
  const simStages = simActive ? appState.simBracket.stages : {};
  const metaM = appState.simMeta || {};

  const simById = {};
  Object.keys(simStages).forEach(function(k) {
    ((simStages[k] || {}).matches || []).forEach(function(t) {
      if (t && t.id) simById[t.id] = t;
    });
  });

  let sawSim = false;
  const order = br.stage_order || ["league", "playoff", "R16", "QF", "SF", "FINAL"];
  const outStages = order
    .filter(function(k) { return k !== "league" && stages[k]; })
    .map(function(key) {
      const src = stages[key];
      const realMatches = Array.isArray(src.matches) ? src.matches : [];
      const merged = [];
      const presentIds = {};
      realMatches.forEach(function(t) {
        const tid = t ? (t.id || t.match_id) : null;
        if (!tid) return;
        presentIds[tid] = true;
        const m = _tieToMatch(t, src.label);
        if (!_isFactual(t) && simById[tid]) {
          merged.push(_withSimOverlay(m, simById[tid]));
          sawSim = true;
        } else {
          merged.push(m);
        }
      });
      // Simulation-only ties for slots the real payload does not define.
      ((simStages[key] || {}).matches || []).forEach(function(sm) {
        if (sm && sm.id && !presentIds[sm.id]) {
          merged.push(_tieToMatch(sm, src.label));
          sawSim = true;
        }
      });
      return {
        id: key,
        label: src.label || key,
        layout: src.layout || (key === "playoff" ? "list" : "tree"),
        matches: merged,
      };
    });

  const totalCards = outStages.reduce(function(n, s) { return n + s.matches.length; }, 0);

  let pre = "";

  // Simulation provenance note + projected champion: shown whenever a
  // completed run exists in this session (alternate-history analysis),
  // even when every knockout slot is already factual and no SIM card is
  // overlaid. Real facts always take precedence in the tree itself.
  if (simActive) {
    pre += '<div style="margin:12px 0 4px;padding:4px 8px;font-size:11px;color:#8E44AD">'
      + "SIMULATION &middot; projected knockout path"
      + (sawSim ? " &middot; example simulated bracket (one sampled run)" : "")
      + (appState.simRunCount ? " &middot; " + appState.simRunCount.toLocaleString() + " runs" : "")
      + (metaM.seed != null ? " &middot; seed " + metaM.seed : "")
      + " &middot; not real results</div>";
    if (appState.simChampion) {
      pre += '<div class="champ-banner champ-banner-sim">Projected champion: '
        + _esc(appState.simChampion) + " (SIMULATED)</div>";
    }
  }

  // Truth model: absence of knockout data in the snapshot is NOT proof the
  // stage was never played. Only a genuinely unreadable store may speak
  // about readability; otherwise report plain unavailability.
  if (!totalCards) {
    const koStore = (d.phase && d.phase.stores && d.phase.stores.knockout_results) || "missing";
    pre += '<div class="dim" style="padding:8px;font-size:11px">'
      + (koStore === "unavailable"
        ? "Knockout data exists but could not be read."
        : "Knockout results unavailable in current snapshot.")
      + "</div>";
  }

  // Playoff fallback: when no tie cards exist for that stage, surface the
  // data-derived qualification view (positions 9-24 from final standings).
  const playoffStage = outStages.filter(function(s) { return s.id === "playoff"; })[0];
  if (playoffStage && !playoffStage.matches.length) {
    const st = appState.standings || [];
    const qual = st.filter(function(r) { return r.zone === "playoff"; });
    if (qual.length) {
      pre += '<div class="dim" style="padding:4px 8px;font-size:11px;color:#15565B">'
        + "Playoff results unavailable in current snapshot. Qualified teams (positions 9-24):</div>";
      pre += '<div style="display:flex;flex-wrap:wrap;gap:6px;padding:8px">';
      qual.forEach(function(r) {
        pre += '<span class="zone-badge playoff">' + r.position + ". " + _esc(r.team) + "</span>";
      });
      pre += "</div>";
    } else {
      pre += '<div class="dim" style="padding:8px;color:#15565B;font-size:11px">Playoff results unavailable in current snapshot.</div>';
    }
  }

  host.innerHTML = pre + '<div id="uclKoTree"></div>';
  if (totalCards) {
    renderBracketTree(document.getElementById("uclKoTree"), { stages: outStages }, {
      cardThemeClass: "",
      simLabel: "SIM",
      onMatch: function(m) { openTiePopup(m); },
    });
  }
}

// A real tie is factual once decided; only then does the simulation overlay
// stay off (REAL DATA ALWAYS WINS).
function _isFactual(t) {
  return t.status === "played" || !!t.winner;
}

// Map a canonical TIE onto the shared renderer's match shape. True leg order
// is preserved: no winner-first reordering anywhere.
function _tieToMatch(t, stageLabel) {
  const legs = Array.isArray(t.legs) ? t.legs : [];
  const played = t.status === "played" || !!t.winner;
  const hasAgg = t.aggregate_a != null && t.aggregate_b != null;
  const teamsKnown = !!(t.team_a && t.team_b);
  const detailParts = [];
  let resultLine = null;

  const appendOutcomeNotes = function() {
    if (t.et_played) detailParts.push("(ET)");
    if (t.penalties_played) {
      if (t.penalty_a != null && t.penalty_b != null) detailParts.push("PENS " + t.penalty_a + "-" + t.penalty_b);
      else if (t.penalty_score) detailParts.push("PENS " + t.penalty_score);
    }
    if (t.winner) detailParts.push("WINNER " + t.winner);
  };

  if (!legs.length && t.score && t.score.home != null) {
    // Final-style single match.
    resultLine = t.score.home + "-" + t.score.away;
    appendOutcomeNotes();
  } else if (legs.length >= 2) {
    resultLine = hasAgg ? ("AGG " + t.aggregate_a + "-" + t.aggregate_b) : null;
    legs.forEach(function(l) {
      detailParts.push("LEG " + (l.leg != null ? l.leg : "?")
        + "  " + (l.home || "?") + " "
        + (l.home_score != null ? l.home_score : "-") + "-"
        + (l.away_score != null ? l.away_score : "-") + " "
        + (l.away || "?"));
    });
    if (hasAgg) {
      let aggLine = "AGGREGATE " + (t.team_a || "?") + " " + t.aggregate_a + "-" + t.aggregate_b + " " + (t.team_b || "?");
      if (t.et_played) aggLine += " (ET)";
      detailParts.push(aggLine);
    }
    if (t.penalties_played) {
      if (t.penalty_a != null && t.penalty_b != null) detailParts.push("PENS " + t.penalty_a + "-" + t.penalty_b);
      else if (t.penalty_score) detailParts.push("PENS " + t.penalty_score);
    }
    if (t.winner) detailParts.push("WINNER " + t.winner);
  } else if (legs.length === 1) {
    const l = legs[0];
    resultLine = l.home_score != null ? (l.home_score + "-" + l.away_score) : null;
    appendOutcomeNotes();
  } else if (hasAgg && played) {
    resultLine = "AGG " + t.aggregate_a + "-" + t.aggregate_b;
    appendOutcomeNotes();
  }

  let status;
  if (played) status = "played";
  else if (t.status === "scheduled" || t.status === "unavailable" || t.status === "tbd") status = t.status;
  else status = teamsKnown ? "scheduled" : "tbd";

  const id = t.id || t.match_id || "";
  return {
    id,
    parents: (Array.isArray(t.source_matches) && t.source_matches.length)
      ? t.source_matches.slice() : null,
    teamA: t.team_a || null,
    teamB: t.team_b || null,
    status,
    provenance: t.provenance || "official",
    winner: t.winner || null,
    resultLine: resultLine != null ? resultLine : (teamsKnown ? "vs" : "?-?"),
    // Adapter owns every HTML fragment it emits; escape all dynamic text.
    detailHtml: detailParts.map(function(p) { return _esc(p); }).join("<br>"),
    sim: null,
    clickable: teamsKnown,
    _stageLabel: stageLabel || "",
  };
}

// Attach the simulation annotation for an undecided real slot.
function _withSimOverlay(m, sm) {
  const out = Object.assign({}, m);
  const hasAgg = sm.aggregate_a != null && sm.aggregate_b != null;
  const probA = typeof sm.prob_a === "number" ? sm.prob_a : undefined;
  const line = hasAgg ? ("SIM " + sm.aggregate_a + "-" + sm.aggregate_b) : null;
  if (line == null && probA == null) return out;
  out.sim = { line, probA };
  return out;
}

// Rich tie/match intelligence modal. Opens the shared modal shell
// immediately with teams/stage/id, then hydrates from
// /ucl/api/match/insight (frozen wave-2 contract) and renders result,
// signals, distribution, form, h2h, insight and What-If controls inside it.
async function openTiePopup(m) {
  const tieId = m.id || "";
  if (!tieId) return;
  destroyModalCharts();
  openIntelModal({
    titleHtml:
      '<span style="color:#16A085">' + _esc(m.teamA || "TBD") + "</span>"
      + ' <span style="color:#15565B;font-weight:normal">vs</span> '
      + '<span style="color:#e67e22">' + _esc(m.teamB || "TBD") + "</span>",
    sub: (m._stageLabel ? m._stageLabel + " - " : "") + tieId,
    bodyHtml: '<div class="dim" style="padding:8px 4px;font-size:12px">'
      + "Loading intelligence...</div>",
  });

  let ins;
  try {
    ins = await safeJson(API + "/match/insight?match_id="
      + encodeURIComponent(tieId));
  } catch (e) {
    _setModalBody('<div style="color:#ff6b6b;font-size:12px">'
      + "Failed to load tie intelligence: " + _esc(e.message) + "</div>");
    return;
  }
  if (ins.error) {
    const unresolved = String(ins.error).indexOf("teams not set") !== -1;
    _setModalBody('<div class="dim" style="padding:8px 4px;font-size:12px">'
      + (unresolved
        ? "Slot unresolved - intelligence unavailable."
        : _esc(ins.error))
      + "</div>");
    return;
  }
  _renderTieIntelligence(ins, m);
}

function _setModalBody(html) {
  const el = document.getElementById("modalBody");
  if (el) el.innerHTML = html;
}

function _provenanceChip(ins, cardProv) {
  const raw = cardProv === "simulated" ? "simulated" : (ins.provenance || "official");
  const p = String(raw).toLowerCase();
  let token = "REAL", cls = "prov-real";
  if (p === "manual") { token = "MANUAL"; cls = "prov-manual"; }
  else if (p === "simulated") { token = "SIMULATION"; cls = "prov-sim"; }
  else if (p === "snapshot") { token = "SNAPSHOT"; cls = "prov-snap"; }
  return '<span class="prov-chip ' + cls + '">' + token + "</span>";
}

function _enDashScore(h, a) {
  return _esc(h != null ? h : "-") + "\u2013" + _esc(a != null ? a : "-");
}

function _tieResultHtml(ins) {
  let h = '<div class="sec-title">Result</div>';
  const agg = ins.aggregate;
  const legs = Array.isArray(ins.legs) ? ins.legs : [];
  const hasAgg = !!(agg && agg.a != null && agg.b != null);
  const row = function(lbl, left, mid, right, strong) {
    return "<tr" + (strong ? ' style="font-weight:bold"' : "")
      + "><td>" + lbl + '</td><td style="text-align:right">' + left
      + '</td><td class="num">' + mid + "</td><td>" + right + "</td></tr>";
  };
  const etRow = function() {
    if (ins.et && ins.et.played) h += row("ET", "", _enDashScore(ins.et.a, ins.et.b), "");
  };
  const pensRow = function() {
    if (ins.pens && ins.pens.played) h += row("PENS", "", _esc(ins.pens.score || "?"), "");
  };
  if (ins.kind === "tie") {
    h += '<table class="wi-table">';
    if (legs.length >= 2) {
      legs.forEach(function(l) {
        h += row("LEG " + (l.leg != null ? l.leg : "?"), _esc(l.home || "?"),
          _enDashScore(l.home_score, l.away_score), _esc(l.away || "?"));
      });
    }
    if (hasAgg) {
      h += row("AGGREGATE", _esc(ins.teams.a), _enDashScore(agg.a, agg.b),
        _esc(ins.teams.b), true);
    }
    etRow();
    pensRow();
    h += "</table>";
    if (!legs.length && hasAgg && ins.availability_note) {
      h += '<div class="intel-note">' + _esc(ins.availability_note) + "</div>";
    }
  } else {
    const sc = ins.score || {};
    h += '<table class="wi-table">';
    h += row("SCORE", _esc(ins.teams.a), _enDashScore(sc.home, sc.away), _esc(ins.teams.b));
    etRow();
    pensRow();
    h += "</table>";
  }
  if (ins.winner) {
    h += '<div style="padding:4px 8px;font-size:12px;color:#16A085;font-weight:bold">'
      + "WINNER: " + _esc(ins.winner) + "</div>";
  }
  return h;
}

function _tiePredictionHtml(ins) {
  const bpAvailable = ins.prob_available === true
    && typeof ins.blended_prob === "number";
  let h = '<div class="sec-title">Blended Prediction</div>';
  h += bpAvailable
    ? '<div class="stat-card" style="margin:4px 0"><div class="val">'
      + Math.round(ins.blended_prob * 100) + '%</div><div class="lbl">'
      + _esc(ins.teams.a) + ' win</div></div>'
    : '<div class="dim" style="padding:6px 4px;font-size:12px">'
      + "Prediction unavailable"
      + (ins.prob_reason ? " (" + _esc(ins.prob_reason) + ")" : "") + ".</div>";
  return h;
}

function _tieDistributionHtml(ins) {
  let h = '<div class="sec-title">Outcome Distribution</div>';
  const o = ins.outcome_distribution;
  if (!o || typeof o.a_win !== "number" || typeof o.draw !== "number"
      || typeof o.b_win !== "number") {
    return h + '<div class="dim" style="padding:4px;font-size:11px">'
      + "Outcome distribution unavailable without a blended prediction.</div>";
  }
  const total = o.a_win + o.draw + o.b_win;
  if (!(total > 0)) {
    return h + '<div class="dim" style="padding:4px;font-size:11px">'
      + "Outcome distribution unavailable.</div>";
  }
  const seg = function(v, color) {
    return '<div class="outcome-stack-seg" style="width:'
      + ((v / total) * 100).toFixed(2) + "%;background:" + color + '"></div>';
  };
  h += '<div class="outcome-stack-bar">'
    + seg(o.a_win, "#16A085") + seg(o.draw, "#156F69") + seg(o.b_win, "#153D4C")
    + "</div>";
  h += '<div class="outcome-stack-lbl"><span>' + _esc(ins.teams.a) + " "
    + Math.round((o.a_win / total) * 100) + "%</span><span>Draw "
    + Math.round((o.draw / total) * 100) + "%</span><span>"
    + Math.round((o.b_win / total) * 100) + "% " + _esc(ins.teams.b)
    + "</span></div>";
  return h;
}

function _tieFormHtml(ins) {
  const ft = ins.form_trends || {};
  let h = '<div class="sec-title">Form Trend</div>';
  const rows = [];
  [ins.teams.a, ins.teams.b].forEach(function(team) {
    const tr = ft[team];
    if (!Array.isArray(tr) || !tr.length) return;
    const cells = tr.map(function(r) {
      const res = r && r.result;
      if (res === "W") return '<span class="dot-green">W</span>';
      if (res === "L") return '<span class="dot-red">L</span>';
      return "D";
    }).join(" ");
    rows.push("<tr><td>" + _esc(team) + "</td><td>" + cells + "</td></tr>");
  });
  if (!rows.length) {
    return h + '<div class="dim" style="padding:4px;font-size:11px">'
      + "No recent-form data.</div>";
  }
  return h + '<table class="wi-table">' + rows.join("") + "</table>";
}

function _tieRightColumnHtml(ins) {
  const sigs = ins.signals || {};
  const keys = Object.keys(sigs);
  let h = '<div class="sec-title">Signal Breakdown</div>';
  h += '<table class="insight-table"><tr><th>Signal</th><th>Prob</th><th>Weight</th></tr>';
  if (!keys.length) {
    h += '<tr><td colspan="3" style="color:#15565B">No signal data for this tie.</td></tr>';
  } else {
    keys.forEach(function(sk) {
      const sd = sigs[sk];
      if (!sd) return;
      h += "<tr><td>" + _esc(sd.label || sk) + '</td><td class="num">'
        + Math.round((sd.probability != null ? sd.probability : 0) * 100)
        + '%</td><td class="num">'
        + ((sd.weight != null ? sd.weight : 0) * 100).toFixed(1) + "%</td></tr>";
    });
  }
  h += "</table>";
  const h2h = ins.head_to_head;
  if (h2h && typeof h2h.total === "number" && h2h.total > 0) {
    h += '<div class="sec-title">Head-to-Head</div>'
      + '<div style="padding:4px 2px;font-size:11px">'
      + _esc(ins.teams.a) + " " + (h2h.a_wins || 0) + " wins &middot; "
      + (h2h.draws || 0) + " draws &middot; " + (h2h.b_wins || 0) + " wins "
      + _esc(ins.teams.b) + " (" + h2h.total + " played)</div>";
  }
  h += '<div class="sec-title">Match Insight</div><div class="insight-box">'
    + (ins.insight || "No insight available.") + "</div>";
  return h;
}

function _tieWhatIfHtml(ta) {
  return '<div class="sec-title warn">What-If Scenario</div>'
    + '<div class="whatif-controls">'
    + '<label>Elo boost for ' + _esc(ta) + ':</label>'
    + '<input type="number" id="tieWiDelta" value="50" step="10" min="-600"'
    + ' max="600" style="width:80px;background:#0d2430;color:#F6DBC0;'
    + 'border:1px solid rgba(21,61,76,.4);border-radius:4px;padding:4px 6px;'
    + 'font-size:11px">'
    + '<select id="tieWiIters" style="background:#0d2430;color:#F6DBC0;'
    + 'border:1px solid rgba(21,61,76,.4);border-radius:4px;padding:4px;'
    + 'font-size:11px">'
    + '<option value="1000">1,000</option>'
    + '<option value="5000" selected>5,000</option>'
    + '<option value="10000">10,000</option></select>'
    + '<button class="status-btn" id="tieWiRun">&#9654; Run What-If</button>'
    + "</div>"
    + '<div class="whatif-result" id="tieWiResult" style="display:none"></div>'
    + '<div class="dim" style="padding:2px 0;font-size:10px">'
    + "Adjusts Elo for both teams and re-runs a seeded Monte Carlo. "
    + "Factual history is never modified.</div>";
}

async function _runTieWhatIf(tieId, ta, tb) {
  const deltaInput = document.getElementById("tieWiDelta");
  const itersSel = document.getElementById("tieWiIters");
  const btn = document.getElementById("tieWiRun");
  const resultDiv = document.getElementById("tieWiResult");
  if (!deltaInput || !resultDiv) return;
  let eloDelta = parseInt(deltaInput.value, 10);
  if (!Number.isFinite(eloDelta)) eloDelta = 50;
  eloDelta = Math.max(-600, Math.min(600, eloDelta));
  const iterations = parseInt(itersSel ? itersSel.value : "5000", 10) || 5000;
  if (btn) btn.disabled = true;
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<div style="color:#15565B;font-size:11px">'
    + "Running seeded counterfactual...</div>";
  try {
    const resp = await safeJson(API + "/what-if", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        match_id: tieId, elo_delta: eloDelta, iterations: iterations,
      }),
    });
    if (resp.error) {
      resultDiv.innerHTML = '<div style="color:#ff6b6b;font-size:11px">'
        + _esc(resp.error) + "</div>";
      return;
    }
    const teamsResp = resp.teams || {};
    const rowFn = function(name) {
      const e = teamsResp[name] || {};
      const dlt = e.delta || 0;
      const cls = dlt >= 0 ? "wir-diff-pos" : "wir-diff-neg";
      return "<tr><td>" + _esc(name) + '</td><td class="num">'
        + ((e.baseline || 0) * 100).toFixed(1) + '%</td><td class="num">'
        + ((e.adjusted || 0) * 100).toFixed(1) + '%</td><td class="num '
        + cls + '">' + (dlt >= 0 ? "+" : "") + (dlt * 100).toFixed(1)
        + " pp</td></tr>";
    };
    let html = '<div class="wir-head">WHAT-IF (SIMULATED) - champion '
      + "probability, baseline vs adjusted</div>";
    html += '<table class="wi-table"><tr><th>Team</th><th>Baseline</th>'
      + "<th>Adjusted</th><th>Delta (pp)</th></tr>"
      + rowFn(ta) + rowFn(tb) + "</table>";
    html += '<div class="wir-meta">Factual history unchanged.</div>';
    resultDiv.innerHTML = html;
  } catch (e) {
    resultDiv.innerHTML = '<div style="color:#ff6b6b;font-size:11px">Error: '
      + _esc(e.message) + "</div>";
  } finally {
    const b2 = document.getElementById("tieWiRun");
    if (b2) b2.disabled = false;
  }
}

function _renderTieIntelligence(ins, m) {
  const ta = ins.teams.a, tb = ins.teams.b;
  const titleEl = document.getElementById("modalTitle");
  if (titleEl) {
    titleEl.innerHTML =
      '<span style="color:#16A085">' + _esc(ta || "TBD") + "</span>"
      + ' <span style="color:#15565B;font-weight:normal">vs</span> '
      + '<span style="color:#e67e22">' + _esc(tb || "TBD") + "</span>"
      + _provenanceChip(ins, m.provenance);
  }
  const subParts = [];
  if (m._stageLabel) subParts.push(m._stageLabel);
  if (ins.round && subParts.indexOf(ins.round) === -1) subParts.push(ins.round);
  subParts.push(ins.kind === "tie" ? "TIE" : "MATCH");
  subParts.push(ins.match_id || m.id || "");
  const subEl = document.getElementById("modalSub");
  if (subEl) subEl.textContent = subParts.filter(Boolean).join(" - ");

  const leftHtml = _tieResultHtml(ins) + _tiePredictionHtml(ins)
    + _tieDistributionHtml(ins) + _tieFormHtml(ins);
  const rightHtml = _tieRightColumnHtml(ins);
  _setModalBody(
    '<div class="mb-wrap"><div class="mb-col">' + leftHtml + "</div>"
    + '<div class="mb-col">' + rightHtml + "</div></div>"
    + _tieWhatIfHtml(ta));

  const runBtn = document.getElementById("tieWiRun");
  if (runBtn) {
    runBtn.addEventListener("click", function() {
      _runTieWhatIf(ins.match_id || m.id, ta, tb);
    });
  }
}

// ES modules create no globals, so inline onclick attributes cannot reach
// openMatchModalFromEl; bind listeners after each render instead.
function bindMatchClicks(scope) {
  scope.querySelectorAll(".match-clickable").forEach(function (el) {
    el.addEventListener("click", function () { openMatchModalFromEl(el); });
  });
}

// ── Match intelligence modal ─────────────────────────────────────────

function openMatchModalFromEl(el) {
  const mid = el.getAttribute('data-match-id');
  if (!mid) return;
  openMatchModal({ match_id: mid, team_a: el.getAttribute('data-team-a') || '', team_b: el.getAttribute('data-team-b') || '' });
}

async function openMatchModal(m) {
  destroyModalCharts();
  var mid = m.match_id;
  if (!mid) return;

  document.getElementById("modalTitle").innerHTML =
    '<span style="color:#16A085">' + (m.team_a || "TBD") + '</span>' +
    ' <span style="color:#15565B;font-weight:normal">vs</span> ' +
    '<span style="color:#e67e22">' + (m.team_b || "TBD") + '</span>';
  document.getElementById("modalSub").textContent = mid;
  document.getElementById("modalBody").innerHTML =
    '<div class="mb-wrap"><div class="mb-col" id="mbLeft"></div>' +
    '<div class="mb-col" id="mbRight"></div></div><div id="modalBottom"></div>';
  document.getElementById("modalOverlay").classList.add("show");

  var bodyEl = document.getElementById("modalBody");
  var left = document.getElementById("mbLeft");
  var right = document.getElementById("mbRight");

  var insight;
  try {
    insight = await safeJson(API + "/match/insight?match_id=" + encodeURIComponent(mid));
  } catch (e) {
    bodyEl.innerHTML = '<div style="color:#ff6b6b;font-size:12px">Failed to load match insight.</div>';
    return;
  }
  if (insight.error) {
    bodyEl.innerHTML = '<div style="color:#ff6b6b;font-size:12px">' + insight.error + '</div>';
    return;
  }

  var ta = insight.teams.a, tb = insight.teams.b;
  var sigs = insight.signals || {};
  var sigKeys = Object.keys(sigs);
  // Truth contract: blended_prob is null when the model could not produce a
  // prediction. Never substitute a default probability for it.
  var bpAvailable = insight.prob_available === true && typeof insight.blended_prob === "number";
  var bp = bpAvailable ? insight.blended_prob : null;
  var outcome = (bpAvailable && insight.outcome_distribution) || null;
  var ft = insight.form_trends || {};
  var playedFlag = insight.played === true;

  var leftHtml =
    '<div class="sec-title">Blended Prediction</div>' +
    (bpAvailable
      ? '<div class="stat-card" style="margin:4px 0"><div class="val">' +
        Math.round(bp * 100) + '%</div><div class="lbl">' + ta + ' win</div></div>'
      : '<div class="dim" style="padding:6px 4px;font-size:12px">Prediction unavailable'
        + (insight.prob_reason ? ' (' + insight.prob_reason + ')' : '') + '.</div>');

  leftHtml += '<div class="sec-title">Form Trend</div><div class="form-charts">' +
    [ta, tb].map(function(team) {
      return '<div class="form-chart-box"><div class="fc-label">' + team +
        '</div><canvas id="fc-' + team.replace(/\s/g, "") + '"></canvas></div>';
    }).join("") +
    '</div><div class="sec-title">Signal Comparison</div>' +
    '<div class="chart-box"><canvas id="sigChart"></canvas></div>' +
    '<div class="sec-title">Outcome Distribution</div>';
  leftHtml += (outcome
    ? '<div class="outcome-charts"><div class="outcome-chart-box"><canvas id="outcomeChart"></canvas></div></div>'
    : '<div class="dim" style="padding:4px;font-size:11px">Outcome distribution unavailable without a blended prediction.</div>');
  leftHtml += '<div class="sec-title">Result</div>';
  leftHtml += playedFlag
    ? '<div class="dim" style="padding:4px;font-size:12px">Played' +
      (insight.score ? ' - ' + insight.score.home + ' - ' + insight.score.away : '') +
      (insight.winner ? ' (winner: ' + insight.winner + ')' : '') + '</div>'
    : '<div class="dim" style="padding:4px;font-size:12px">Scheduled - no result yet.</div>';
  left.innerHTML = leftHtml;

  var sigHtml = '<div class="sec-title">Signal Breakdown</div>';
  sigHtml += '<table class="insight-table"><tr><th>Signal</th><th>Prob</th><th>Weight</th></tr>';
  var hasSignals = false;
  sigKeys.forEach(function(sk) {
    var sd = sigs[sk];
    if (!sd) return;
    hasSignals = true;
    sigHtml += '<tr><td>' + (sd.label || sk) + '</td><td class="num">' +
      Math.round((sd.probability != null ? sd.probability : 0) * 100) + '%</td><td class="num">' +
      ((sd.weight != null ? sd.weight : 0) * 100).toFixed(1) + '%</td></tr>';
  });
  if (!hasSignals) sigHtml += '<tr><td colspan="3" style="color:#15565B">No signal data for this match.</td></tr>';
  sigHtml += '</table>';
  right.innerHTML = sigHtml +
    '<div class="sec-title">Match Insight</div>' +
    '<div class="insight-box">' + (insight.insight || "No insight available.") + '</div>';

  var bottomEl = document.getElementById("modalBottom");
  bottomEl.innerHTML =
    '<div class="sec-title warn">What-If Scenario</div>' +
    '<div class="whatif-input-wrap"><input type="number" id="modalWhatifDelta" value="50" step="10" style="width:90px">' +
    '<button onclick="window.__sendModalWhatIf(\'' + mid.replace(/'/g, "\\'") + '\',\'' + ta.replace(/'/g, "\\'") + '\',\'' + tb.replace(/'/g, "\\'") + '\')">&#9654;</button></div>' +
    '<div class="whatif-controls"><label>Elo boost for ' + ta + ':</label></div>' +
    '<div class="whatif-modal-result" id="modalWhatifResult"></div>';

  [ta, tb].forEach(function(team) {
    var tr = ft[team] || [];
    var canvas = document.getElementById("fc-" + team.replace(/\s/g, ""));
    if (!canvas || typeof Chart === "undefined") return;
    var labels = tr.map(function(_, i) { return "M" + (i + 1); });
    var vals = tr.map(function(r) { return r.result === "W" ? 1 : r.result === "D" ? 0.5 : 0; });
    modalCharts["form_" + team] = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: { labels: labels, datasets: [{ data: vals,
        borderColor: "#16A085", backgroundColor: "transparent",
        pointBackgroundColor: "#16A085", borderWidth: 2, tension: 0.3, pointRadius: 3 }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { min: -0.1, max: 1.1, display: false } } }
    });
  });

  var sigCanvas = document.getElementById("sigChart");
  if (sigCanvas && typeof Chart !== "undefined" && sigKeys.length > 0) {
    var sigVals = sigKeys.map(function(sk) {
      return Math.round((sigs[sk].probability != null ? sigs[sk].probability : 0) * 100);
    });
    var sigColors = sigKeys.map(function(sk, i) {
      return i === 0 ? "#16A085" : "#156F69";
    });
    modalCharts.signals = new Chart(sigCanvas.getContext("2d"), {
      type: "bar",
      data: { labels: sigKeys.map(function(sk) { return sk; }),
        datasets: [{ data: sigVals, backgroundColor: sigColors,
          borderRadius: 2, borderSkipped: false }] },
      options: { responsive: true, maintainAspectRatio: false, indexAxis: "y",
        plugins: { legend: { display: false },
          tooltip: { callbacks: { label: function(ctx) { return ctx.parsed.x + "%"; } } } },
        scales: { x: { min: 0, max: 100, grid: { color: "rgba(21,61,76,0.2)" },
          ticks: { color: "#15565B", font: { size: 9 }, callback: function(v) { return v + "%"; } } },
          y: { grid: { display: false }, ticks: { color: "#F6DBC0", font: { size: 9 } } } } }
    });
  }

  // Doughnut only when a real distribution exists - never draw fabricated
  // equal-thirds slices for missing data.
  var ocCanvas = document.getElementById("outcomeChart");
  if (ocCanvas && typeof Chart !== "undefined" && outcome &&
      typeof outcome.a_win === "number" &&
      typeof outcome.draw === "number" &&
      typeof outcome.b_win === "number") {
    modalCharts.outcome = new Chart(ocCanvas.getContext("2d"), {
      type: "doughnut",
      data: { labels: [ta + " win", "Draw", tb + " win"],
        datasets: [{ data: [outcome.a_win, outcome.draw, outcome.b_win],
          backgroundColor: ["#16A085", "#156F69", "#153D4C"],
          borderColor: "#140C30", borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom",
          labels: { color: "#F6DBC0", font: { size: 9 }, boxWidth: 10, padding: 6 } },
          tooltip: { callbacks: { label: function(ctx) {
            return ctx.label + ": " + (ctx.parsed * 100).toFixed(1) + "%"; } } } },
        cutout: "55%" }
    });
  }
}

window.__sendModalWhatIf = async function(matchId, teamA, teamB) {
  var deltaInput = document.getElementById("modalWhatifDelta");
  var eloDelta = parseInt(deltaInput ? deltaInput.value : 50) || 50;
  var resultDiv = document.getElementById("modalWhatifResult");
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<div style="color:#15565B;font-size:11px">Running seeded counterfactual...</div>';
  try {
    var resp = await safeJson(API + "/what-if", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: matchId, elo_delta: eloDelta })
    });
    if (resp.error) {
      resultDiv.innerHTML = '<div style="color:#ff6b6b">' + resp.error + '</div>';
      return;
    }
    var rowFn = function(name, e) {
      var t = resp.teams[name] || {};
      var d = t.delta || 0;
      var cls = d >= 0 ? "wir-diff-pos" : "wir-diff-neg";
      return '<tr><td>' + name + ' (Elo ' + e + ')</td><td class="num">' +
        ((t.baseline || 0) * 100).toFixed(1) + '%</td><td class="num">' +
        ((t.adjusted || 0) * 100).toFixed(1) + '%</td><td class="num ' + cls + '">' +
        (d >= 0 ? "+" : "") + (d * 100).toFixed(1) + '%</td></tr>';
    };
    var html = '<div class="wir-head">Champion probability: baseline vs adjusted</div>';
    html += '<table class="odds-table" style="width:100%">';
    html += rowFn(teamA, (resp.elo_changes || {})[teamA] || "?");
    html += rowFn(teamB, (resp.elo_changes || {})[teamB] || "?");
    html += "</table>";
    resultDiv.innerHTML = html;
  } catch (e) {
    resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + '</div>';
  }
};
