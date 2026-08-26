// ═══ UCL 2025/26 Module ═══
import {
  destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions, showSimPopup,
  buildTable, safeJson,
} from "./shared.js";

const API = "/ucl/api";
const appState = { data: null, standings: [], bracket: null, odds: [], signals: {}, simProjections: null, simMeta: null, simRunCount: 0, simBracketRounds: null, simPlayoff: null };

const sigLabels = {
  refined_elo: "Refined Elo", market_odds: "Market Odds", rolling_form: "Rolling Form",
  squad_value: "Squad Value", rest_days: "Rest Days",
};
const sigOrder = ["refined_elo", "rolling_form", "market_odds", "squad_value", "rest_days"];

export function init(comp) {
  loadAll();
}

// ── Data loading ─────────────────────────────────────────────────────

async function loadAll() {
  try {
    const [d, s, br, o, sig] = await Promise.all([
      safeJson(API + "/data"),
      safeJson(API + "/standings"),
      safeJson(API + "/bracket"),
      safeJson(API + "/odds"),
      safeJson(API + "/signals"),
    ]);
    appState.data = d;
    appState.standings = s.standings || [];
    appState.bracket = br;
    appState.odds = o.odds || [];
    appState.signals = sig.signals || {};

    // Session persistence: a run completed against this server process
    // must survive page reloads and hash navigation. The backend keeps
    // completed results in its session store; hydrate from it so the UI
    // reflects reality instead of claiming no simulation was ever run.
    if (d.simulation && d.simulation.request_state === "completed"
        && !(appState.simProjections && appState.simProjections.length)) {
      try {
        _applySimulationPayload(await safeJson(API + "/simulation"), 0);
      } catch (e) { console.error("simulation hydration failed:", e); }
    }
  } catch (e) {
    console.error("loadAll API fetch failed:", e);
    const tab = document.getElementById("tab-overview");
    if (tab) tab.innerHTML = '<div class="stat-card" style="color:#ff6b6b">Failed to load UCL data: ' + e.message + '</div>';
    return;
  }

  renderOverview();
  renderStandings();
  renderBracket();
  updateStatus();
}

