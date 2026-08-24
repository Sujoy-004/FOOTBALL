// ── World Cup 2026 Module ──
import {
  buildTable, destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions,
} from "./shared.js";

const API = "/worldcup/api";
const sigLabels = { elo: "Elo", market_odds: "Market Odds", rolling_form: "Rolling Form", squad_value: "Squad Value", rest_days: "Rest Days" };
const appState = { data: null, overview: null, standings: null, bracket: null, fullBracket: null, eval: null, blend: null, signalCache: {} };
let refreshing = false;
let autoRefreshOn = false;
let autoTimer = null;

export function init(comp) {
  loadAll();
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
  const stale = d.refresh && d.refresh.stale;
  updateStatusBar(
    d.n_teams + " teams  |  " + d.n_played + " matches played  |  " + nActive + " active signals",
    stale ? '<span style="color:#e6a817">⚠ STALE — live refresh failed; showing snapshot data</span>' : ""
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

    if (resp.status === "no_unplayed_matches") {
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
    try {
      const simResp = await fetch(API + "/simulation").then(r => r.json());
      appState.simBracket = simResp.full_bracket ? simResp.full_bracket : null;
    } catch { appState.simBracket = null; }
    renderBracket();
  } catch (e) {
    progressLbl.textContent = "Error: " + (e.message || "unknown");
    startBtn.disabled = false;
    cancelBtn.style.display = "";
  }
  refreshing = false;
}
window.__refreshWC = showSimPopup;

// ── Overview (real data only) ──

async function renderOverview() {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const ov = appState.overview || appState.data;
  if (!ov) return;

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

  html += '<div style="text-align:right;margin-bottom:8px"><button class="status-btn" onclick="window.__simulateAllRemaining()">&#9654; Simulate All Remaining</button></div>';

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

  // Build sim match lookup if sim bracket data exists
  const simById = {};
  if (appState.simBracket && appState.simBracket.rounds) {
    for (const [, ms] of Object.entries(appState.simBracket.rounds)) {
      for (const sm of ms) simById[sm.match_id] = sm;
    }
  }

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
      const isPlayed = m.played || !!m.winner;
      const isTbd = (!m.team_a && !m.team_b) || (!m.played && !m.winner);

      // Determine score string: real > sim predicted > placeholder
      let scoreStr, simWinnerHtml = "", simProbHtml = "";
      const simM = (!isPlayed && simById[m.match_id]) ? simById[m.match_id] : null;
      if (m.score) {
        scoreStr = m.score.home + '-' + m.score.away;
      } else if (m.winner) {
        scoreStr = '1-0';
      } else if (simM && simM.predicted_score) {
        scoreStr = simM.predicted_score.home + '-' + simM.predicted_score.away;
      } else {
        scoreStr = '?-?';
      }
      if (simM && simM.predicted_score) {
        const pct = (simM.prob_a != null) ? Math.round(simM.prob_a * 100) : 50;
        simProbHtml = '<div class="m-prob" style="font-size:9px;color:#8E44AD;text-align:center;line-height:1.2">' + pct + '% / ' + (100 - pct) + '%</div>';
      }

      const cardClass = isTbd ? 'tbd' : isPlayed ? 'played' : 'upcoming';

      let cardHtml = '<div class="match-card ' + cardClass + '" data-mid="' + m.match_id + '">' +
        '<div class="m-teams"><span class="m-team ' + (m.winner === ta ? 'winner' : '') + '">' + ta + '</span>' +
        '<span class="m-score">' + scoreStr + '</span>' +
        '<span class="m-team ' + (m.winner === tb ? 'winner' : '') + '">' + tb + '</span></div>' +
        (m.winner ? '<div class="m-winner-label">' + m.winner + ' advances</div>' : simProbHtml);

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
  const scoreStr = (m.home_score != null && m.away_score != null) ? (m.home_score + '-' + m.away_score) : (m.played ? '?' : '—');
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
        if (resp.status === 'no_unplayed_matches') {
          resultDiv.textContent = resp.message || 'All matches played.';
          resultDiv.style.display = 'block';
          startBtn.disabled = false;
          cancelBtn.style.display = '';
          progressWrap.style.display = 'none';
          return;
        }
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
        try {
          const simResp = await fetch(API + '/simulation').then(r => r.json());
          appState.simBracket = simResp.full_bracket ? simResp.full_bracket : null;
        } catch { appState.simBracket = null; }
        renderBracket();
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

  bottom.innerHTML = `
    <div class="sec-title warn">What-If Scenario</div>
    <div class="whatif-input-wrap">
      <input type="number" id="whatifDelta" value="50" step="10" style="width:90px">
      <button onclick="window.__sendWhatIf('${mid}','${ta}','${tb}')">&#9654;</button>
    </div>
    <div class="whatif-controls">
      <label>Elo boost for ${ta} (opponent lowered equally):</label>
    </div>
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
window.__sendWhatIf = async function (mid, ta, tb) {
  const deltaInput = document.getElementById("whatifDelta");
  const eloDelta = parseInt(deltaInput.value) || 50;
  const resultDiv = document.getElementById("whatifResult");
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<div style="color:#15565B;font-size:11px">Running seeded counterfactual...</div>';
  try {
    const resp = await (await fetch(API + "/what-if", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: mid, elo_delta: eloDelta })
    })).json();
    if (resp.error) { resultDiv.innerHTML = '<div style="color:#ff6b6b">' + resp.error + "</div>"; return; }
    const row = (name, e) => {
      const t = resp.teams[name] || {};
      const d = t.delta || 0;
      const cls = d >= 0 ? "wir-diff-pos" : "wir-diff-neg";
      return '<tr><td>' + name + ' (Elo ' + e + ')</td><td class="num">' + ((t.baseline||0)*100).toFixed(1) + '%</td><td class="num">' + ((t.adjusted||0)*100).toFixed(1) + '%</td><td class="num ' + cls + '">' + (d>=0?"+":"") + (d*100).toFixed(1) + '%</td></tr>';
    };
    let html = '<div class="wir-head">Champion probability: baseline vs adjusted</div><table class="odds-table" style="width:100%"><tr><th>Team</th><th>Baseline</th><th>Adjusted</th><th>Delta</th></tr>';
    html += row(ta, (resp.elo_changes||{})[ta] || "?");
    html += row(tb, (resp.elo_changes||{})[tb] || "?");
    html += "</table>";
    html += '<div class="wir-meta">Seeded Monte Carlo (seed 42), ' + (resp.iterations||0).toLocaleString() + ' iterations.</div>';
    resultDiv.innerHTML = html;
  } catch (e) {
    resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + "</div>";
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




