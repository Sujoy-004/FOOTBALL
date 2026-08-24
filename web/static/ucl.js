// ── UCL 2025/26 Module ──
import {
  destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions, showSimPopup,
  buildTable, safeJson,
} from "./shared.js";

const API = "/ucl/api";
const appState = { data: null, standings: [], bracket: null, odds: [], signals: {}, matches: [] };

export function init(comp) {
  loadAll();
}

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
    const matches = [];
    if (br.playoff) br.playoff.forEach(m => matches.push({ ...m, round: "Playoff", match_id: "po_" + m.tie_num }));
    if (br.bracket_rounds) {
      Object.entries(br.bracket_rounds).forEach(([rnd, ms]) => {
        ms.forEach(m => matches.push({ ...m, round: rnd }));
      });
    }
    appState.matches = matches;
  } catch (e) {
    console.error("loadAll API fetch failed:", e);
    const tab = document.getElementById("tab-overview");
    if (tab) tab.innerHTML = '<div class="stat-card" style="color:#ff6b6b">Failed to load data</div>';
    return;
  }
  try { renderOverview(); } catch (e) { console.error("renderOverview:", e); }
  try { renderStandings(); } catch (e) { console.error("renderStandings:", e); }
  try { renderBracket(); } catch (e) { console.error("renderBracket:", e); }
  try { updateStatus(); } catch (e) { console.error("updateStatus:", e); }
}

function updateStatus() {
  const d = appState.data;
  if (!d) return;
  const signals = appState.signals;
  const sigKeys = Object.keys(signals);
  const nActive = sigKeys.filter(k => { const s = signals[k]; return s && (s.available || s.available_pct > 0 || s.n_matches > 0); }).length;
  const stale = d.refresh && d.refresh.stale;
  updateStatusBar(
    d.n_teams + " teams  |  " + (d.n_played || 0) + " matches played  |  " + nActive + " / " + sigKeys.length + " signals",
    stale ? '<span style="color:#e6a817">⚠ STALE — live refresh failed; showing snapshot data</span>' : ""
  );
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
    appState.data = d; appState.standings = s.standings || [];
    appState.bracket = br; appState.odds = o.odds || [];
    appState.signals = sig.signals || {};
    const matches = [];
    if (br.playoff) br.playoff.forEach(m => matches.push({ ...m, round: "Playoff", match_id: "po_" + m.tie_num }));
    if (br.bracket_rounds) {
      Object.entries(br.bracket_rounds).forEach(([rnd, ms]) => {
        ms.forEach(m => matches.push({ ...m, round: rnd }));
      });
    }
    appState.matches = matches;
    renderOverview(); renderStandings(); renderBracket();
    updateStatus();
  } catch (e) {
    console.error("reloadData failed:", e);
  }
}

window.__simulateAllRemaining = function () {
  showSimPopup(API, {
    bodyBuilder: iters => ({ iterations: iters }),
    onComplete: async () => {
      await reloadData();
      try {
        const simResp = await safeJson("/ucl/api/simulation");
        appState.simBracket = (simResp.bracket_rounds || simResp.playoff) ? {
          bracket_rounds: simResp.bracket_rounds || {},
          playoff: simResp.playoff || []
        } : null;
      } catch { appState.simBracket = null; }
      renderBracket();
    },
  });
};

window.__resetResults = async function () {
  try {
    const resp = await safeJson(API + "/reset", { method: "POST" });
    if (resp.status === "error") {
      console.error("Reset error:", resp.error);
      return;
    }
    const [d, s, br, o, sig] = await Promise.all([
      safeJson(API + "/data"),
      safeJson(API + "/standings"),
      safeJson(API + "/bracket"),
      safeJson(API + "/odds"),
      safeJson(API + "/signals"),
    ]);
    appState.data = d; appState.standings = s.standings || [];
    appState.bracket = br; appState.odds = o.odds || [];
    appState.signals = sig.signals || {};
    renderOverview(); renderStandings(); renderBracket();
    updateStatus();
  } catch (e) {
    console.error("Reset failed:", e);
  }
};

// ── Overview (WC-style layout) ──
async function renderOverview() {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const d = appState.data;
  if (!d) return;
  const html = '<div class="stats-row">' +
    '<div class="stat-card"><div class="val">' + d.n_teams + '</div><div class="lbl">Teams</div></div>' +
    '<div class="stat-card"><div class="val">' + (d.n_played || 0) + '</div><div class="lbl">Matches</div></div>' +
    '</div>';
  tab.innerHTML = html;
}

