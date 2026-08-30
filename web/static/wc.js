// ── World Cup 2026 Module ──
import {
  buildTable, destroyModalCharts, modalCharts, renderBracketTree,
  updateStatusBar, competitions, renderLoading, currentCompetition,
} from "./shared.js";

const API = "/worldcup/api";
const sigLabels = { elo: "Elo", market_odds: "Market Odds", rolling_form: "Rolling Form", squad_value: "Squad Value", rest_days: "Rest Days" };
const appState = { data: null, overview: null, standings: null, bracket: null, fullBracket: null, eval: null, blend: null, signalCache: {} , simMeta: null };
let refreshing = false;
let autoRefreshOn = false;
let autoTimer = null;

let _transitionGen = 0;

function _isWcActive() {
  return !!(currentCompetition && currentCompetition.apiPrefix === API);
}

function _stale(gen) {
  return gen !== _transitionGen || !_isWcActive();
}

export function init(comp) {
  loadAll();
}

async function loadAll() {
  const gen = ++_transitionGen;
  // Loaders reflect the real in-flight fetches below (initial boot AND the
  // post-simulation reload). Each tab's render call replaces its loader once
  // data — or a truthful fallback — is ready. No artificial delay is added.
  renderLoading(document.getElementById("tab-overview"), "Loading overview...");
  renderLoading(document.getElementById("tab-standings"), "Loading standings...");
  renderLoading(document.getElementById("tab-bracket"), "Loading bracket...");

  let ov = null;
  try {
    ov = await fetch(API + "/overview").then(r => r.json());
  } catch (e) { console.error("overview load failed:", e); }
  if (_stale(gen)) return gen;
  appState.overview = ov;
  appState.data = ov;
  // Rendered unconditionally (with a truthful fallback when ov is null) so the
  // overview loader always clears, never sticks as a spinner.
  renderOverview();
  updateStatus();
  // Standings tab
  try {
    const s = await fetch(API + "/standings").then(r => r.json());
    if (_stale(gen)) return gen;
    appState.standings = s;
  } catch {}
  // Rendered unconditionally so the standings loader always clears (a failed
  // fetch falls through to renderStandings' truthful "not available" state).
  if (_stale(gen)) return gen;
  renderStandings();
  // Bracket tab — full bracket data (chronological + knockout tree)
  try {
    const br = await fetch(API + "/bracket").then(r => r.json());
    if (_stale(gen)) return gen;
    appState.bracket = br;
  } catch {}
  try {
    const bd = await fetch(API + "/bracket/data").then(r => r.json());
    if (_stale(gen)) return gen;
    appState.bracketData = bd;
  } catch {}
  try {
    const fb = await fetch(API + "/bracket/full").then(r => r.json());
    if (_stale(gen)) return gen;
    appState.fullBracket = fb;
  } catch {}
  if (_stale(gen)) return gen;
  renderBracket();
  return gen;
}

function updateStatus() {
  const d = appState.data;
  if (!d) return;
  if (refreshing) return;
  const signals = d.signals_meta?.signals || [];
  const nActive = signals.filter(s => s.available).length;
  const stale = d.refresh && d.refresh.stale;
  updateStatusBar(
    d.n_teams + " teams  |  " + d.n_played + " matches played  |  " + nActive + " active signals",
    stale ? '<span style="color:#e6a817">⚠ STALE — live refresh failed; showing snapshot data</span>' : ""
  );
}


function toggleAuto(on) {
  autoRefreshOn = on;
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  if (on) autoTimer = setInterval(() => doRefresh(), 60000);
  updateStatus();
}

