// ── UCL 2025/26 Module ──
import {
  destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions, showSimPopup,
  buildTable,
} from "./shared.js";

const API = "/ucl/api";
const appState = { data: null, standings: [], bracket: null, odds: [], signals: {}, matches: [] };

export function init(comp) {
  loadAll();
}

async function loadAll() {
  try {
    const [d, s, br, o, sig] = await Promise.all([
      fetch(API + "/data").then(r => r.json()),
      fetch(API + "/standings").then(r => r.json()),
      fetch(API + "/bracket").then(r => r.json()),
      fetch(API + "/odds").then(r => r.json()),
      fetch(API + "/signals").then(r => r.json()),
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
  updateStatusBar(
    d.n_teams + " teams  |  " + (d.n_played || 0) + " matches played  |  " + nActive + " / " + sigKeys.length + " signals",
    ""
  );
}

async function reloadData() {
  try {
    const [d, s, br, o, sig] = await Promise.all([
      fetch(API + "/data").then(r => r.json()),
      fetch(API + "/standings").then(r => r.json()),
      fetch(API + "/bracket").then(r => r.json()),
      fetch(API + "/odds").then(r => r.json()),
      fetch(API + "/signals").then(r => r.json()),
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
        const simResp = await fetch("/ucl/api/simulation").then(r => r.json());
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
    const resp = await (await fetch(API + "/reset", { method: "POST" })).json();
    if (resp.status === "error") {
      console.error("Reset error:", resp.error);
      return;
    }
    const [d, s, br, o, sig] = await Promise.all([
      fetch(API + "/data").then(r => r.json()),
      fetch(API + "/standings").then(r => r.json()),
      fetch(API + "/bracket").then(r => r.json()),
      fetch(API + "/odds").then(r => r.json()),
      fetch(API + "/signals").then(r => r.json()),
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
  const signals = appState.signals;
  const sigKeys = Object.keys(signals);

  const sigLabelMap = { elo: "Elo", all_signals: "Blended", refined_elo: "Refined Elo", market_odds: "Market Odds", rolling_form: "Rolling Form", squad_value: "Squad Value", rest_days: "Rest Days" };

  const signalList = [];
  sigKeys.forEach(k => {
    const s = signals[k];
    if (!s) return;
    const available = (s.available || s.available_pct > 0 || s.n_matches > 0) ? true : false;
    signalList.push({ name: k, available: available, n_matches: s.n_matches || 0, avg_probability: s.avg_probability || 0, weight: s.weight || 0 });
  });

  let html = '<div class="stats-row" id="statsRow">';
  html += '<div class="stat-card"><div class="val">' + d.n_teams + '</div><div class="lbl">Teams</div></div>';
  html += '<div class="stat-card"><div class="val">' + (d.n_played || 0) + '</div><div class="lbl">Matches Played</div></div>';
  html += '<div class="stat-card"><div class="val">' + signalList.filter(s => s.available).length + ' / ' + signalList.length + '</div><div class="lbl">Signals Available</div></div>';
  html += '</div>';

  if (signalList.length > 0) {
    html += '<div class="chart-section"><div class="title">Signal Cache Status</div><table class="eval-table"><tr><th>Signal</th><th>Available</th><th>Matches</th><th>Avg Prob</th><th>Weight</th></tr>';
    signalList.forEach(s => {
      const dot = s.available ? 'dot-green' : 'dot-red';
      const status = s.available ? 'Yes' : 'No';
      const label = sigLabelMap[s.name] || s.name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
      html += '<tr><td>' + label + '</td><td class="num"><span class="' + dot + '">&#9679;</span> ' + status + '</td><td class="num">' + s.n_matches + '</td><td class="num">' + (s.avg_probability || 0).toFixed(3) + '</td><td class="num">' + ((s.weight || 0) * 100).toFixed(1) + '%</td></tr>';
    });
    html += '</table></div>';
  }

  tab.innerHTML = html;
}

// ── League Table ──
function renderStandings() {
  const tab = document.getElementById("tab-standings");
  if (!tab) return;
  const st = appState.standings;
  if (!st || !st.length) {
    tab.innerHTML = '<div style="color:#15565B;font-size:12px">No standings data.</div>';
    return;
  }
  tab.innerHTML = `<div class="league-table-wrap"><table class="league-table">
    <tr><th>Pos</th><th>Team</th><th>Pld</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Zone</th></tr>
    ${st.map(r => {
      const zone = r.zone || "eliminated";
      const cls = zone === "top_8" ? "zone-top8" : zone === "playoff" ? "zone-playoff" : "";
      const zoneLabel = zone === "top_8" ? "TOP 8" : zone === "playoff" ? "PLAYOFF" : "OUT";
      const zoneCls = zone === "top_8" ? "top8" : zone === "playoff" ? "playoff" : "eliminated";
      const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
      const pld = (r.wins || 0) + (r.draws || 0) + (r.losses || 0);
      return '<tr class="' + cls + '"><td class="num">' + r.position + '</td><td>' + r.team + '</td><td class="num">' + pld + '</td><td class="num">' + (r.wins || 0) + '</td><td class="num">' + (r.draws || 0) + '</td><td class="num">' + (r.losses || 0) + '</td><td class="num">' + (r.gs || 0) + '</td><td class="num">' + (r.ga || 0) + '</td><td class="num">' + gd + '</td><td class="num">' + (r.pts !== undefined && r.pts !== null ? r.pts : "?") + '</td><td><span class="zone-badge ' + zoneCls + '">' + zoneLabel + '</span></td></tr>';
    }).join("")}
  </table></div>`;
}

// ── Bracket ──
function renderBracket() {
  const tab = document.getElementById("tab-bracket");
  if (!tab) return;
  const br = appState.bracket;
  if (!br) return;

  window.__bracketData = br.bracket_rounds || {};

  const playoff = br.playoff || [];
  const poHtml = playoff.length ? '<div class="g-title" style="color:#16A085;font-size:12px;margin-bottom:6px">Playoff Round (9-24)</div><div class="playoff-grid">' +
    playoff.map(t => {
      const aggStr = t.aggregate_a + "-" + t.aggregate_b;
      let detail = aggStr + " agg";
      if (t.et_played) detail += " (ET)";
      if (t.penalties_played) detail += " (pens)";
      return '<div class="playoff-card"><div class="p-title">Tie ' + t.tie_num + '</div><div class="p-teams"><span class="p-team winner">' + t.team_a + '</span><span class="p-score">' + aggStr + '</span><span class="p-team">' + t.team_b + '</span></div><div class="p-detail">' + detail + "</div></div>";
    }).join("") + "</div>" : "";

  const lmd = br.league_matchdays || {};
  const lmdKeys = Object.keys(lmd).sort();
  let mdHtml = "";
  if (lmdKeys.length) {
    mdHtml = '<div class="g-title" style="color:#16A085;font-size:12px;margin:8px 0 6px">League Phase</div>';
    mdHtml += '<div class="md-accordion">';
    const firstMid = lmdKeys[0];
    lmdKeys.forEach(md => {
      const ms = lmd[md] || [];
      const isFirst = md === firstMid;
      mdHtml += '<div class="md-card"><div class="md-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">' +
        '<span class="md-label">' + md + '</span><span class="md-count">' + ms.length + " matches</span>" +
        '<span class="md-arrow">' + (isFirst ? "\u25BC" : "\u25B6") + "</span></div>" +
        '<div class="md-body ' + (isFirst ? "open" : "") + '">' +
        ms.map(m => '<div class="md-row"><span class="md-team">' + m.team_a + '</span><span class="md-score">' + m.home_score + "-" + m.away_score + '</span><span class="md-team">' + m.team_b + "</span></div>").join("") +
        "</div></div>";
    });
    mdHtml += "</div>";
  }

  tab.innerHTML = '<div style="text-align:right;margin-bottom:8px"><button class="status-btn" onclick="window.__simulateAllRemaining()">&#9654; Simulate All Remaining</button></div>' + mdHtml + poHtml + '<div class="bracket-wrap"><div class="bracket-grid" id="bracketGrid"></div><svg class="bracket-svg" id="bracketSvg"></svg></div>';

  const rounds = br.bracket_rounds || {};
  const grid = document.getElementById("bracketGrid");
  if (!grid) return;

  const roundOrder = ["R16", "QF", "SF", "FINAL"];
  const roundLabel = { R16: "Round of 16", QF: "Quarter-Finals", SF: "Semi-Finals", FINAL: "Final" };
  const byId = {};
  for (const [, ms] of Object.entries(rounds)) for (const m of ms) byId[m.match_id] = m;

  function getLeafOrder(mid) {
    const m = byId[mid];
    if (!m || !m.source_matches) return [mid];
    return [...getLeafOrder(m.source_matches[0]), ...getLeafOrder(m.source_matches[1])];
  }
  const leafOrder = getLeafOrder("final_01");
  const leafIdx = {};
  leafOrder.forEach((id, i) => leafIdx[id] = i);

  function getRowRange(mid) {
    const m = byId[mid];
    if (!m) return { start: 0, end: 2 };
    if (m.round === "FINAL") return { start: 0, end: leafOrder.length };
    const leaves = getLeafOrder(mid);
    if (!leaves.length) return { start: 0, end: 2 };
    return { start: leafIdx[leaves[0]], end: leafIdx[leaves[leaves.length - 1]] + 1 };
  }

  const ROW_UNIT = 28;
  roundOrder.forEach((r, ri) => {
    const col = document.createElement("div");
    col.className = "bracket-col";
    col.style.flex = String(1 + (ri === roundOrder.length - 1 ? 0.5 : 0));
    col.innerHTML = '<div class="col-head">' + (roundLabel[r] || r) + "</div>";

    const ms = (rounds[r] || []).slice().sort((a, b) => getRowRange(a.match_id).start - getRowRange(b.match_id).start);
    let lastEnd = 0;
    ms.forEach(m => {
      const rr = getRowRange(m.match_id);
      const gap = rr.start - lastEnd;
      if (gap > 0) {
        const sp = document.createElement("div");
        sp.className = "match-slot";
        sp.style.minHeight = (gap * ROW_UNIT) + "px";
        col.appendChild(sp);
      }
      lastEnd = rr.end;

      const slot = document.createElement("div");
      slot.className = "match-slot";
      slot.style.minHeight = Math.max((rr.end - rr.start) * ROW_UNIT, 40) + "px";

      const ta = m.team_a || "TBD";
      const tb = m.team_b || "TBD";
      const isPlayed = m.winner ? true : false;
      const isTbd = !m.team_a && !m.team_b;
      let scoreStr, simProbHtml = "", simWinnerHtml = "";
      if (m.score) {
        scoreStr = m.score.home + "-" + m.score.away;
      } else if (isPlayed) {
        scoreStr = "1-0";
      } else if (!isPlayed && appState.simBracket) {
        const allSim = Object.values(appState.simBracket.bracket_rounds).flat();
        const sm = allSim.find(x => x.match_id === m.match_id);
        if (sm) {
          const r = sm.result;
          if (r && r.score_a != null) {
            scoreStr = r.score_a + "-" + r.score_b;
          } else if (r && r.aggregate_a != null) {
            scoreStr = r.aggregate_a + "-" + r.aggregate_b;
          } else if (sm.winner) {
            scoreStr = sm.winner === ta ? "1-0" : "0-1";
          } else {
            scoreStr = "?-?";
          }
          if (sm.winner) {
            simWinnerHtml = '<div class="m-winner-label" style="color:#8E44AD">' + sm.winner + ' (sim)</div>';
          }
        } else {
          scoreStr = "?-?";
        }
      } else {
        scoreStr = "?-?";
      }
      const cardClass = isTbd ? "tbd" : isPlayed ? "played" : "upcoming";

      slot.innerHTML = '<div class="match-card ' + cardClass + '" data-mid="' + m.match_id + '">' +
        '<div class="m-teams"><span class="m-team ' + (m.winner === ta ? "winner" : "") + '">' + ta + '</span>' +
        '<span class="m-score">' + scoreStr + '</span>' +
        '<span class="m-team ' + (m.winner === tb ? "winner" : "") + '">' + tb + '</span></div>' +
        (m.winner ? '<div class="m-winner-label">' + m.winner + " advances</div>" : "") +
        simWinnerHtml +
        "</div>";
      slot.querySelector(".match-card").onclick = () => openMatchModal(m);
      col.appendChild(slot);
    });
    grid.appendChild(col);
  });

  setTimeout(drawBracketConnectors, 50);
}

const sigLabels = {
  refined_elo: "Refined Elo", market_odds: "Market Odds", rolling_form: "Rolling Form",
  squad_value: "Squad Value", rest_days: "Rest Days", availability: "Availability",
  manager_effect: "Manager Effect", defensive_quality: "Defensive Quality",
  player_form: "Player Form", team_synergy: "Team Synergy",
};

const sigOrder = ["refined_elo", "rolling_form", "market_odds", "defensive_quality",
  "manager_effect", "squad_value", "player_form", "team_synergy", "availability", "rest_days"];

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
  try { insight = await (await fetch(API + "/match/insight?match_id=" + mid)).json(); } catch { insight = { error: "fetch failed" }; }
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
      <input type="text" id="modalWhatifInput" placeholder="Describe a scenario... (e.g. PSG weaker, Arsenal stronger)">
      <button onclick="window.__sendModalWhatIf('${mid}','${ta}','${tb}')">&#9654;</button>
    </div>
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
  const scenario = document.getElementById("modalWhatifInput").value.trim();
  const resultDiv = document.getElementById("modalWhatifResult");
  if (!scenario) { resultDiv.style.display = "none"; return; }
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<div style="color:#15565B;font-size:11px">Processing...</div>';
  try {
    const resp = await (await fetch(API + "/what-if", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: matchId, scenario }),
    })).json();
    let html = "";
    if (resp.insight) {
      html += '<div class="wir-insight">>> ' + resp.insight.replace(/ >> /g, "<br>>></div><div class=\"wir-insight\">>> ") + "</div>";
    }
    if (resp.adjusted_signals) {
      let sigDetail = "";
      Object.entries(resp.adjusted_signals).forEach(([sk, sv]) => {
        if (sv.was_adjusted) {
          const deltaStr = (sv.delta * 100).toFixed(1);
          const cls = sv.delta >= 0 ? "wir-diff-pos" : "wir-diff-neg";
          sigDetail += '<div class="wir-sig-row"><span>' + sk + '</span><span class="wir-bar-wrap"><span class="wir-bar" style="width:' + (sv.probability * 100) + '%"></span></span><span class="wir-val">' + (sv.probability * 100).toFixed(1) + '%</span><span class="' + cls + '">' + (sv.delta >= 0 ? "+" : "") + deltaStr + '%</span></div>';
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
    resultDiv.innerHTML = html || '<div style="color:#15565B;font-size:11px">No adjustment triggered for this scenario.</div>';
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