function renderStandings() {
  const tab = document.getElementById("tab-standings");
  if (!tab) return;
  const st = appState.standings || [];
  if (!st.length) { tab.innerHTML = '<div style="color:#15565B;font-size:12px">No standings data.</div>'; return; }
  let html = '<div class="league-table-wrap"><table class="league-table"><tr><th>Pos</th><th>Team</th><th>Pld</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Zone</th></tr>';
  st.forEach(function(r) {
    const zone = r.zone || "eliminated";
    const cls = zone === "top_8" ? "zone-top8" : zone === "playoff" ? "zone-playoff" : "";
    const zoneLabel = zone === "top_8" ? "TOP 8" : zone === "playoff" ? "PLAYOFF" : "OUT";
    const zoneCls = zone === "top_8" ? "top8" : zone === "playoff" ? "playoff" : "eliminated";
    const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
    const pld = (r.wins || 0) + (r.draws || 0) + (r.losses || 0);
    html += '<tr class="' + cls + '"><td class="num">' + r.position + '</td><td>' + r.team + '</td><td class="num">' + pld + '</td><td class="num">' + (r.wins || 0) + '</td><td class="num">' + (r.draws || 0) + '</td><td class="num">' + (r.losses || 0) + '</td><td class="num">' + (r.gs || 0) + '</td><td class="num">' + (r.ga || 0) + '</td><td class="num">' + gd + '</td><td class="num">' + (r.pts !== undefined && r.pts !== null ? r.pts : "?") + '</td><td><span class="zone-badge ' + zoneCls + '">' + zoneLabel + '</span></td></tr>';
  });
  html += "</table></div>";
  tab.innerHTML = html;
}

function renderBracket() {
  const tab = document.getElementById("tab-bracket");
  if (!tab) return;
  const br = appState.bracket;
  if (!br) { tab.innerHTML = "<p>No bracket data.</p>"; return; }

  const playoff = br.playoff || [];
  let poHtml = "";
  if (playoff.length) {
    poHtml = '<div class="g-title">Playoff Round (9-24)</div><div class="playoff-grid">';
    playoff.forEach(function(t) {
      const aggStr = t.aggregate_a + "-" + t.aggregate_b;
      let detail = aggStr + " agg";
      if (t.et_played) detail += " (ET)";
      if (t.penalties_played) detail += " (pens)";
      poHtml += '<div class="playoff-card"><div class="p-title">Tie ' + t.tie_num + '</div><div class="p-teams"><span class="p-team winner">' + t.team_a + '</span><span class="p-score">' + aggStr + '</span><span class="p-team">' + t.team_b + '</span></div><div class="p-detail">' + detail + "</div></div>";
    });
    poHtml += "</div>";
  }

  const lmd = br.league_matchdays || {};
  const lmdKeys = Object.keys(lmd).sort();
  let mdHtml = "";
  if (lmdKeys.length) {
    mdHtml = '<div class="g-title">League Phase</div><div class="md-accordion">';
    const firstMid = lmdKeys[0];
    lmdKeys.forEach(function(md) {
      const ms = lmd[md] || [];
      const isFirst = md === firstMid;
      mdHtml += '<div class="md-card"><div class="md-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">';
      mdHtml += '<span class="md-label">' + md + '</span><span class="md-count">' + ms.length + " matches</span>";
      mdHtml += "</div>";
      mdHtml += '<div class="md-body' + (isFirst ? " open" : "") + '"><table class="league-table"><tr><th>#</th><th>Home</th><th>Score</th><th>Away</th></tr>';
      ms.forEach(function(m) {
        const hs = m.home_score !== undefined ? m.home_score : "-";
        const as_ = m.away_score !== undefined ? m.away_score : "-";
        mdHtml += "<tr><td>" + m.match_id + "</td><td>" + m.team_a + "</td><td>" + hs + "-" + as_ + "</td><td>" + m.team_b + "</td></tr>";
      });
      mdHtml += "</table></div></div>";
    });
    mdHtml += "</div>";
  }
  tab.innerHTML = poHtml + mdHtml;
}



function getScoreStr(m) {
  if (m.score) return m.score.home + "-" + m.score.away;
  if (m.result && m.result.score_a !== undefined) return m.result.score_a + "-" + m.result.score_b;
  if (m.home_score !== undefined) return m.home_score + "-" + m.away_score;
  return "No result";
}