// ── Simulation Popup ──
function showSimPopup() {
  if (refreshing) return;
  let overlay = document.getElementById("simPopupOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "simPopupOverlay";
    overlay.className = "sim-popup-overlay";
    overlay.innerHTML = `
      <div class="sim-popup">
        <h3>Simulate Tournament</h3>
        <p>Number of Monte Carlo iterations:</p>
        <div class="sim-presets" id="simPresets">
          <button data-iters="10000">10K</button>
          <button data-iters="50000" class="active">50K</button>
          <button data-iters="100000">100K</button>
          <button data-iters="500000">500K</button>
        </div>
        <input type="number" id="simCustomIters" value="50000" min="1" max="1000000">
        <div class="sim-actions">
          <button id="simCancelBtn">Cancel</button>
          <button id="simStartBtn">&#9654; Start</button>
        </div>
        <div id="simProgressWrap" class="progress-bar-wrap" style="display:none;margin-top:10px">
          <div class="progress-bar-fill" id="simProgressFill" style="width:0%"></div>
        </div>
        <div class="progress-lbl" id="simProgressLbl" style="display:none"></div>
      </div>
    `;
    document.body.appendChild(overlay);

    // Wire presets
    overlay.querySelectorAll(".sim-presets button").forEach(btn => {
      btn.addEventListener("click", () => {
        overlay.querySelectorAll(".sim-presets button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("simCustomIters").value = btn.dataset.iters;
      });
    });

    // Cancel
    document.getElementById("simCancelBtn").addEventListener("click", () => {
      overlay.classList.remove("show");
    });

    // Start
    document.getElementById("simStartBtn").addEventListener("click", startSimulation);

    // Overlay click to close
    overlay.addEventListener("click", e => {
      if (e.target === overlay) overlay.classList.remove("show");
    });
  }
  overlay.classList.add("show");
}

async function startSimulation() {
  refreshing = true;
  const iters = parseInt(document.getElementById("simCustomIters").value) || 50000;
  const startBtn = document.getElementById("simStartBtn");
  const cancelBtn = document.getElementById("simCancelBtn");
  const progressWrap = document.getElementById("simProgressWrap");
  const progressFill = document.getElementById("simProgressFill");
  const progressLbl = document.getElementById("simProgressLbl");

  startBtn.disabled = true;
  cancelBtn.style.display = "none";
  progressWrap.style.display = "block";
  progressLbl.style.display = "block";
  progressFill.style.width = "0%";
  progressLbl.textContent = "Starting simulation...";

  try {
    const resp = await (await fetch(API + "/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ iterations: iters })
    })).json();

    if (resp.error) {
      progressLbl.textContent = "Error: " + resp.error;
      startBtn.disabled = false;
      cancelBtn.style.display = "";
      refreshing = false;
      return;
    }

    if (resp.status === "not_needed") {
      progressLbl.textContent = resp.message || "All matches played.";
      startBtn.disabled = false;
      cancelBtn.style.display = "";
      refreshing = false;
      return;
    }

    const taskId = resp.task_id;
    const totalIters = resp.iterations;
    let t0 = Date.now();

    await new Promise((resolve, reject) => {
      const poll = setInterval(async () => {
        try {
          const p = await (await fetch(API + "/simulation/progress/" + taskId)).json();
          if (p.error) { clearInterval(poll); reject(new Error(p.error)); return; }

          progressFill.style.width = p.progress + "%";
          const elapsed = ((Date.now() - t0) / 1000).toFixed(0);
          let label = p.stage || "Simulating...";
          if (p.total_iterations > 0) {
            label += "  " + (p.iteration || 0).toLocaleString() + "/" + p.total_iterations.toLocaleString();
          }
          label += "  (" + p.progress.toFixed(0) + "%)  " + elapsed + "s";
          if (p.elapsed) label += "  ETA: " + Math.max(0, Math.round(p.elapsed * ((100 - p.progress) / Math.max(p.progress, 1)))) + "s";
          progressLbl.textContent = label;

          if (p.status === "completed") {
            clearInterval(poll);
            resolve();
          }
          if (p.status === "failed") {
            clearInterval(poll);
            reject(new Error(p.error || "simulation failed"));
          }
        } catch (e) {
          clearInterval(poll);
          reject(e);
        }
      }, 200);
    });

    // Complete — close popup, reload data
    document.getElementById("simPopupOverlay").classList.remove("show");
    progressWrap.style.display = "none";
    progressLbl.style.display = "none";
    const gen = await loadAll();
    try {
      const simResp = await fetch(API + "/simulation").then(r => r.json());
      if (!_stale(gen)) appState.simBracket = simResp.full_bracket ? simResp.full_bracket : null;
    } catch { if (!_stale(gen)) appState.simBracket = null; }
    if (!_stale(gen)) renderBracket();
  } catch (e) {
    progressLbl.textContent = "Error: " + (e.message || "unknown");
    startBtn.disabled = false;
    cancelBtn.style.display = "";
  }
  refreshing = false;
}