async function reloadData() {
  try {
    const [d, s, br, o, sig] = await Promise.all([
      safeJson(API + "/data"),
      safeJson(API + "/standings"),
      safeJson(API + "/bracket"),
      safeJson(API + "/odds"),
      safeJson(API + "/signals"),
    ]);
    appState.data = d;
    appState.standings = s.standings || [];
    appState.bracket = br;
    appState.odds = o.odds || [];
    appState.signals = sig.signals || {};
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

  // Stat cards: Teams / Matches Played / Stage  (WC-style hierarchy)
  let html = '<div class="stats-row">';
  html += '<div class="stat-card"><div class="val">' + (d.n_teams || 0) + '</div><div class="lbl">Teams</div></div>';
  html += '<div class="stat-card"><div class="val">' + (d.n_played || 0) + '</div><div class="lbl">Matches Played</div></div>';
  html += '<div class="stat-card"><div class="val" style="font-size:.75em">' + stage + '</div><div class="lbl">Stage</div></div>';
  html += '<div class="stat-card"><div class="val">' + nActive + ' / ' + sigOrder.length + '</div><div class="lbl">Signals Available</div></div>';
  if (d.snapshot_date) html += '<div class="stat-card"><div class="val" style="font-size:.8em">' + d.snapshot_date + '</div><div class="lbl">Season</div></div>';
  html += '</div>';

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
  const simState = d.simulation || {};
  const availability = simState.availability || "available";
  const requestState = simState.request_state || "not_requested";
  html += '<div class="chart-section"><div class="title">Simulation</div>';

  if (availability === "not_needed") {
    html += '<div class="dim" style="padding:4px 8px;font-size:12px">'
      + 'All competition results are already known from real match data. '
      + 'Simulation is not needed.</div>';
  } else if (requestState === "running") {
    html += '<div class="dim" style="padding:4px 8px;font-size:12px">'
      + 'A simulation is currently running. Reload in a moment to see its '
      + 'projections.</div>';
  } else {
    if (requestState === "completed" && appState.simProjections
        && appState.simProjections.length) {
      const m = appState.simMeta || {};
      html += '<div class="dim" style="padding:2px 8px;font-size:11px;color:#8E44AD">'
        + 'SIMULATION &middot; ' + (appState.simRunCount || 0).toLocaleString()
        + ' RUNS' + (m.seed != null ? ' &middot; seed ' + m.seed : '')
        + ' - projected probabilities, not real results.</div>';
      html += '<table class="eval-table"><tr><th>#</th><th>Team</th><th>Champion %</th></tr>';
      appState.simProjections.slice(0, 5).forEach(function(o, i) {
        const pct = ((o.champion_prob || 0) * 100).toFixed(1);
        html += '<tr><td class="num">' + (i + 1) + '</td><td>' + o.team
          + '</td><td class="num">' + pct + '%</td></tr>';
      });
      html += '</table>';
    } else if (requestState === "failed") {
      html += '<div class="dim" style="padding:4px 8px;font-size:12px;color:#ff6b6b">'
        + 'The last simulation failed. No projected probabilities exist.</div>';
    } else {
      html += '<div class="dim" style="padding:2px 8px;font-size:11px">'
        + 'No simulation has been run in this session, so no projected '
        + 'probabilities exist.</div>';
    }

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

  html += '</div>';

  tab.innerHTML = html;
  bindSimulationControls();
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
  appState.simBracketRounds = sim.bracket_rounds || null;
  appState.simPlayoff = sim.playoff || null;
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

  const playoff = br.playoff || [];
  const rounds = br.bracket_rounds || {};
  const lmd = br.league_matchdays || {};
  const lmdKeys = Object.keys(lmd).sort();

  let html = "";

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

  // ── Section 2: Knockout Playoffs ──
  if (playoff.length) {
    html += '<div class="chart-section"><div class="title">Knockout Playoffs</div><div class="playoff-grid">';
    playoff.forEach(function(t) {
      const aggStr = t.aggregate_a + "-" + t.aggregate_b;
      let detail = aggStr + " agg";
      if (t.et_played) detail += " (ET)";
      if (t.penalties_played) detail += " (pens)";
      html += '<div class="playoff-card match-clickable" data-match-id="' + (t.match_id || "") + '"'
        + ' data-team-a="' + (t.team_a || "") + '" data-team-b="' + (t.team_b || "") + '"'
        + ' style="cursor:pointer">'
        + '<div class="p-title">Tie ' + t.tie_num + '</div>'
        + '<div class="p-teams"><span class="p-team">' + (t.team_a || "?") + '</span><span class="p-score">' + aggStr + '</span><span class="p-team">' + (t.team_b || "?") + '</span></div>'
        + '<div class="p-detail">' + detail + "</div></div>";
    });
    html += "</div></div>";
  } else {
    // Data-derived qualification view: positions 9-24 from final standings.
    html += '<div class="chart-section"><div class="title">Knockout Playoffs</div>';
    const st = appState.standings || [];
    const qual = st.filter(function(r) { return r.zone === "playoff"; });
    if (qual.length) {
      html += '<div class="dim" style="padding:4px 8px;font-size:11px;color:#15565B">'
        + 'Playoff results unavailable in current snapshot. Qualified teams (positions 9-24):</div>';
      html += '<div style="display:flex;flex-wrap:wrap;gap:6px;padding:8px">';
      qual.forEach(function(r) {
        html += '<span class="zone-badge playoff">' + r.position + '. ' + r.team + '</span>';
      });
      html += '</div>';
    } else {
      html += '<div class="dim" style="padding:8px;color:#15565B;font-size:11px">Playoff results unavailable in current snapshot.</div>';
    }
    html += '</div>';
  }

  // ── Section 3: Knockout Rounds (R16 -> QF -> SF -> Final) ──
  const roundMeta = [
    { key: "R16", label: "Round of 16" },
    { key: "QF", label: "Quarter-Finals" },
    { key: "SF", label: "Semi-Finals" },
    { key: "FINAL", label: "Final" },
  ];

  let koSection = '<div class="chart-section"><div class="title">Knockout Stage</div>';
  let anyKoData = false;

  roundMeta.forEach(function(rm) {
    const ms = rounds[rm.key] || [];
    if (!ms.length) return;
    anyKoData = true;
    koSection += '<div style="margin:10px 0 4px"><strong style="color:#16A085;font-size:12px">' + rm.label + '</strong></div>';
    koSection += '<div class="ko-round-cards">';
    ms.forEach(function(m) {
      const ta = m.team_a || "?"; const tb = m.team_b || "?";
      const agg = m.aggregate_a !== undefined ? (m.aggregate_a + " - " + m.aggregate_b) :
                   (m.home_score !== undefined ? (m.home_score + "-" + m.away_score) : "TBD");
      const winner = m.winner || "";
      koSection += '<div class="ko-match-card match-clickable"'
        + ' data-match-id="' + (m.match_id || "") + '"'
        + ' data-team-a="' + ta + '" data-team-b="' + tb + '">'
        + '<div class="ko-round-tag">' + rm.label + '</div>'
        + '<div class="ko-teams"><span>' + ta + '</span><span class="ko-vs">vs</span><span>' + tb + '</span></div>'
        + '<div class="ko-score">' + agg + '</div>'
        + (winner ? '<div class="ko-winner">Winner: ' + winner + '</div>' : '')
        + '</div>';
    });
    koSection += '</div>';
  });

  if (!anyKoData) {
    // Truth model: absence of knockout data in the snapshot is NOT proof
    // the stage was never played. Only a genuinely unreadable store may
    // speak about readability; otherwise report plain unavailability.
    const koStore = (appState.data && appState.data.phase
      && appState.data.phase.stores
      && appState.data.phase.stores.knockout_results) || "missing";
    koSection += '<div class="dim" style="padding:8px;font-size:11px">'
      + (koStore === "unavailable"
        ? "Knockout data exists but could not be read."
        : "Knockout results unavailable in current snapshot.")
      + '</div>';

    // Simulation overlay: when a completed run projected the unresolved
    // knockout path, surface it clearly marked as SIMULATION. Factual
    // wording above stays untouched; real results (anyKoData) always win.
    const simLive = appState.data && appState.data.simulation
      && appState.data.simulation.request_state === "completed";
    const simRounds = simLive ? (appState.simBracketRounds || {}) : {};
    const simTies = simLive ? (appState.simPlayoff || []) : [];
    const metaM = appState.simMeta || {};
    let anySimKo = false;
    const _simHeader = function() {
      if (anySimKo) return;
      anySimKo = true;
      koSection += '<div style="margin:12px 0 4px;padding:4px 8px;font-size:11px;color:#8E44AD">'
        + 'SIMULATION &middot; projected knockout path'
        + (appState.simRunCount ? ' &middot; ' + appState.simRunCount.toLocaleString() + ' runs' : '')
        + (metaM.seed != null ? ' &middot; seed ' + metaM.seed : '')
        + ' &middot; not real results</div>';
    };
    if (simTies.length) {
      _simHeader();
      koSection += '<div style="margin:10px 0 4px"><strong style="color:#8E44AD;font-size:12px">Knockout Playoffs</strong></div>';
      koSection += '<div class="ko-round-cards">';
      simTies.forEach(function(t) {
        const ta = t.team_a || "?"; const tb = t.team_b || "?";
        const aggStr = t.aggregate_a !== undefined
          ? (t.aggregate_a + " - " + t.aggregate_b) : "TBD";
        const winner = t.winner || "";
        koSection += '<div class="ko-match-card" style="border-color:#8E44AD">'
          + '<div class="ko-round-tag">Playoff &middot; SIM</div>'
          + '<div class="ko-teams"><span>' + ta + '</span><span class="ko-vs">vs</span><span>' + tb + '</span></div>'
          + '<div class="ko-score">' + aggStr + '</div>'
          + (winner ? '<div class="ko-winner">Winner: ' + winner + '</div>' : '')
          + '</div>';
      });
      koSection += '</div>';
    }
    roundMeta.forEach(function(rm) {
      const ms = simRounds[rm.key] || [];
      if (!ms.length) return;
      _simHeader();
      koSection += '<div style="margin:10px 0 4px"><strong style="color:#8E44AD;font-size:12px">' + rm.label + '</strong></div>';
      koSection += '<div class="ko-round-cards">';
      ms.forEach(function(sm) {
        const ta = sm.team_a || "?"; const tb = sm.team_b || "?";
        const agg = sm.aggregate_a !== undefined ? (sm.aggregate_a + " - " + sm.aggregate_b) :
                     (sm.home_score !== undefined ? (sm.home_score + "-" + sm.away_score) : "TBD");
        const winner = sm.winner || "";
        koSection += '<div class="ko-match-card" style="border-color:#8E44AD">'
          + '<div class="ko-round-tag">' + rm.label + ' &middot; SIM</div>'
          + '<div class="ko-teams"><span>' + ta + '</span><span class="ko-vs">vs</span><span>' + tb + '</span></div>'
          + '<div class="ko-score">' + agg + '</div>'
          + (winner ? '<div class="ko-winner">Winner: ' + winner + '</div>' : '')
          + '</div>';
      });
      koSection += '</div>';
    });
  }
  koSection += '</div>';
  html += koSection;

  tab.innerHTML = html;
  bindMatchClicks(tab);
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