async function openMatchModal(m) {
  destroyModalCharts();
  const mid = m.match_id || m.tie_num || "";
  document.getElementById("modalTitle").innerHTML = (m.team_a || "TBD") + ' <span style="color:#15565B;font-weight:normal">vs</span> ' + (m.team_b || "TBD");
  document.getElementById("modalSub").textContent = m.round + " — " + mid + "  |  " + getScoreStr(m);
  document.getElementById("modalBody").innerHTML = '<div class="mb-wrap"><div class="mb-col" id="mbLeft"></div><div class="mb-col" id="mbRight"></div></div><div id="modalBottom"></div>';
  document.getElementById("modalOverlay").classList.add("show");

  const bodyEl = document.getElementById("modalBody");
  const left = document.getElementById("mbLeft");
  const right = document.getElementById("mbRight");
  const bottom = document.getElementById("modalBottom");

  let insight;
  try { insight = await safeJson(API + "/match/insight?match_id=" + mid); } catch { insight = { error: "fetch failed" }; }
  if (insight.error) {
    bodyEl.innerHTML = '<div style="color:#ff6b6b;font-size:12px">Failed to load match insight.</div>';
    return;
  }

  const ta = insight.teams.a, tb = insight.teams.b;
  const sigs = insight.signals || {};
  const ev = appState.signals || {};
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
      if (se && se.n_matches > 0 && se.brier !== undefined) {
        const dot = se.brier < 0.15 ? "dot-green" : se.brier < 0.25 ? "dot-orange" : "dot-red";
        return '<tr><td>' + (sigLabels[sk] || sk) + '</td><td class="num">' + se.brier.toFixed(4) + '</td><td class="num">' + (se.accuracy * 100).toFixed(1) + '%</td><td class="num"><span class="' + dot + '">&#9679;</span></td></tr>';
      }
      return "";
    }).join("")}
    ${sigOrder.every(sk => { const se = ev[sk]; return !se || !se.n_matches || se.brier === undefined; }) ? '<tr><td colspan="4" style="color:#15565B;text-align:center">No eval data available</td></tr>' : ""}
    </table>
    <div class="sec-title">Match Insight</div>
    <div class="insight-box">${insight.insight || "No insight available."}</div>
  `;

  bottom.innerHTML = `
    <div class="sec-title warn">What-If Scenario</div>
    <div class="whatif-input-wrap">
      <input type="number" id="modalWhatifDelta" value="50" step="10" style="width:90px">
      <button onclick="window.__sendModalWhatIf('${mid}','${ta}','${tb}')">&#9654;</button>
    </div>
    <div class="whatif-controls"><label>Elo boost for ${ta} (opponent lowered equally):</label></div>
    <div class="whatif-modal-result" id="modalWhatifResult"></div>
  `;

  // Form trend charts
  [ta, tb].forEach(team => {
    const tr = ft[team] || [];
    const canvas = document.getElementById("fc-" + team.replace(/\s/g, ""));
    if (!canvas) return;
    const labels = tr.map((_, i) => "M" + (i + 1));
    const vals = tr.map(r => r.result === "W" ? 1 : r.result === "D" ? 0.5 : 0);
    modalCharts["form_" + team] = new Chart(canvas, {
      type: "line",
      data: { labels, datasets: [{ data: vals, borderColor: "#16A085", backgroundColor: "transparent", pointBackgroundColor: "#16A085", borderWidth: 2, tension: 0.3, pointRadius: 3 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { min: -0.1, max: 1.1, display: false } } }
    });
  });

  // Signal comparison bar chart
  const sigCanvas = document.getElementById("sigChart");
  if (sigCanvas) {
    const sigKeys = sigOrder.filter(sk => sigs[sk] !== undefined);
    const sigVals = sigKeys.map(sk => Math.round((sigs[sk].probability || 0.5) * 100));
    const sigColors = sigKeys.map((sk, i) => i === 0 ? "#16A085" : "#156F69");
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

  // Outcome distribution doughnut
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

window.__sendModalWhatIf = async function (matchId, teamA, teamB) {
  const deltaInput = document.getElementById("modalWhatifDelta");
  const eloDelta = parseInt(deltaInput.value) || 50;
  const resultDiv = document.getElementById("modalWhatifResult");
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<div style="color:#15565B;font-size:11px">Running seeded counterfactual...</div>';
  try {
    const resp = await safeJson(API + "/what-if", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: matchId, elo_delta: eloDelta }),
    });
    if (resp.error) { resultDiv.innerHTML = '<div style="color:#ff6b6b">' + resp.error + "</div>"; return; }
    const row = (name, e) => {
      const t = resp.teams[name] || {};
      const d = t.delta || 0;
      const cls = d >= 0 ? "wir-diff-pos" : "wir-diff-neg";
      return '<tr><td>' + name + ' (Elo ' + e + ')</td><td class="num">' + ((t.baseline||0)*100).toFixed(1) + '%</td><td class="num">' + ((t.adjusted||0)*100).toFixed(1) + '%</td><td class="num ' + cls + '">' + (d>=0?"+":"") + (d*100).toFixed(1) + '%</td></tr>';
    };
    let html = '<div class="wir-head">Champion probability: baseline vs adjusted</div><table class="odds-table" style="width:100%"><tr><th>Team</th><th>Baseline</th><th>Adjusted</th><th>Delta</th></tr>';
    html += row(teamA, (resp.elo_changes||{})[teamA] || "?");
    html += row(teamB, (resp.elo_changes||{})[teamB] || "?");
    html += "</table>";
    html += '<div class="wir-meta">Seeded Monte Carlo (seed 42), ' + (resp.iterations||0).toLocaleString() + ' iterations.</div>';
    resultDiv.innerHTML = html;
  } catch (e) {
    resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + "</div>";
  }
};

// ── Odds ──
function renderOdds() {
  const tab = document.getElementById("tab-odds");
  if (!tab) return;
  const odds = appState.odds;
  if (!odds || !odds.length) {
    tab.innerHTML = '<div style="color:#15565B;font-size:12px">No odds data.</div>';
    return;
  }
  tab.innerHTML = `<div class="odds-wrap"><table class="odds-table">
    <tr><th>#</th><th>Team</th><th>Champion</th><th>Final</th><th>SF</th><th>QF</th><th>Top 8</th></tr>
    ${odds.map(t => '<tr><td class="num">' + t.rank + '</td><td>' + t.team + '</td>' +
      '<td class="num">' + (t.champion_prob * 100).toFixed(1) + '%<span class="odds-bar-wrap"><span class="odds-bar" style="width:' + Math.max(2, t.champion_prob * 200) + '%"></span></span></td>' +
      '<td class="num">' + (t.final_prob * 100).toFixed(1) + '%</td>' +
      '<td class="num">' + (t.sf_prob * 100).toFixed(1) + '%</td>' +
      '<td class="num">' + (t.qf_prob * 100).toFixed(1) + '%</td>' +
      '<td class="num">' + (t.top_8_prob * 100).toFixed(1) + '%</td></tr>').join("")}
  </table></div>`;
}

// ── Signals ──
function renderSignals() {
  const tab = document.getElementById("tab-signals");
  if (!tab) return;
  const sigs = appState.signals;
  const keys = Object.keys(sigs);
  const mode = (appState.data || {}).mode || "simulation";
  const hasBrier = mode === "results" && keys.length > 0 && sigs[keys[0]] && sigs[keys[0]].brier !== undefined;

  if (!keys.length) {
    tab.innerHTML = '<div style="color:#15565B;font-size:12px">No signal data available.</div>';
    return;
  }

  let html = '<table class="eval-table"><tr><th>Signal</th><th>Avg Prob</th><th>Matches</th><th>Avail</th><th>Weight</th>';
  if (hasBrier) html += "<th>Brier</th><th>Accuracy</th>";
  html += "<th></th></tr>";
  keys.forEach(k => {
    const s = sigs[k];
    const pct = s.available_pct || 0;
    const dot = pct >= 80 ? "dot-green" : pct >= 50 ? "dot-orange" : "dot-red";
    const status = pct >= 80 ? "High" : pct >= 50 ? "Medium" : "Low";
    html += '<tr><td>' + k + '</td><td class="num">' + (s.avg_probability || 0).toFixed(3) + '</td><td class="num">' + s.n_matches + '</td><td class="num">' + pct + '%</td><td class="num">' + ((s.weight || 0) * 100).toFixed(1) + '%</td>';
    if (hasBrier) {
      const b = s.brier || 0;
      const acc = (s.accuracy || 0) * 100;
      const brierDot = b < 0.15 ? "dot-green" : b < 0.25 ? "dot-orange" : "dot-red";
      html += '<td class="num"><span class="' + brierDot + '">&#9679;</span> ' + b.toFixed(4) + '</td><td class="num">' + acc.toFixed(1) + "%</td>";
    }
    html += '<td class="num"><span class="' + dot + '">&#9679;</span> ' + status + "</td></tr>";
  });
  html += "</table>";
  tab.innerHTML = html;
}