// ── Overview (real data only) ──

async function renderOverview() {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const ov = appState.overview || appState.data;
  if (!ov) { tab.innerHTML = '<div class="dim" style="padding:20px">Overview data not available yet.</div>'; return; }

  const signals = ov.signals_meta?.signals || [];
  const nActive = signals.filter(s => s.available).length;

  let html = '<div class="stats-row" id="statsRow">';
  html += '<div class="stat-card"><div class="val">' + ov.n_teams + '</div><div class="lbl">Teams</div></div>';
  html += '<div class="stat-card"><div class="val">' + ov.n_played + '</div><div class="lbl">Matches Played</div></div>';
  html += '<div class="stat-card"><div class="val">' + nActive + ' / ' + signals.length + '</div><div class="lbl">Signals Available</div></div>';
  html += '</div>';

  if (signals.length > 0) {
    html += '<div class="chart-section"><div class="title">Signal Cache Status</div>';
    html += '<div class="overview-signals" id="ovSignals">';
    html += renderOverviewSignals(signals);
    html += '</div></div>';
  }

  tab.innerHTML = html;
}

function renderSignalEval(signalEval) {
  const sigOrder = ["elo", "all_signals", "market_odds", "rolling_form", "squad_value", "rest_days"];
  const labels = { elo: "Elo", all_signals: "Blended", market_odds: "Market Odds", rolling_form: "Rolling Form", squad_value: "Squad Value", rest_days: "Rest Days" };
  let html = '<table class="eval-table"><tr><th>Signal</th><th>Brier</th><th>Accuracy</th><th>Matches</th></tr>';
  sigOrder.forEach(sk => {
    const e = signalEval[sk];
    if (!e) return;
    const nMatches = e.n_matches || e.n || 0;
    if (!nMatches) return;
    const metrics = e.metrics || e;
    const brier = metrics.brier != null ? metrics.brier : null;
    const accuracy = metrics.accuracy != null ? metrics.accuracy : null;
    if (brier == null) return;
    const dot = brier < 0.15 ? "dot-green" : brier < 0.25 ? "dot-orange" : "dot-red";
    html += '<tr><td>' + (labels[sk] || sk) + '</td><td class="num">' + brier.toFixed(4) + '</td><td class="num">' + (accuracy !== null ? (accuracy * 100).toFixed(1) + '%' : '—') + '</td><td class="num">' + nMatches + ' <span class="' + dot + '">&#9679;</span></td></tr>';
  });
  return html + '</table>';
}

function renderOverviewStandings(standings) {
  if (!standings.length) return '<div class="dim">No matches played yet.</div>';
  const groups = {};
  standings.forEach(r => {
    if (!groups[r.group]) groups[r.group] = [];
    groups[r.group].push(r);
  });
  let html = '';
  Object.keys(groups).sort().forEach(letter => {
    const rows = groups[letter];
    html += '<details class="group-detail" open>' +
      '<summary class="gd-summary">Group ' + letter + ' &middot; ' + rows.filter(r => r.played > 0).length + ' teams</summary>' +
      '<table class="group-table"><tr><th>#</th><th>Team</th><th>Pts</th><th>GD</th><th>GS</th></tr>';
    rows.forEach(r => {
      const gd = r.gd > 0 ? '+' + r.gd : String(r.gd);
      html += '<tr><td class="num">' + r.position + '</td><td>' + r.team + '</td><td class="num">' + r.pts + '</td><td class="num">' + gd + '</td><td class="num">' + r.gs + '</td></tr>';
    });
    html += '</table></details>';
  });
  return html;
}

