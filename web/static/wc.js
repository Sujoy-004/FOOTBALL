// ── World Cup 2026 Module ──
import {
  termAdd, termScroll, termShowPrompt, termRenderBootStep, termBooting,
  wireTerminal, buildTable, destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions, termRunSimulation, termRunCalibration,
  renderSparkline, termRunWithSpinner,
} from "./shared.js";

const API = "/worldcup/api";
const sigLabels = { elo: "Elo", form: "Form", lineup_strength: "Lineup", defensive_quality: "Defense", manager_effect: "Manager", market_odds: "Odds", catboost: "CatBoost" };
const appState = { data: null, overview: null, standings: null, bracket: null, fullBracket: null, eval: null, blend: null, signalCache: {} };
let refreshing = false;
let autoRefreshOn = false;
let autoTimer = null;

export function init(comp) {
  // Terminal input
  wireTerminal(termExec);

  renderTerminalShell();
  loadAll();
  termBoot();
}

function renderTerminalShell() {
  const tab = document.getElementById("tab-terminal");
  if (!tab) return;
  tab.innerHTML = `
    <div class="term-output" id="termOutput"></div>
    <div class="term-input-line" id="termInputLine" style="display:none">
      <span class="prompt"></span><span class="term-input-display" id="termInputDisplay"></span><span class="term-cursor">&#9608;</span>
    </div>
  `;
}

async function loadAll() {
  const ov = await fetch(API + "/overview").then(r => r.json());
  appState.overview = ov;
  appState.data = ov;
  renderOverview();
  updateStatus();
  // Standings tab
  try {
    const s = await fetch(API + "/standings").then(r => r.json());
    appState.standings = s;
    renderStandings();
  } catch {}
  // Bracket tab — full bracket data (chronological + knockout tree)
  try {
    const br = await fetch(API + "/bracket").then(r => r.json());
    appState.bracket = br;
  } catch {}
  try {
    const bd = await fetch(API + "/bracket/data").then(r => r.json());
    appState.bracketData = bd;
  } catch {}
  try {
    const fb = await fetch(API + "/bracket/full").then(r => r.json());
    appState.fullBracket = fb;
  } catch {}
  renderBracket();
}

function updateStatus() {
  const d = appState.data;
  if (!d) return;
  if (refreshing) return;
  const signals = d.signals_meta?.signals || [];
  const nActive = signals.filter(s => s.available).length;
  const hasSim = (d.top_teams || []).length > 0;
  const btn = '<button class="status-btn" onclick="window.__refreshWC()">>> ' + (hasSim ? 'Re-Simulate' : 'Refresh & Simulate') + '</button>';
  updateStatusBar(
    ">> " + d.n_teams + " teams  |  " + d.n_played + " matches played  |  " + nActive + " active signals",
    btn + (autoRefreshOn ? '  <span style="color:#168777;font-size:10px">auto</span>' : "")
  );
}

window.__refreshWC = showSimPopup;

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
        <input type="number" id="simCustomIters" value="50000" min="1000" max="500000">
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

          if (p.status === "complete") {
            clearInterval(poll);
            resolve();
          }
          if (p.status === "error") {
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
    await loadAll();
    const btn = '<button class="status-btn" onclick="window.__refreshWC()">>> Refresh & Simulate</button>';
    updateStatusBar('<span style="color:#168777">Simulation complete (' + iters.toLocaleString() + ' iters)</span>', btn);
  } catch (e) {
    progressLbl.textContent = "Error: " + (e.message || "unknown");
    startBtn.disabled = false;
    cancelBtn.style.display = "";
  }
  refreshing = false;
}
window.__refreshWC = showSimPopup;

// ── Overview (pre- and post-simulation) ──
function renderOverview() {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const ov = appState.overview || appState.data;
  if (!ov) return;

  const signals = ov.signals_meta?.signals || [];
  const nActive = signals.filter(s => s.available).length;
  const topTeams = ov.top_teams || [];
  const hasSim = topTeams.length > 0;
  const signalEval = ov.signal_eval || {};

  let html = '';

  // Stat cards (always)
  html += '<div class="stats-row" id="statsRow">';
  if (hasSim) {
    const simMeta = ov.simulation_meta || {};
    html += '<div class="stat-card"><div class="val">' + ov.n_teams + '</div><div class="lbl">Teams</div></div>';
    html += '<div class="stat-card"><div class="val">' + ov.n_played + '</div><div class="lbl">Matches Played</div></div>';
    html += '<div class="stat-card"><div class="val">' + nActive + '/' + signals.length + '</div><div class="lbl">Signals</div></div>';
    html += '<div class="stat-card"><div class="val">' + (simMeta.iterations || 0).toLocaleString() + '</div><div class="lbl">Simulations Run</div></div>';
  } else {
    html += '<div class="stat-card"><div class="val">' + ov.n_teams + '</div><div class="lbl">Teams</div></div>';
    html += '<div class="stat-card"><div class="val">' + ov.n_played + '</div><div class="lbl">Matches Played</div></div>';
    html += '<div class="stat-card"><div class="val">' + nActive + ' / ' + signals.length + '</div><div class="lbl">Signals Available</div></div>';
  }
  html += '</div>';

  // Post-sim: champion probability bar chart
  if (hasSim) {
    html += '<div class="chart-section">';
    html += '<div class="title">Champion Probability (Top 10)</div>';
    html += '<div class="champ-chart" id="champChart">';
    topTeams.slice(0, 10).forEach(t => {
      const pct = (t.champion * 100).toFixed(1);
      const barW = Math.max(2, pct * 3);
      html += '<div class="champ-bar-row"><div class="cname">' + t.name + '</div><div class="cbar-wrap"><div class="cbar" style="width:' + barW + 'px"></div></div><div class="cpct">' + pct + '%</div></div>';
    });
    html += '</div></div>';

    // Post-sim: top 4 team cards with ring charts
    html += '<div class="chart-section">';
    html += '<div class="title">Top 4 Teams</div>';
    html += '<div class="team-cards" id="topTeamCards">';
    topTeams.slice(0, 4).forEach(t => {
      const champ = (t.champion * 100).toFixed(1);
      const final = (t.final * 100).toFixed(1);
      const sf = (t.sf * 100).toFixed(1);
      const qf = (t.qf * 100).toFixed(1);
      html += '<div class="team-card"><div class="name">' + t.name + '</div>';
      html += '<div class="team-ring-row">';
      html += '<div class="team-ring-item"><div class="trl">CH</div><div class="trv">' + champ + '%</div><div class="tr-bar"><div class="tr-fill" style="width:' + Math.min(100, champ * 2) + '%"></div></div></div>';
      html += '<div class="team-ring-item"><div class="trl">F</div><div class="trv">' + final + '%</div><div class="tr-bar"><div class="tr-fill" style="width:' + Math.min(100, final) + '%"></div></div></div>';
      html += '<div class="team-ring-item"><div class="trl">SF</div><div class="trv">' + sf + '%</div><div class="tr-bar"><div class="tr-fill" style="width:' + Math.min(100, sf) + '%"></div></div></div>';
      html += '<div class="team-ring-item"><div class="trl">QF</div><div class="trv">' + qf + '%</div><div class="tr-bar"><div class="tr-fill" style="width:' + Math.min(100, qf) + '%"></div></div></div>';
      html += '</div></div>';
    });
    html += '</div></div>';
  }

  // Group standings (always)
  html += '<div class="chart-section">';
  html += '<div class="title">Group Standings</div>';
  html += '<div class="overview-standings" id="ovStandings">';
  html += renderOverviewStandings(ov.standings || []);
  html += '</div></div>';

  // Post-sim: signal evaluation table
  if (hasSim && Object.keys(signalEval).length > 0) {
    html += '<div class="chart-section">';
    html += '<div class="title">Signal Accuracy</div>';
    html += renderSignalEval(signalEval);
    html += '</div>';
  }

  // Signals metadata (always — or only when no sim data)
  if (!hasSim || signals.length > 0) {
    html += '<div class="chart-section">';
    html += '<div class="title">' + (hasSim ? 'Signal Cache Status' : 'Signals Data') + '</div>';
    html += '<div class="overview-signals" id="ovSignals">';
    html += renderOverviewSignals(signals);
    html += '</div></div>';
  }

  tab.innerHTML = html;
}