function renderOverviewSignals(signals) {
  if (!signals.length) return '<div class="dim">No signal data available.</div>';
  let html = '<table class="eval-table"><tr><th>Signal</th><th>Available</th><th>Last Updated</th></tr>';
  signals.forEach(s => {
    const dot = s.available ? 'dot-green' : 'dot-red';
    const status = s.available ? 'Yes' : 'No';
    const updated = s.last_updated ? new Date(s.last_updated).toLocaleString() : '—';
    html += '<tr><td>' + s.name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) + '</td><td class="num"><span class="' + dot + '">&#9679;</span> ' + status + '</td><td class="num" style="font-size:10px">' + updated + '</td></tr>';
  });
  return html + '</table>';
}

// ── Bracket (Phase 3: group accordion + knockout tree via shared renderer) ──

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Map a knockout_tree node onto the shared renderer's match shape.
function _mapWcMatch(m, simById) {
  const isPlayed = !!(m.played || m.winner);
  const simM = (!isPlayed && simById[m.match_id]) ? simById[m.match_id] : null;

  // Score string: real result > sim projection (marked) > placeholder.
  let resultLine;
  if (m.score) {
    resultLine = m.score.home + "-" + m.score.away;
  } else if (m.winner) {
    // Real result with unrecorded scorelines: show the fact (winner)
    // without inventing a numeric score.
    resultLine = "—";
  } else if (simM && simM.predicted_score) {
    resultLine = "SIM " + simM.predicted_score.home + "-" + simM.predicted_score.away;
  } else {
    resultLine = "?-?";
  }

  let status;
  if (isPlayed) status = "played";
  else if (!m.team_a && !m.team_b) status = "tbd";
  else status = "scheduled";

  const canWhatIf = !!(m.team_a && m.team_b);

  return {
    id: m.match_id,
    parents: (Array.isArray(m.source_matches) && m.source_matches.length)
      ? m.source_matches.slice() : null,
    teamA: m.team_a || null,
    teamB: m.team_b || null,
    status,
    provenance: m.provenance || "official",
    winner: m.winner || null,
    resultLine,
    detailHtml: m.round === "TPP"
      ? _esc("Third-place play-off: losers of the two semi-finals.")
      : null,
    sim: (simM && simM.prob_a != null)
      ? { line: null, probA: simM.prob_a }
      : null,
    clickable: true,
    _canWhatIf: canWhatIf,
  };
}

function renderBracket() {
  const tab = document.getElementById("tab-bracket");
  if (!tab) return;
  const bd = appState.bracketData;
  if (!bd) {
    tab.innerHTML = '<div class="dim" style="padding:20px">Bracket data not available yet.</div>';
    return;
  }

  const rounds = bd.chronological_rounds || [];
  const koTree = bd.knockout_tree || {};

  // Split into group rounds and KO rounds
  const groupRounds = rounds.filter(r => r.round_type === 'group');

  let html = '';

  const nUnplayed = (appState.data && appState.data.n_unplayed != null) ? appState.data.n_unplayed : null;
  const seasonComplete = nUnplayed === 0
    || !!(appState.data && appState.data.phase && appState.data.phase.completed);
    if (seasonComplete) {
      html += '<div class="dim" style="text-align:right;margin-bottom:8px;font-size:11px">All competition results are already known from real match data. Simulation is not needed.</div>';
    } else {
      html += '<div style="text-align:right;margin-bottom:8px"><button class="status-btn" onclick="window.__simulateAllRemaining()">&#9654; Simulate All Remaining Matches</button></div>';
    }

  // Truth banners (Exchange 4): simulation provenance + not-requested state.
  if (appState.simMeta && appState.simMeta.status === "completed") {
    const m = appState.simMeta;
    html += '<div class="chart-section" style="border:1px solid rgba(142,68,173,.5)">'
      + '<div class="title">SIMULATION &middot; ' + (m.count || 0).toLocaleString() + ' RUNS'
      + ' &middot; seed ' + (m.seed != null ? m.seed : 'auto') + '</div>'
      + '<div class="dim" style="font-size:11px;padding:2px 8px">Projected probability (aggregate over '
      +   (m.count || 0).toLocaleString() + ' runs) - real played results above are unchanged.</div>'
      + '<div class="dim" style="font-size:11px;padding:2px 8px">Knockout card annotations show one example simulated bracket (sampled run).</div></div>';
  } else if (!seasonComplete) {
    html += '<div class="dim" style="padding:2px 4px;font-size:11px;margin-bottom:6px">Unplayed matches are shown as scheduled. Run a simulation to project their outcomes.</div>';
  }

  // Section 1: Group Stage Accordion
  html += '<div class="chart-section"><div class="title">Group Stage</div><div class="md-accordion">';
  groupRounds.forEach((r, ri) => {
    const isFirst = ri === 0;
    const nPlayed = r.matches.filter(m => m.played).length;
    const nTotal = r.matches.length;
    html += '<div class="md-card"><div class="md-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">' +
      '<span class="md-label">' + r.round_name + '</span><span class="md-count">' + nPlayed + '/' + nTotal + ' played</span>' +
      '<span class="md-arrow">' + (isFirst ? '\u25BC' : '\u25B6') + '</span></div>' +
      '<div class="md-body ' + (isFirst ? 'open' : '') + '">' +
      r.matches.map(m => renderMatchRow(m)).join('') +
      '</div></div>';
  });
  html += '</div></div>';

  // Section 2: Knockout Tree (shared renderer host)
  html += '<div class="chart-section"><div class="title">Knockout Stage</div>';
  html += '<div id="koTreeHost"></div></div>';

  tab.innerHTML = html;

  const host = document.getElementById('koTreeHost');
  if (!host) return;

  // Sim match lookup for the unplayed-match projection overlay
  const simById = {};
  if (appState.simBracket && appState.simBracket.rounds) {
    for (const [, ms] of Object.entries(appState.simBracket.rounds)) {
      for (const sm of ms) simById[sm.match_id] = sm;
    }
  }

  // Stage order and col-head labels preserved exactly from the previous
  // tree build; TPP stays between SF and FINAL as its own list column so
  // connector semantics are unchanged (SF -> TPP drawn; FINAL has no direct
  // incoming lines from SF, matching prior behaviour).
  const stageDefs = [
    { key: 'R32', label: 'Round of 32', layout: 'tree' },
    { key: 'R16', label: 'Round of 16', layout: 'tree' },
    { key: 'QF', label: 'Quarter-Finals', layout: 'tree' },
    { key: 'SF', label: 'Semi-Finals', layout: 'tree' },
    { key: 'TPP', label: 'Third Place', layout: 'list' },
    { key: 'FINAL', label: 'Final', layout: 'tree' },
  ];
  const bracketState = {
    stages: stageDefs.map(d => ({
      id: d.key,
      label: d.label,
      layout: d.layout,
      matches: (koTree[d.key] || []).map(m => _mapWcMatch(m, simById)),
    })),
  };

  renderBracketTree(host, bracketState, {
    cardThemeClass: "",
    columnFlex: (_st, i, n) => String(i === n - 1 ? 1.5 : 1),
    simLabel: "SIM",
    onMatch: m => openMatchModal(m.id),
    winnerLabel: m => (m.winner ? _esc(m.winner) + " advances" : null),
    cardExtrasHtml: m => {
      if (!m._canWhatIf) return "";
      const safeMid = String(m.id).replace(/[^A-Za-z0-9_.:-]/g, "");
      return '<div class="m-sim-btn" onclick="event.stopPropagation();window.__openWhatIf(\'' + safeMid + '\')">&#9654; What-If</div>';
    },
  });
}

function renderMatchRow(m) {
  const scoreStr = (m.home_score != null && m.away_score != null) ? (m.home_score + '-' + m.away_score) : (m.played ? '?' : '—');
  const status = m.played
    ? '<span class="dot-green">&#9679;</span> <span class="dim">Played</span>'
    : '<span class="dot-orange">&#9679;</span> TBD';
  return '<div class="md-row"><span class="md-team">' + m.team_a + '</span><span class="md-score">' + scoreStr + '</span><span class="md-team">' + m.team_b + '</span><span class="md-date">' + status + '</span></div>';
}

// ── Bracket controls ──
// Tournament simulation (whole-competition Monte Carlo) stays a separate,
// truthfully labeled control. The per-card button is a MATCH-level What-If
// (see openMatchModal / __sendWhatIf) — the two concepts are never merged.
window.__simulateAllRemaining = function() {
  showSimPopup();
};