function renderSignalEval(signalEval) {
  const sigOrder = ["elo", "all_signals", "form", "lineup_strength", "defensive_quality", "manager_effect", "market_odds", "catboost"];
  const labels = { elo: "Elo", all_signals: "Blended", form: "Form", lineup_strength: "Lineup", defensive_quality: "Defense", manager_effect: "Manager", market_odds: "Odds", catboost: "CatBoost" };
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

// ── Bracket (Phase 3: group accordion + knockout tree) ──
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
  window.__bracketData = koTree;

  // Split into group rounds and KO rounds
  const groupRounds = rounds.filter(r => r.round_type === 'group');
  const koRounds = rounds.filter(r => r.round_type !== 'group');

  const koTreeRounds = ['R32', 'R16', 'QF', 'SF', 'TPP', 'FINAL'];
  const koRoundLabels = { R32: 'Round of 32', R16: 'Round of 16', QF: 'Quarter-Finals', SF: 'Semi-Finals', TPP: 'Third Place', FINAL: 'Final' };

  let html = '';

  // Simulate All Remaining button
  const hasUnplayed = [...groupRounds, ...koRounds].some(r => r.matches.some(m => !m.played));
  if (hasUnplayed) {
    html += '<div style="text-align:right;margin-bottom:8px"><button class="status-btn" onclick="window.__simulateAllRemaining()">&#9654; Simulate All Remaining</button></div>';
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

  // Section 2: Knockout Tree (UCL-style)
  html += '<div class="chart-section"><div class="title">Knockout Stage</div>';
  html += '<div class="bracket-wrap"><div class="bracket-grid" id="bracketGrid"></div><svg class="bracket-svg" id="bracketSvg"></svg></div></div>';

  tab.innerHTML = html;

  // Build the knockout tree from koTree data
  const grid = document.getElementById('bracketGrid');
  if (!grid) return;

  // Flatten all KO matches into byId
  const byId = {};
  for (const [, ms] of Object.entries(koTree)) for (const m of ms) byId[m.match_id] = m;

  function getLeafOrder(mid) {
    const m = byId[mid];
    if (!m || !m.source_matches) return [mid];
    return [...getLeafOrder(m.source_matches[0]), ...getLeafOrder(m.source_matches[1])];
  }

  const leafOrder = [];
  const leafMatches = koTree.R32 || [];
  for (const m of leafMatches) leafOrder.push(m.match_id);
  const leafIdx = {};
  leafOrder.forEach((id, i) => leafIdx[id] = i);

  function getRowRange(mid) {
    const m = byId[mid];
    if (!m) return { start: 0, end: leafOrder.length };
    if (['FINAL', 'TPP'].includes(m.round)) return { start: 0, end: leafOrder.length };
    if (!m.source_matches) return { start: leafIdx[mid] || 0, end: (leafIdx[mid] || 0) + 1 };
    const leaves = getLeafOrder(mid);
    if (!leaves.length) return { start: 0, end: 2 };
    return { start: leafIdx[leaves[0]] || 0, end: (leafIdx[leaves[leaves.length - 1]] || 0) + 1 };
  }

  const ROW_UNIT = 28;
  const roundOrder = ['R32', 'R16', 'QF', 'SF', 'TPP', 'FINAL'];
  roundOrder.forEach((r, ri) => {
    const col = document.createElement('div');
    col.className = 'bracket-col';
    col.style.flex = String(1 + (ri === roundOrder.length - 1 ? 0.5 : 0));
    col.innerHTML = '<div class="col-head">' + (koRoundLabels[r] || r) + '</div>';

    const ms = (koTree[r] || []).slice().sort((a, b) => getRowRange(a.match_id).start - getRowRange(b.match_id).start);
    let lastEnd = 0;
    ms.forEach(m => {
      const rr = getRowRange(m.match_id);
      const gap = rr.start - lastEnd;
      if (gap > 0) {
        const sp = document.createElement('div');
        sp.className = 'match-slot';
        sp.style.minHeight = (gap * ROW_UNIT) + 'px';
        col.appendChild(sp);
      }
      lastEnd = rr.end;

      const slot = document.createElement('div');
      slot.className = 'match-slot';
      slot.style.minHeight = Math.max((rr.end - rr.start) * ROW_UNIT, 40) + 'px';

      const ta = m.team_a || 'TBD';
      const tb = m.team_b || 'TBD';
      const scoreStr = m.score ? m.score.home + '-' + m.score.away : (m.winner ? '1-0' : '?-?');
      const isPlayed = m.played || !!m.winner;
      const isTbd = (!m.team_a && !m.team_b) || (!m.played && !m.winner);
      const cardClass = isTbd ? 'tbd' : isPlayed ? 'played' : 'upcoming';

      let cardHtml = '<div class="match-card ' + cardClass + '" data-mid="' + m.match_id + '">' +
        '<div class="m-teams"><span class="m-team ' + (m.winner === ta ? 'winner' : '') + '">' + ta + '</span>' +
        '<span class="m-score">' + scoreStr + '</span>' +
        '<span class="m-team ' + (m.winner === tb ? 'winner' : '') + '">' + tb + '</span></div>' +
        (m.winner ? '<div class="m-winner-label">' + m.winner + ' advances</div>' : '');

      // Show Simulate button for unplayed matches
      if (!m.played && m.team_a) {
        cardHtml += '<div class="m-sim-btn" onclick="event.stopPropagation();window.__simulateMatch(\'' + m.match_id + '\')">&#9654; Simulate</div>';
      }
      cardHtml += '</div>';

      slot.innerHTML = cardHtml;
      slot.querySelector('.match-card').onclick = () => openMatchModal(m.match_id);
      col.appendChild(slot);
    });
    grid.appendChild(col);
  });

  setTimeout(drawBracketConnectors, 50);
}

function renderMatchRow(m) {
  const scoreStr = m.winner ? (m.home_score + '-' + m.away_score) : (m.played ? '?' : '—');
  const status = m.played
    ? '<span class="dot-green">&#9679;</span> <span class="dim">Played</span>'
    : '<span class="dot-orange">&#9679;</span> TBD';
  return '<div class="md-row"><span class="md-team">' + m.team_a + '</span><span class="md-score">' + scoreStr + '</span><span class="md-team">' + m.team_b + '</span><span class="md-date">' + status + '</span></div>';
}

// ── Match Simulation from bracket ──
let simMatchId = null;

window.__simulateAllRemaining = function() {
  simMatchId = '__all__';
  showMatchSimPopup('Simulate All Remaining Matches');
};

window.__simulateMatch = function(matchId) {
  simMatchId = matchId;
  showMatchSimPopup('Simulate Match ' + matchId);
};

function showMatchSimPopup(title) {
  let overlay = document.getElementById('matchSimOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'matchSimOverlay';
    overlay.className = 'sim-popup-overlay';
    overlay.innerHTML = `
      <div class="sim-popup" style="max-width:400px">
        <h3 id="matchSimTitle">Simulate Match</h3>
        <p>Number of Monte Carlo iterations:</p>
        <div class="sim-presets">
          <button data-iters="5000">5K</button>
          <button data-iters="10000" class="active">10K</button>
          <button data-iters="50000">50K</button>
        </div>
        <input type="number" id="matchSimIters" value="10000" min="1000" max="100000">
        <div class="sim-actions">
          <button id="matchSimCancelBtn">Cancel</button>
          <button id="matchSimStartBtn">&#9654; Start</button>
        </div>
        <div id="matchSimProgress" class="progress-bar-wrap" style="display:none;margin-top:10px">
          <div class="progress-bar-fill" id="matchSimProgressFill" style="width:0%"></div>
        </div>
        <div id="matchSimResult" style="display:none;margin-top:10px;font-size:11px"></div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelectorAll('.sim-presets button').forEach(btn => {
      btn.addEventListener('click', () => {
        overlay.querySelectorAll('.sim-presets button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('matchSimIters').value = btn.dataset.iters;
      });
    });
    document.getElementById('matchSimCancelBtn').addEventListener('click', () => overlay.classList.remove('show'));
    document.getElementById('matchSimStartBtn').addEventListener('click', startMatchSim);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.classList.remove('show'); });
  }
  document.getElementById('matchSimTitle').textContent = title;
  document.getElementById('matchSimResult').style.display = 'none';
  overlay.classList.add('show');
}

async function startMatchSim() {
  const iters = parseInt(document.getElementById('matchSimIters').value) || 10000;
  const startBtn = document.getElementById('matchSimStartBtn');
  const cancelBtn = document.getElementById('matchSimCancelBtn');
  const progressWrap = document.getElementById('matchSimProgress');
  const progressFill = document.getElementById('matchSimProgressFill');
  const resultDiv = document.getElementById('matchSimResult');

  startBtn.disabled = true;
  cancelBtn.style.display = 'none';
  progressWrap.style.display = 'block';
  progressFill.style.width = '0%';
  resultDiv.style.display = 'none';

  try {
    if (simMatchId === '__all__') {
      // Full tournament simulation
      const startBtn2 = document.getElementById('simStartBtn');
      if (startBtn2) {
        document.getElementById('matchSimOverlay').classList.remove('show');
        document.getElementById('simCustomIters').value = iters;
        startSimulation();
      } else {
        // Fallback: call POST /api/simulate
        const resp = await (await fetch(API + '/simulate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ iterations: iters })
        })).json();
        const taskId = resp.task_id;
        await new Promise((resolve, reject) => {
          const poll = setInterval(async () => {
            const p = await (await fetch(API + '/simulation/progress/' + taskId)).json();
            if (p.status === 'complete') { clearInterval(poll); resolve(); }
            if (p.status === 'error') { clearInterval(poll); reject(new Error(p.error)); }
            progressFill.style.width = p.progress + '%';
          }, 200);
        });
        await loadAll();
        document.getElementById('matchSimOverlay').classList.remove('show');
      }
      return;
    }

    // Single match simulation
    const resp = await (await fetch(API + '/simulate-from-match', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ match_id: simMatchId, iterations: iters })
    })).json();

    if (resp.error) {
      resultDiv.textContent = 'Error: ' + resp.error;
      resultDiv.style.display = 'block';
      startBtn.disabled = false;
      cancelBtn.style.display = '';
      return;
    }

    // Show predictions
    let resultHtml = '<div style="color:#168777;font-weight:bold;margin-bottom:6px">Simulation Complete</div>';
    if (resp.predictions && resp.predictions.length) {
      resultHtml += '<div style="margin-bottom:4px">Top contenders:</div>';
      resp.predictions.forEach(p => {
        const cp = (p.champion * 100).toFixed(1);
        const fn = (p.final * 100).toFixed(1);
        resultHtml += '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.05)">' +
          '<span>' + p.name + '</span><span style="color:#16A085">' + cp + '% champ, ' + fn + '% final</span></div>';
      });
    }
    if (resp.downstream && resp.downstream.length) {
      resultHtml += '<div style="margin-top:6px;font-size:10px;color:#15565B">' + resp.downstream.length + ' downstream matches simulated</div>';
    }
    resultDiv.innerHTML = resultHtml;
    resultDiv.style.display = 'block';
    progressFill.style.width = '100%';
    progressWrap.style.display = 'none';
  } catch (e) {
    resultDiv.textContent = 'Error: ' + (e.message || 'unknown');
    resultDiv.style.display = 'block';
  }
  startBtn.disabled = false;
  cancelBtn.style.display = '';
}

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
  const sigOrder = ["elo", "form", "lineup_strength", "defensive_quality", "manager_effect", "market_odds", "catboost"];
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

  bottom.innerHTML = `
    <div class="sec-title warn">What-If Scenario</div>
    <div class="whatif-input-wrap">
      <input type="text" id="whatifInput" placeholder="Describe a scenario... (e.g. Messi injured, defense weak)">
      <button onclick="window.__sendWhatIf('${mid}')">&#9654;</button>
    </div>
    <div class="whatif-controls">
      <label>Mode:</label><select id="whatifMode"><option value="instant">Instant</option><option value="simulate">Simulate</option></select>
      <label>Iterations:</label><select id="whatifIters"><option value="10000">10K</option><option value="50000" selected>50K</option><option value="100000">100K</option><option value="500000">500K</option></select>
    </div>
    <div class="progress-bar-wrap" id="whatifProgress"><div class="progress-bar-fill" id="whatifProgressFill" style="width:0%"></div></div>
    <div class="progress-lbl" id="whatifProgressLbl"></div>
    <div class="whatif-result" id="whatifResult"></div>
  `;

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
    const sigVals = sigKeys.map(sk => Math.round((sigs[sk].probability || 0.5) * 100));
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

  const ocCanvas = document.getElementById("outcomeChart");
  if (ocCanvas) {
    modalCharts.outcome = new Chart(ocCanvas, {
      type: "doughnut",
      data: { labels: [ta + " win", "Draw", tb + " win"], datasets: [{ data: [outcome.a_win || 0, outcome.draw || 0, outcome.b_win || 0], backgroundColor: ["#16A085", "#156F69", "#153D4C"], borderColor: "#140C30", borderWidth: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { color: "#F6DBC0", font: { size: 9 }, boxWidth: 10, padding: 6 } }, tooltip: { callbacks: { label: ctx => ctx.label + ": " + (ctx.parsed * 100).toFixed(1) + "%" } } },
        cutout: "55%"
      }
    });
  }
}

// ── What-If handler (exposed on window for onclick) ──
window.__sendWhatIf = async function (mid) {
  const input = document.getElementById("whatifInput");
  const scenario = input.value.trim();
  if (!scenario) return;
  const mode = document.getElementById("whatifMode").value;
  const iters = parseInt(document.getElementById("whatifIters").value) || 50000;
  const resultDiv = document.getElementById("whatifResult");
  const progressWrap = document.getElementById("whatifProgress");
  const progressFill = document.getElementById("whatifProgressFill");
  const progressLbl = document.getElementById("whatifProgressLbl");

  resultDiv.style.display = "none";
  resultDiv.innerHTML = "";

  if (mode === "instant") {
    try {
      const resp = await (await fetch(API + "/what-if", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: mid, scenario, mode: "instant" })
      })).json();

      resultDiv.style.display = "block";
      const insightText = resp.insight || "No analysis generated.";
      let html = '<div class="wir-insight">>> ' + insightText.replace(/ >> /g, "<br>>></div><div class=\"wir-insight\">>> ") + "</div>";

      if (resp.adjusted_signals) {
        let sigDetail = "";
        Object.entries(resp.adjusted_signals).forEach(([sk, sv]) => {
          if (sv.was_adjusted) {
            const deltaStr = (sv.delta * 100).toFixed(1);
            const cls = sv.delta >= 0 ? "wir-diff-pos" : "wir-diff-neg";
            sigDetail += '<div class="wir-sig-row"><span>' + (sigLabels[sk] || sk) + '</span><span class="wir-bar-wrap"><span class="wir-bar" style="width:' + (sv.probability * 100) + '%"></span></span><span class="wir-val">' + (sv.probability * 100).toFixed(1) + '%</span><span class="' + cls + '">' + (sv.delta >= 0 ? "+" : "") + deltaStr + '%</span></div>';
          }
        });
        if (sigDetail) {
          html += '<div class="wir-toggle" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">[+] Signal detail</div>';
          html += '<div class="wir-sigs" style="display:none">' + sigDetail + "</div>";
        }
      }
      if (resp.parsed && resp.parsed.explanation) {
        const conf = resp.parsed.confidence || 0;
        const confColor = conf >= 0.6 ? "#168777" : conf >= 0.3 ? "#15565B" : "#ff6b6b";
        html += '<div class="wir-meta"><span style="color:' + confColor + '">Detection confidence: ' + (conf * 100).toFixed(0) + "%</span> &middot; " + resp.parsed.explanation + "</div>";
      }
      resultDiv.innerHTML = html;
    } catch (e) {
      resultDiv.style.display = "block";
      resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + "</div>";
    }
  } else {
    progressWrap.style.display = "block";
    progressFill.style.width = "0%";
    progressLbl.textContent = "Starting simulation...";
    try {
      const resp = await (await fetch(API + "/what-if", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: mid, scenario, mode: "simulate", iterations: iters })
      })).json();
      if (resp.error) {
        progressWrap.style.display = "none";
        resultDiv.style.display = "block";
        resultDiv.innerHTML = '<div style="color:#ff6b6b">' + resp.error + "</div>";
        return;
      }
      const taskId = resp.task_id;
      let t0 = Date.now();
      let prevPct = 0;
      const pollInterval = setInterval(async () => {
        try {
          const prog = await (await fetch(API + "/simulation/progress/" + taskId)).json();
          if (prog.status === "running" || prog.status === "complete") {
            progressFill.style.width = prog.progress + "%";
            const comp = prog.iteration.toLocaleString();
            const total = prog.total_iterations.toLocaleString();
            const elapsed = ((Date.now() - t0) / 1000).toFixed(0);
            let eta = "";
            if (prog.progress > 2 && prog.progress < 98) {
              const rate = (prog.progress - prevPct) / 0.2;
              if (rate > 0) {
                const remain = ((100 - prog.progress) / rate).toFixed(0);
                eta = "  ETA " + remain + "s";
              }
            }
            prevPct = prog.progress;
            progressLbl.textContent = comp + " / " + total + "  (" + prog.progress.toFixed(1) + "%)  " + elapsed + "s" + eta;
          }
          if (prog.status === "complete") {
            clearInterval(pollInterval);
            progressFill.style.width = "100%";
            progressLbl.textContent = "Complete!";
            setTimeout(() => { progressWrap.style.display = "none"; }, 2000);
            resultDiv.style.display = "block";
            const simInsight = prog.insight || "Simulation complete.";
            let html = '<div class="wir-insight">>> ' + simInsight.replace(/ >> /g, "<br>>></div><div class=\"wir-insight\">>> ") + "</div>";
            const simResult = prog.result || {};
            const teamsList = Object.entries(simResult).sort((a, b) => b[1].champion - a[1].champion).slice(0, 5);
            html += '<div class="wir-head">Top 5 Champion Probabilities</div><div class="wir-grid">';
            teamsList.forEach(([team, probs]) => {
              const pct = (probs.champion * 100).toFixed(1);
              html += '<div class="wir-grid-item"><span class="wir-grid-team">' + team + '</span><span class="wir-grid-val">' + pct + '%</span></div>';
            });
            html += "</div>";
            resultDiv.innerHTML = html;
          }
          if (prog.status === "error") {
            clearInterval(pollInterval);
            progressLbl.textContent = "Error";
            resultDiv.style.display = "block";
            resultDiv.innerHTML = '<div style="color:#ff6b6b">Simulation error: ' + (prog.error || "unknown") + "</div>";
          }
        } catch (e) { clearInterval(pollInterval); }
      }, 200);
    } catch (e) {
      progressWrap.style.display = "none";
      resultDiv.style.display = "block";
      resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + "</div>";
    }
  }
};

// ── Standings ──
function renderStandings() {
  const tab = document.getElementById("tab-standings");
  if (!tab) return;
  const s = appState.standings;
  if (!s) return;
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

// ── Terminal ──
function buildWCTable(teams, cols) {
  const show = cols || ["champion", "final", "sf", "qf"];
  const labels = { champion: "Champion", final: "Final", sf: "SF", qf: "QF" };
  let h = '<tr><th>#</th><th>Team</th><th>Elo</th>';
  show.forEach(c => h += "<th>" + (labels[c] || c) + "</th>");
  h += '<th></th></tr><tr class="sep"><td class="num">──</td><td>────</td><td>───</td>';
  show.forEach(c => h += '<td class="num">' + (labels[c] || c).replace(/./g, '─') + '</td>');
  h += '<td></td></tr>';
  let html = "<table>" + h;
  teams.forEach((t, i) => {
    const pct = t[show[0]] || 0;
    const barW = Math.max(2, pct * 2);
    html += '<tr><td class="num">' + (i + 1) + '</td><td class="team">' + t.name + "</td>";
    show.forEach(c => html += '<td class="num prob">' + (t[c] || 0).toFixed(1) + '%</td>');
    html += '<td><div class="bar-wrap"><div class="bar" style="width:' + barW + 'px"></div></div></td></tr>';
  });
  return html + "</table>";
}

async function termBoot() {
  termBooting = true;
  const tab = document.getElementById("tab-terminal");
  if (!tab) return;
  termAdd('<span class="title">>> WC26  FIFA World Cup 2026 — Terminal Simulator</span>');
  termAdd('<span class="banner">+------------------------------------+\n|     MONTE CARLO SIMULATION         |\n|     50 000 iterations              |\n+------------------------------------+</span>');
  termAdd("");

  let bootSteps;
  try { bootSteps = await (await fetch(API + "/boot")).json(); }
  catch { termAdd('<span class="danger">ERROR: Server unreachable.</span>'); termShowPrompt(); termBooting = false; return; }

  for (const step of bootSteps) await termRenderBootStep(step);
  termAdd("");

  try {
    const [dr, sr, er, gr, br] = await Promise.all([
      fetch(API + "/data").then(r => r.json()),
      fetch(API + "/standings").then(r => r.json()),
      fetch(API + "/evaluation").then(r => r.json()),
      fetch(API + "/governance").then(r => r.json()),
      fetch(API + "/backtest").then(r => r.json()),
    ]);
    appState.data = dr;
    appState.standings = sr;
    appState.eval = er;
  } catch { termAdd('<span class="danger">ERROR: Failed to load prediction data.</span>'); termShowPrompt(); termBooting = false; return; }

  termAdd("");
  termAdd('<span class="highlight">== Champion Probability Table ==</span>');
  termAdd("");
  termAdd(buildWCTable(appState.data.teams));
  termAdd("");

  const ev = appState.eval;
  if (ev && ev.elo && ev.elo.n_matches > 0) {
    termAdd('<span class="highlight">== Elo Evaluation (replay)</span> <span class="dim">' + ev.elo.n_matches + " matches</span>");
    termAdd("  Brier: " + ev.elo.brier.toFixed(4) + "  LogLoss: " + ev.elo.log_loss.toFixed(4) + "  Accuracy: " + (ev.elo.accuracy * 100).toFixed(1) + "%");
    termAdd("");
    const others = Object.keys(ev).filter(k => k !== "elo" && ev[k].n_matches > 0);
    if (others.length) {
      termAdd('<span class="highlight">== Multi-Signal Evaluation</span>');
      let tbl = "<table><tr><th>Signal</th><th>Brier</th><th>LogLoss</th><th>Acc</th><th>N</th></tr>";
      others.forEach(sk => {
        const s = ev[sk];
        tbl += '<tr><td>' + sk + '</td><td class="num">' + s.brier.toFixed(4) + '</td><td class="num">' + s.log_loss.toFixed(4) + '</td><td class="num">' + (s.accuracy * 100).toFixed(1) + '%</td><td class="num">' + s.n_matches + "</td></tr>";
      });
      termAdd(tbl + "</table>");
    }
  }
  termAdd('<span class="dim">>> System ready. Type help to explore.</span>');
  termAdd("");
  termAdd('Type <span class="prompt">help</span> for available commands.', "dim");
  termShowPrompt();
  termBooting = false;
}

async function termExec(cmd) {
  const trimmed = cmd.trim();
  if (!trimmed) { termShowPrompt(); return; }
  const parts = trimmed.toLowerCase().split(/\s+/);
  const main = parts[0];
  const d = appState.data;

  if (main === "help") {
    termAdd("");
    termAdd('<span class="highlight">Available commands:</span>');
    termAdd('<span class="prompt">top N</span>       - top N by champion probability.');
    termAdd('<span class="prompt">elo</span>         - ranking by ELO rating.');
    termAdd('<span class="prompt">rank</span>        - full 48-team table (QF/SF/Final/Champion).');
    termAdd('<span class="prompt">standings</span>   - group tables + third-place bubble.');
    termAdd('<span class="prompt">bracket</span>     - resolved R32 matchups with win odds.');
    termAdd('<span class="prompt">eval</span>        - prediction accuracy (Brier, LogLoss, Accuracy).');
    termAdd('<span class="prompt">form</span>        - rolling form signal statistics.');
    termAdd('<span class="prompt">lineup</span>      - lineup strength / squad value signal.');
    termAdd('<span class="prompt">defensive</span>   - defensive quality signal.');
    termAdd('<span class="prompt">manager</span>     - manager effect signal.');
    termAdd('<span class="prompt">odds</span>        - market odds signal.');
    termAdd('<span class="prompt">catboost</span>    - CatBoost ML prediction signal.');
    termAdd('<span class="prompt">blend</span>       - signal blending weights and calibration.');
    termAdd('<span class="prompt">coverage</span>    - feature coverage audit report.');
    termAdd('<span class="prompt">gov</span>         - system health check.');
    termAdd('<span class="prompt">simulate [N]</span> - run Monte Carlo simulation (N iterations, default 50000).');
    termAdd('<span class="prompt">what-if TEAM[.PARAM=VALUE]</span> - team stats or scenario impact analysis.');
    termAdd('<span class="prompt">validate</span>   - run validation suite (Brier, LogLoss, accuracy).');
    termAdd('<span class="prompt">calibrate</span>  - trigger temperature scaling.');
    termAdd('<span class="prompt">export</span>      - print report snapshot.');
    termAdd('<span class="prompt">auto</span>        - toggle auto-refresh every 60s.');
    termAdd('<span class="prompt">clear</span>       - reset screen.');
    termAdd("");
  } else if (main === "clear") {
    document.getElementById("termOutput").innerHTML = "";
    termAdd('<span class="banner">+------------------------------------+\n|     MONTE CARLO SIMULATION         |\n|     50 000 iterations              |\n+------------------------------------+</span>');
    termAdd("");
  } else if (main === "top") {
    const n = parseInt(parts[1]) || 10;
    const teams = d ? d.teams.slice(0, Math.min(n, d.teams.length)) : [];
    if (!teams.length) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Top ' + teams.length + " -- Champion Probability ==</span>");
    termAdd(buildWCTable(teams));
    termAdd("");
  } else if (main === "standings") {
    const s = appState.standings;
    if (!s || !s.standings) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Group Standings ==</span>');
    Object.entries(s.standings).forEach(([letter, rows]) => {
      termAdd('<span class="title">Group ' + letter + "</span>");
      let tbl = "<table><tr><th>#</th><th>Team</th><th>Pts</th><th>GD</th><th>GS</th></tr>";
      rows.forEach(r => {
        const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
        tbl += '<tr><td class="num">' + r.position + "</td><td>" + r.team + '</td><td class="num">' + r.pts + '</td><td class="num">' + gd + '</td><td class="num">' + r.gs + "</td></tr>";
      });
      termAdd(tbl + "</table>");
    });
    const tp = s.third_place;
    if (tp && tp.length >= 9) {
      termAdd('<span class="title">Third-Place Bubble</span>');
      let tbl = "<table><tr><th>#</th><th>G</th><th>Team</th><th>Pts</th><th>GD</th><th>GS</th></tr>";
      tp.forEach((r, i) => {
        const cls = i >= 8 ? "dim" : "";
        termAdd('<span class="' + cls + '">' + (i + 1) + ". " + r.group + " " + r.team + " " + r.pts + "pts " + (r.gd > 0 ? "+" : "") + r.gd + " " + r.gs + "gs</span>");
      });
    }
    termAdd("");
  } else if (main === "bracket") {
    const br = appState.bracket;
    if (!br || !br.rounds) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Resolved R32 Matchups ==</span>');
    const ms = br.rounds.R32 || [];
    let tbl = "<table><tr><th>Match</th><th>Team A</th><th>Prob</th><th>Team B</th></tr>";
    ms.forEach(m => {
      const probStr = m.prob_a ? (m.prob_a * 100).toFixed(1) + "%" : "?";
      tbl += '<tr><td>' + m.match_id + "</td><td>" + m.team_a + '</td><td class="num">' + probStr + "</td><td>" + m.team_b + "</td></tr>";
    });
    termAdd(tbl + "</table>");
    termAdd("");
  } else if (main === "eval") {
    const ev = appState.eval;
    if (!ev) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Signal Evaluation ==</span>');
    let tbl = "<table><tr><th>Signal</th><th>Brier</th><th>LogLoss</th><th>Acc</th><th>N</th></tr>";
    Object.keys(ev).filter(k => ev[k].n_matches > 0).forEach(k => {
      const s = ev[k];
      tbl += '<tr><td>' + k + '</td><td class="num">' + s.brier.toFixed(4) + '</td><td class="num">' + (s.log_loss || 0).toFixed(4) + '</td><td class="num">' + (s.accuracy * 100).toFixed(1) + '%</td><td class="num">' + s.n_matches + "</td></tr>";
    });
    termAdd(tbl + "</table>");
    termAdd("");
  } else if (main === "gov") {
    const gr = appState.data ? appState.data.governance : null;
    if (!gr) { termAdd("No governance data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== System Health ==</span>');
    termAdd("  Status: " + gr.status + "  Data: " + gr.data_version + "  Model: " + gr.model_version + "  Run: " + gr.run_version);
    termAdd("");
  } else if (main === "coverage") {
    try {
      const cov = await (await fetch(API + "/coverage")).json();
      termAdd("");
      termAdd('<span class="highlight">== Coverage Audit ==</span>');
      termAdd(JSON.stringify(cov, null, 2).replace(/\n/g, "<br>").replace(/  /g, "&nbsp;&nbsp;"));
      termAdd("");
    } catch { termAdd("Failed to load coverage.", "danger"); }
  } else if (main === "simulate") {
    termAdd('<span class="dim">Open the Overview tab and click "Refresh & Simulate" to run a simulation.</span>');
  } else if (main === "auto") {
    toggleAuto(!autoRefreshOn);
    termAdd("");
    termAdd('<span class="highlight">== Auto-Refresh ==</span>');
    termAdd("  Auto-refresh every 60s: " + (autoRefreshOn ? '<span class="ok">ON</span>' : '<span class="danger">OFF</span>'));
    termAdd("");
  } else if (main === "elo") {
    const teams = d ? [...d.teams].sort((a, b) => b.elo - a.elo) : [];
    if (!teams.length) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Elo Ranking ==</span>');
    let tbl = "<table><tr><th>#</th><th>Team</th><th>Elo</th></tr>";
    teams.forEach((t, i) => {
      tbl += '<tr><td class="num">' + (i + 1) + "</td><td>" + t.name + '</td><td class="num">' + t.elo + "</td></tr>";
    });
    termAdd(tbl + "</table>");
    termAdd("");
  } else if (main === "rank") {
    if (!d) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Full Team Ranking ==</span>');
    termAdd(buildWCTable(d.teams, ["champion", "final", "sf", "qf"]));
    termAdd("");
  } else if (["form", "lineup", "defensive", "manager", "odds", "catboost"].includes(main)) {
    const sigName = main === "lineup" ? "lineup_strength" : main === "defensive" ? "defensive_quality" : main === "manager" ? "manager_effect" : main === "odds" ? "market_odds" : main;
    try {
      const sig = await (await fetch(API + "/signal/" + sigName)).json();
      termAdd("");
      termAdd('<span class="highlight">== ' + sigName + " Signal Detail ==</span>");
      termAdd("  Matches: " + sig.n_matches + "  With results: " + sig.n_with_results);
      if (sig.live_eval && sig.live_eval.n) {
        termAdd("  Live Brier: " + sig.live_eval.brier + "  Live Accuracy: " + (sig.live_eval.accuracy * 100).toFixed(1) + "%");
      }
      if (sig.cache_eval) {
        termAdd("  Cache Brier: " + sig.cache_eval.brier + "  Cache Accuracy: " + (sig.cache_eval.accuracy * 100).toFixed(1) + "%");
      }
      termAdd("");
    } catch { termAdd("Signal not found: " + sigName, "danger"); }
  } else if (main === "blend") {
    try {
      const bl = await (await fetch(API + "/blend")).json();
      termAdd("");
      termAdd('<span class="highlight">== Signal Blending ==</span>');
      termAdd("  Status: " + bl.calibration_status + " (" + bl.n_matches_for_calibration + "/" + bl.threshold + " matches)");
      let tbl = "<table><tr><th>Signal</th><th>Brier</th><th>Weight</th></tr>";
      Object.entries(bl.blend_weights).forEach(([sk, w]) => {
        const b = bl.backtest_briers[sk] || "?";
        tbl += '<tr><td>' + sk + '</td><td class="num">' + b + '</td><td class="num">' + (w * 100).toFixed(1) + "%</td></tr>";
      });
      termAdd(tbl + "</table>");
      termAdd("");
    } catch { termAdd("Failed to load blend info.", "danger"); }
  } else if (main === "simulate") {
    const n = parseInt(parts[1]) || 50000;
    await termRunSimulation(API, n, async () => {
      const ov = await fetch(API + "/overview").then(r => r.json());
      appState.overview = ov;
      appState.data = ov;
      const teams = ov.teams || [];
      termAdd("");
      termAdd('<span class="highlight">== Champion Probability Table ==</span>');
      termAdd(buildWCTable(teams));
      termAdd("");
      updateStatus();
    });
    return;
  } else if (main === "what-if") {
    const arg = parts.slice(1).join(" ").trim();
    if (!arg) { termAdd("Usage: what-if <TEAM[.PARAM=VALUE]>", "dim"); termShowPrompt(); return; }
    const dotIdx = arg.indexOf(".");
    const eqIdx = arg.indexOf("=");
    let teamName, param, value;
    if (dotIdx > 0 && eqIdx > dotIdx) { teamName = arg.slice(0, dotIdx); param = arg.slice(dotIdx + 1, eqIdx); value = parseFloat(arg.slice(eqIdx + 1)); }
    else { teamName = arg; param = null; }
    const teams = (d && d.teams) || [];
    const team = teams.find(t => t.name.toLowerCase() === teamName.toLowerCase());
    if (!team) { termAdd("Team not found: " + teamName, "danger"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== ' + team.name + ' ==</span>');
    termAdd('  Elo: <span class="num">' + team.elo + '</span>');
    termAdd('  Champion: <span class="num">' + (team.champion || 0).toFixed(1) + '%</span>');
    termAdd('  Final: <span class="num">' + (team.final || 0).toFixed(1) + '%</span>  SF: <span class="num">' + (team.sf || 0).toFixed(1) + '%</span>  QF: <span class="num">' + (team.qf || 0).toFixed(1) + '%</span>');
    termAdd('  Group: <span class="num">' + (team.group_win || 0).toFixed(1) + '%</span>  R32: <span class="num">' + (team.r32 || 0).toFixed(1) + '%</span>');
    if (team.form_avg !== undefined) termAdd('  Form: <span class="num">' + team.form_avg.toFixed(3) + '</span>');
    if (team.odds_avg !== undefined) termAdd('  Market Odds: <span class="num">' + team.odds_avg.toFixed(3) + '</span>');
    try {
      const sig = await (await fetch(API + "/signals")).json();
      const teamSigs = (sig.team_signals || {})[team.name] || {};
      if (Object.keys(teamSigs).length) {
        termAdd('<span class="dim">--- Signal Breakdown ---</span>');
        Object.entries(teamSigs).forEach(([k, v]) => {
          termAdd('  ' + k + ': <span class="num">' + (typeof v === "number" ? v.toFixed(4) : v) + '</span>');
        });
      }
    } catch {}
    if (param && !isNaN(value)) {
      let matchId = null;
      try {
        const br = appState.bracketData;
        if (br && br.knockout_tree) {
          for (const [, ms] of Object.entries(br.knockout_tree)) {
            const found = ms.find(m => (m.team_a || "").toLowerCase() === team.name.toLowerCase() || (m.team_b || "").toLowerCase() === team.name.toLowerCase());
            if (found) { matchId = found.match_id; break; }
          }
        }
      } catch {}
      if (matchId) {
        const scenario = param === "form" && value > 1 ? team.name + " in form" : param === "form" && value < 1 ? team.name + " poor form" : param === "defense" && value > 1 ? team.name + " strong defense" : param === "defense" && value < 1 ? team.name + " weak defense" : param === "lineup" && value < 1 ? team.name + " lineup injury" : param === "manager" && value < 0.5 ? team.name + " manager sacked" : team.name + " " + param + " " + value;
        await termRunWithSpinner('<span class="highlight">What-If</span>',
          () => fetch(API + "/what-if", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ match_id: matchId, scenario, mode: "instant" }) }).then(r => r.json()),
          result => {
            if (result.error) { termAdd('<span class="dim">' + result.error + '</span>'); return; }
            if (result.insight) termAdd('<span class="title">Impact:</span> ' + result.insight.replace(/<br>/g, ' '));
            if (result.adjusted_signals) {
              const adj = Object.entries(result.adjusted_signals).filter(([, sv]) => sv.was_adjusted);
              if (adj.length) {
                let tbl = '<table><tr><th>Signal</th><th>Before</th><th>After</th><th>Δ</th></tr>';
                adj.forEach(([sk, sv]) => {
                  const base = sv.original_probability != null ? (sv.original_probability * 100) : ((sv.probability - sv.delta) * 100);
                  const aft = sv.probability * 100;
                  const d = sv.delta * 100;
                  const cls = d >= 0 ? "ok" : "danger";
                  tbl += '<tr><td>' + (sigLabels[sk] || sk) + '</td><td class="num prob">' + base.toFixed(1) + '%</td><td class="num prob">' + aft.toFixed(1) + '%</td><td class="num ' + cls + '">' + (d >= 0 ? "+" : "") + d.toFixed(1) + '%</td></tr>';
                });
                termAdd(tbl + '</table>');
              }
            }
          }
        );
      } else {
        termAdd('<span class="dim">No match found for scenario analysis.</span>');
      }
    }
    termAdd("");
  } else if (main === "validate") {
    await termRunWithSpinner('<span class="highlight">Validate</span>',
      () => fetch(API + "/validation").then(r => r.json()),
      v => {
        if (v.error) { termAdd('<span class="danger">' + v.error + '</span>'); return; }
        termAdd('<span class="highlight">== Validation ==</span>');
        termAdd('  Matches evaluated: ' + (v.n_matches || "?"));
        if (v.before) {
          termAdd('<span class="title">Before Calibration:</span>');
          termAdd('  Brier: ' + v.before.brier.toFixed(4) + '  LogLoss: ' + (v.before.log_loss || 0).toFixed(4) + '  Accuracy: ' + ((v.before.accuracy || 0) * 100).toFixed(1) + '%');
        }
        if (v.after) {
          termAdd('<span class="title">After Calibration:</span>');
          termAdd('  Brier: ' + v.after.brier.toFixed(4) + '  LogLoss: ' + (v.after.log_loss || 0).toFixed(4) + '  Accuracy: ' + ((v.after.accuracy || 0) * 100).toFixed(1) + '%');
        }
        if (v.calibrated) {
          termAdd('  Calibrated: <span class="ok">' + v.calibrated + '</span>');
        }
      }
    );
    termAdd("");
  } else if (main === "calibrate") {
    await termRunCalibration(API);
    return;
  } else if (main === "export") {
    await termRunWithSpinner('<span class="highlight">Export</span>',
      () => fetch(API + "/report").then(r => r.json()),
      r => {
        if (r.error) { termAdd('<span class="danger">' + r.error + '</span>'); return; }
        termAdd('<span class="highlight">== Report Snapshot ==</span>');
        if (r.timestamp) termAdd('  Timestamp: <span class="dim">' + r.timestamp + '</span>');
        if (r.iterations) termAdd('  Iterations: ' + r.iterations.toLocaleString());
        if (r.seed !== undefined) termAdd('  Seed: ' + r.seed);
        if (r.top_teams && r.top_teams.length) {
          termAdd('<span class="title">Top Teams:</span>');
          r.top_teams.slice(0, 10).forEach((t, i) => {
            termAdd('  ' + (i + 1) + '. ' + t.name + ' — ' + (t.champion_prob || 0).toFixed(1) + '% champion');
          });
        }
        if (r.evaluation) {
          const ev = r.evaluation;
          termAdd('<span class="title">Evaluation:</span>');
          Object.entries(ev).forEach(([k, v]) => {
            if (v.n_matches > 0) termAdd('  ' + k + ' — Brier: ' + v.brier.toFixed(4) + '  Accuracy: ' + ((v.accuracy || 0) * 100).toFixed(1) + '%');
          });
        }
        if (r.calibration) {
          termAdd('  Calibration status: <span class="dim">' + (r.calibration.status || "N/A") + '</span>');
        }
      }
    );
    termAdd("");
  } else {
    termAdd("command not found: " + trimmed, "danger");
    termAdd('Type <span class="prompt">help</span> for available commands.', "dim");
  }
  termShowPrompt();
}