window.__openWhatIf = function(matchId) {
  openMatchModal(matchId);
};


// ── Match Insight Modal ──
async function openMatchModal(mid) {
  let match = null;
  const fb = appState.fullBracket;
  const bd = appState.bracketData;
  if (fb && fb.rounds) {
    for (const [, ms] of Object.entries(fb.rounds)) {
      const found = ms.find(m => m.match_id === mid);
      if (found) { match = found; break; }
    }
  }
  if (!match && bd && bd.knockout_tree) {
    for (const [, ms] of Object.entries(bd.knockout_tree)) {
      const found = ms.find(m => m.match_id === mid);
      if (found) { match = found; break; }
    }
  }
  if (!match) return;

  destroyModalCharts();
  document.getElementById("modalTitle").innerHTML = (match.team_a || "TBD") + ' <span style="color:#15565B;font-weight:normal">vs</span> ' + (match.team_b || "TBD");
  document.getElementById("modalSub").textContent = match.round + " — " + match.match_id + (match.score ? "  |  " + match.score.home + "-" + match.score.away : "");
  document.getElementById("modalBody").innerHTML = '<div class="mb-wrap"><div class="mb-col" id="mbLeft"></div><div class="mb-col" id="mbRight"></div></div><div id="modalBottom"></div>';

  const bodyEl = document.getElementById("modalBody");
  const left = document.getElementById("mbLeft");
  const right = document.getElementById("mbRight");
  const bottom = document.getElementById("modalBottom");
  document.getElementById("modalOverlay").classList.add("show");

  let insight;
  try { insight = await (await fetch(API + "/match/insight?match_id=" + mid)).json(); } catch { insight = { error: "fetch failed" }; }
  if (insight.error) {
    bodyEl.innerHTML = '<div style="color:#ff6b6b;font-size:12px">Failed to load match insight.</div>';
    return;
  }

  const ta = insight.teams.a, tb = insight.teams.b;
  const sigs = insight.signals || {};
  const sigOrder = ["elo", "market_odds", "rolling_form", "squad_value", "rest_days"];
  const ev = appState.eval || {};
  const outcome = insight.outcome_distribution || {};
  const ft = insight.form_trends || {};

  left.innerHTML = `
    <div class="sec-title">Form Trend (last 5)</div><div class="form-charts">
      ${[ta, tb].map(team => '<div class="form-chart-box"><div class="fc-label">' + team + '</div><canvas id="fc-' + team.replace(/\s/g, "") + '"></canvas></div>').join("")}
    </div>
    <div class="sec-title">Signal Comparison</div><div class="chart-box"><canvas id="sigChart"></canvas></div>
    <div class="sec-title">Outcome Distribution</div><div class="outcome-charts">
      <div class="outcome-chart-box"><canvas id="outcomeChart"></canvas></div>
    </div>
  `;

  right.innerHTML = `
    <div class="sec-title">Signal Performance</div>
    <table class="insight-table"><tr><th>Signal</th><th>Brier</th><th>Acc</th><th></th></tr>
    ${sigOrder.map(sk => {
      const se = ev[sk];
      if (se && se.n_matches > 0) {
        const dot = se.brier < 0.15 ? "dot-green" : se.brier < 0.25 ? "dot-orange" : "dot-red";
        return '<tr><td>' + (sigLabels[sk] || sk) + '</td><td class="num">' + se.brier.toFixed(4) + '</td><td class="num">' + (se.accuracy * 100).toFixed(1) + '%</td><td class="num"><span class="' + dot + '">&#9679;</span></td></tr>';
      }
      return "";
    }).join("")}
    </table>
    <div class="sec-title">Match Insight</div>
    <div class="insight-box">${insight.insight || "No insight available."}</div>
  `;

  bottom.innerHTML =
    '<div class="sec-title warn">Match What-If</div>' +
    '<div class="whatif-controls">' +
    '<label>Elo boost for ' + _esc(ta) + ' (opponent lowered equally):</label>' +
    '<input type="number" id="whatifDelta" value="50" step="10" min="-600" max="600" style="width:80px;background:#0d2430;color:#F6DBC0;border:1px solid rgba(21,61,76,.4);border-radius:4px;padding:4px 6px;font-size:11px">' +
    '<button class="status-btn" id="whatifRun">&#9654; Run What-If</button>' +
    '</div>' +
    '<div class="dim" style="padding:2px 0;font-size:10px">Re-evaluates this match only via the ensemble blend. Factual history unchanged.</div>' +
    '<div class="whatif-result" id="whatifResult"></div>';
  const runBtn = document.getElementById("whatifRun");
  if (runBtn) runBtn.addEventListener("click", () => window.__sendWhatIf(mid, ta, tb));

  // Charts
  [ta, tb].forEach(team => {
    const tr = ft[team] || [];
    const canvas = document.getElementById("fc-" + team.replace(/\s/g, ""));
    if (!canvas) return;
    const labels = tr.map((r, i) => "M" + (i + 1));
    const vals = tr.map(r => r.result === "W" ? 1 : r.result === "D" ? 0.5 : 0);
    modalCharts["form_" + team] = new Chart(canvas, {
      type: "line",
      data: { labels, datasets: [{ data: vals, borderColor: "#16A085", backgroundColor: "transparent", pointBackgroundColor: "#16A085", borderWidth: 2, tension: 0.3, pointRadius: 3 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { min: -0.1, max: 1.1, display: false } } }
    });
  });

  const sigCanvas = document.getElementById("sigChart");
  if (sigCanvas) {
    const sigKeys = sigOrder.filter(sk => sigs[sk] !== undefined);
    const sigVals = sigKeys.map(sk => Math.round((sigs[sk].probability != null ? sigs[sk].probability : 0) * 100));
    const sigColors = sigKeys.map(sk => sk === "elo" ? "#16A085" : "#156F69");
    modalCharts.signals = new Chart(sigCanvas, {
      type: "bar",
      data: { labels: sigKeys.map(sk => sigLabels[sk] || sk), datasets: [{ data: sigVals, backgroundColor: sigColors, borderRadius: 2, borderSkipped: false }] },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: "y",
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.x + "%" } } },
        scales: { x: { min: 0, max: 100, grid: { color: "rgba(21,61,76,0.2)" }, ticks: { color: "#15565B", font: { size: 9 }, callback: v => v + "%" } }, y: { grid: { display: false }, ticks: { color: "#F6DBC0", font: { size: 9 } } } }
      }
    });
  }

  // Render the doughnut only from a real distribution; never fabricate
  // slices when outcome data is absent.
  const ocCanvas = document.getElementById("outcomeChart");
  if (ocCanvas && typeof insight.outcome_distribution === "object" &&
      typeof outcome.a_win === "number" &&
      typeof outcome.draw === "number" &&
      typeof outcome.b_win === "number") {
    modalCharts.outcome = new Chart(ocCanvas, {
      type: "doughnut",
      data: { labels: [ta + " win", "Draw", tb + " win"], datasets: [{ data: [outcome.a_win, outcome.draw, outcome.b_win], backgroundColor: ["#16A085", "#156F69", "#153D4C"], borderColor: "#140C30", borderWidth: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { color: "#F6DBC0", font: { size: 9 }, boxWidth: 10, padding: 6 } }, tooltip: { callbacks: { label: ctx => ctx.label + ": " + (ctx.parsed * 100).toFixed(1) + "%" } } },
        cutout: "55%"
      }
    });
  }
}

// ── Match What-If handler (exposed on window for the modal) ──
// True match/tie-level What-If: POST /worldcup/api/match/what-if re-evaluates
// the single-match ensemble blend with a hypothetical Elo adjustment. This is
// NOT the tournament Monte Carlo — that lives only in "Simulate All Remaining
// Matches" / the Simulate Tournament popup.
window.__sendWhatIf = async function (mid, ta, tb) {
  const deltaInput = document.getElementById("whatifDelta");
  const resultDiv = document.getElementById("whatifResult");
  if (!deltaInput || !resultDiv) return;
  let eloDelta = parseInt(deltaInput.value, 10);
  if (!Number.isFinite(eloDelta)) eloDelta = 50;
  eloDelta = Math.max(-600, Math.min(600, eloDelta));
  const runBtn = document.getElementById("whatifRun");
  if (runBtn) runBtn.disabled = true;
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<div style="color:#15565B;font-size:11px">Running match what-if...</div>';
  try {
    const resp = await (await fetch(API + "/match/what-if", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: mid, elo_delta: eloDelta })
    })).json();
    if (resp.error) { resultDiv.innerHTML = '<div style="color:#ff6b6b">' + resp.error + "</div>"; return; }
    const row = (name) => {
      const t = resp.teams[name] || {};
      const d = t.delta || 0;
      const cls = d >= 0 ? "wir-diff-pos" : "wir-diff-neg";
      return '<tr><td>' + _esc(name) + '</td><td class="num">' + ((t.baseline||0)*100).toFixed(1) + '%</td><td class="num">' + ((t.adjusted||0)*100).toFixed(1) + '%</td><td class="num ' + cls + '">' + (d>=0?"+":"") + (d*100).toFixed(1) + ' pp</td></tr>';
    };
    let html = '<div class="wir-head">WHAT-IF (SIMULATED) - win probability for this match, baseline vs adjusted</div>';
    html += '<table class="wi-table"><tr><th>Team</th><th>Baseline</th><th>Adjusted</th><th>Delta (pp)</th></tr>';
    html += row(ta);
    html += row(tb);
    html += "</table>";
    const ob = resp.outcome_baseline || {}, oa = resp.outcome_adjusted || {};
    if (typeof ob.draw === "number") {
      html += '<div class="wir-meta">Draw probability: baseline ' + (ob.draw*100).toFixed(1) + '% &rarr; adjusted ' + ((oa.draw||0)*100).toFixed(1) + '%.</div>';
    }
    html += '<div class="wir-meta">SIMULATED - deterministic ensemble blend, Elo ' + (eloDelta >= 0 ? "+" : "") + eloDelta + ' / ' + (-eloDelta) + '. No tournament simulation ran. Factual history unchanged.</div>';
    resultDiv.innerHTML = html;
  } catch (e) {
    resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + "</div>";
  } finally {
    const b2 = document.getElementById("whatifRun");
    if (b2) b2.disabled = false;
  }
};

// ── Standings ──
function renderStandings() {
  const tab = document.getElementById("tab-standings");
  if (!tab) return;
  const s = appState.standings;
  if (!s) { tab.innerHTML = '<div class="dim" style="padding:20px">Standings data not available yet.</div>'; return; }
  // Handle both old format {standings: {A: [...]}} and new flat list [{}]
  let groups = {};
  if (s.standings && !Array.isArray(s.standings)) {
    // Legacy format
    groups = s.standings;
  } else {
    // New flat format — group by letter
    const list = Array.isArray(s) ? s : (s.standings || []);
    list.forEach(r => {
      const g = r.group || '?';
      if (!groups[g]) groups[g] = [];
      groups[g].push(r);
    });
  }
  const letters = Object.keys(groups).sort();
  if (!letters.length) { tab.innerHTML = '<div class="dim" style="padding:20px">No standings data.</div>'; return; }

  tab.innerHTML = `
    <div class="standings-grid" id="standingsGrid">
      ${letters.map(letter => {
        const rows = groups[letter];
        const positions = rows.map(r => r.position);
        const maxPos = Math.max(...positions);
        return '<div class="group-card"><div class="g-title">Group ' + letter + '</div>' +
          '<table class="group-table"><tr><th>#</th><th>Team</th><th>Pts</th><th>GD</th><th>GS</th></tr>' +
          rows.map(r => {
            const cls = r.position <= 2 ? "advancing" : r.position === maxPos ? "eliminated" : "bubble";
            const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
            return '<tr class="' + cls + '"><td class="num">' + r.position + '</td><td>' + r.team + '</td><td class="num">' + r.pts + '</td><td class="num">' + gd + '</td><td class="num">' + r.gs + '</td></tr>';
          }).join("") + "</table></div>";
      }).join("")}
    </div>
  `;
}




