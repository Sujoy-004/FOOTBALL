// ── UCL 2025/26 Module ──
import {
  termAdd, termScroll, termShowPrompt, termRenderBootStep, termBooting,
  wireTerminal, buildTable, destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions,
} from "./shared.js";

const API = "/ucl/api";
const appState = { data: null, standings: [], bracket: null, odds: [], signals: {}, matches: [] };

let pollTimer = null;
let simTaskId = null;

export function init(comp) {
  renderTerminalShell();
  wireTerminal(termExec);
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
      <input id="terminal-input" type="text" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0">
    </div>
  `;
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
  try { renderOdds(); } catch (e) { console.error("renderOdds:", e); }
  try { renderSignals(); } catch (e) { console.error("renderSignals:", e); }
  try { updateStatus(); } catch (e) { console.error("updateStatus:", e); }
}

function updateStatus() {
  const d = appState.data;
  if (!d) return;
  const mode = d.mode || "simulation";
  const modeLabel = mode === "results" ? "Live Results 2025/26" : "MC Simulation";
  const modeColor = mode === "results" ? "#168777" : "#15565B";
  const rightHtml = (mode === "results"
    ? '<input id="simIterInput" type="number" min="10" max="1000000" step="1000" value="10000" style="width:80px;font-size:11px;padding:2px 4px;margin-right:4px;background:#0D1B2A;border:1px solid #15565B;color:#fff;border-radius:3px;text-align:right">'
    + '<span style="color:#15565B;font-size:10px;margin-right:6px">sims</span>'
    + '<button class="status-btn" onclick="window.__runSimulation()">>> Run Simulation</button>'
    : '<button class="status-btn" onclick="window.__resetResults()">>> Back to Real Results</button>');
  updateStatusBar(
    '<span style="color:' + modeColor + '">' + modeLabel + '</span>  |  ' + d.n_teams + " teams  |  " + d.n_iterations.toLocaleString() + (mode === "results" ? "" : " sims"),
    rightHtml
  );
}

window.__runSimulation = async function () {
  try {
    const nIter = Math.max(10, Math.min(1000000, parseInt(document.getElementById("simIterInput")?.value) || 10000));
    const resp = await (await fetch(API + "/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ n_iterations: nIter }),
    })).json();
    if (resp.status === "error") {
      console.error("Simulation error:", resp.error);
      updateStatusBar(
        document.getElementById("statusLeft")?.textContent || "",
        '<span style="color:#ff6b6b;font-size:11px">Simulation failed: ' + resp.error + "</span>"
      );
      return;
    }
    const taskId = resp.task_id;
    showSimProgress(true);
    pollSimProgress(taskId);
  } catch (e) {
    console.error("Simulation failed:", e);
  }
};

// ── Simulation Progress Bar ──
function showSimProgress(visible) {
  let el = document.getElementById("simProgress");
  if (visible && !el) {
    const overview = document.getElementById("tab-overview");
    if (!overview) return;
    el = document.createElement("div");
    el.id = "simProgress";
    el.style.cssText = "margin:8px 16px;padding:8px 12px;background:#0D1B2A;border-radius:6px";
    el.innerHTML = [
      '<div style="display:flex;justify-content:space-between;font-size:10px;color:#15565B;margin-bottom:4px">',
      '  <span id="simProgressLabel">Starting simulation...</span>',
      '  <span id="simProgressPct">0%</span>',
      '</div>',
      '<div style="background:#0A1423;border-radius:4px;height:12px;overflow:hidden">',
      '  <div id="simProgressBar" style="background:#16A085;height:100%;width:0%;transition:width 0.3s"></div>',
      '</div>',
    ].join("");
    const target = overview.querySelector(".team-cards") || overview.querySelector(".stats-row");
    if (target && target.nextSibling) {
      overview.insertBefore(el, target.nextSibling);
    } else {
      overview.appendChild(el);
    }
  }
  if (el) el.style.display = visible ? "block" : "none";
}

function pollSimProgress(taskId) {
  const startTime = Date.now();
  const timer = setInterval(async () => {
    try {
      const resp = await (await fetch(API + "/simulation/progress/" + taskId)).json();
      if (resp.error) { clearInterval(timer); showSimProgress(false); return; }
      const pct = resp.progress || 0;
      const bar = document.getElementById("simProgressBar");
      const label = document.getElementById("simProgressLabel");
      const pctEl = document.getElementById("simProgressPct");
      if (bar) bar.style.width = pct + "%";
      if (pctEl) pctEl.textContent = Math.round(pct) + "%";
      if (label) {
        const iter = resp.iteration || 0;
        const total = resp.total_iterations || 0;
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        const eta = pct > 0 && pct < 100
          ? Math.round(elapsed / pct * (100 - pct))
          : 0;
        let text = "";
        if (total > 0 && pct < 85) {
          text = iter.toLocaleString() + " / " + total.toLocaleString() + " sims";
        } else if (pct < 100) {
          text = "Building results...";
        } else {
          text = "Complete!";
        }
        if (elapsed > 0) text += "  elapsed " + elapsed + "s";
        if (eta > 0) text += "  ETA " + eta + "s";
        label.textContent = text;
      }
      if (resp.status === "complete") {
        clearInterval(timer);
        showSimProgress(false);
        await reloadData();
      } else if (resp.status === "error") {
        clearInterval(timer);
        showSimProgress(false);
        updateStatusBar(
          document.getElementById("statusLeft")?.textContent || "",
          '<span style="color:#ff6b6b;font-size:11px">Simulation failed: ' + (resp.error || "Unknown error") + "</span>"
        );
      }
    } catch (e) {
      clearInterval(timer);
      showSimProgress(false);
    }
  }, 200);
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
    renderOdds(); renderSignals(); updateStatus();
  } catch (e) {
    console.error("reloadData failed:", e);
  }
}

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
    renderOdds(); renderSignals(); updateStatus();
  } catch (e) {
    console.error("Reset failed:", e);
  }
};

// ── Overview ──
function renderOverview() {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const d = appState.data;
  if (!d) return;
  const mode = d.mode || "simulation";
  const champ = d.champion || "—";
  const champData = d.all_teams && d.all_teams.length ? d.all_teams[0] : null;
  const champPct = champData ? (mode === "results" ? "100.0" : (champData.champion_prob * 100).toFixed(1)) : "?";
  const subtitle = mode === "results" ? "Actual Champion 2025/26" : "champion probability";
  const sigCount = Object.keys(appState.signals).length;
  const top4 = (d.teams || []).slice(0, 4);
  const ringColors = ["#168777", "#156F69", "#15565B", "#153D4C"];
  const stageKeys = ["qf_prob", "sf_prob", "final_prob", "champion_prob"];
  const allTeams = d.all_teams || [];
  const sigs = appState.signals;
  const sigKeys = Object.keys(sigs);

  tab.innerHTML = `
    <div class="stats-row">
      <div class="stat-card"><div class="val">${d.n_teams}</div><div class="lbl">Teams</div></div>
      <div class="stat-card"><div class="val">${d.n_iterations.toLocaleString()}</div><div class="lbl">${mode === "results" ? "Matchdays" : "Simulations"}</div></div>
      <div class="stat-card"><div class="val">${sigCount}</div><div class="lbl">Active Signals</div></div>
      <div class="stat-card"><div class="val">${champData ? champData.team.split(" ").pop() : champ}</div><div class="lbl">Champion</div><div class="sub">${subtitle}: ${champPct}%</div></div>
    </div>
    <div class="team-cards">
      ${top4.map(t => {
        const full = (d.all_teams || []).find(x => x.team === t.team) || t;
        return '<div class="team-card"><div class="name">' + full.team + '</div><div class="elo">Avg pos ' + (full.avg_position || "?").toFixed(1) + '</div><div class="ring-row">' +
          stageKeys.map((k, i) => {
            const pct = (full[k] || 0) * 100;
            const label = k === "champion_prob" ? "Champ" : k.replace("_prob", "").toUpperCase();
            return '<div><div class="ring"><div class="ring-fill" style="width:' + Math.max(2, pct) + '%;background:' + ringColors[i] + '"></div></div><div class="ring-lbl">' + label + '</div></div>';
          }).join("") + '</div></div>';
      }).join("")}
    </div>
    <div class="chart-section" id="chartSection">
      <div class="title">Champion Probability</div>
      ${allTeams.length > 0 ? (() => {
        const top10 = allTeams.slice(0, 10);
        const maxC = Math.max(0.01, top10[0].champion_prob);
        return top10.map(t => '<div class="chart-row"><div class="cname">' + t.team + '</div><div class="cbar-wrap"><div class="cbar" style="width:' + (t.champion_prob / maxC * 100) + '%"></div></div><div class="cpct">' + (t.champion_prob * 100).toFixed(1) + '%</div></div>').join("");
      })() : ""}
    </div>
    <div class="chart-section" id="evalSection">
      <div class="title">Signal Statistics</div>
      ${sigKeys.length > 0 ? (() => {
        let h = '<table class="eval-table"><tr><th>Signal</th><th>Avg Prob</th><th>Matches</th><th>Available</th><th>Weight</th></tr>';
        sigKeys.forEach(k => {
          const s = sigs[k];
          h += '<tr><td>' + k + '</td><td class="num">' + (s.avg_probability || 0).toFixed(3) + '</td><td class="num">' + s.n_matches + '</td><td class="num">' + (s.available_pct || 0) + '%</td><td class="num">' + ((s.weight || 0) * 100).toFixed(1) + '%</td></tr>';
        });
        return h + "</table>";
      })() : '<div style="color:#15565B;font-size:11px">No signal data available.</div>'}
    </div>
  `;
}

// ── League Table ──
function renderStandings() {
  const tab = document.getElementById("tab-leaguetable");
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

  tab.innerHTML = mdHtml + poHtml + '<div class="bracket-wrap"><div class="bracket-grid" id="bracketGrid"></div><svg class="bracket-svg" id="bracketSvg"></svg></div>';

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
      const scoreStr = m.score ? m.score.home + "-" + m.score.away : (m.result && m.result.score_a !== undefined ? m.result.score_a + "-" + m.result.score_b : "?-?");
      const isPlayed = m.winner ? true : false;
      const isTbd = !m.team_a && !m.team_b;
      const cardClass = isTbd ? "tbd" : isPlayed ? "played" : "upcoming";

      slot.innerHTML = '<div class="match-card ' + cardClass + '" data-mid="' + m.match_id + '">' +
        '<div class="m-teams"><span class="m-team ' + (m.winner === ta ? "winner" : "") + '">' + ta + '</span>' +
        '<span class="m-score">' + scoreStr + '</span>' +
        '<span class="m-team ' + (m.winner === tb ? "winner" : "") + '">' + tb + '</span></div>' +
        (m.winner ? '<div class="m-winner-label">' + m.winner + " advances</div>" : "") +
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

// ── What-If Page ──
function populateWhatIfSelectors() {
  const matches = appState.matches;
  const roundSel = document.getElementById("whatifRound");
  const matchSel = document.getElementById("whatifMatch");
  if (!roundSel || roundSel.options.length > 1) return;

  const rounds = [...new Set(matches.map(m => m.round))];
  rounds.forEach(r => {
    const opt = document.createElement("option");
    opt.value = r; opt.textContent = r;
    roundSel.appendChild(opt);
  });

  roundSel.onchange = () => {
    const r = roundSel.value;
    matchSel.innerHTML = '<option value="">-- Match --</option>';
    matches.filter(m => m.round === r).forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.match_id;
      opt.textContent = (m.team_a || "TBD") + " vs " + (m.team_b || "TBD");
      matchSel.appendChild(opt);
    });
    updateMatchInfo();
  };
  matchSel.onchange = updateMatchInfo;
}

function updateMatchInfo() {
  const matchId = document.getElementById("whatifMatch").value;
  const info = document.getElementById("whatifMatchInfo");
  if (!matchId || !info) { if (info) info.textContent = ""; return; }
  const m = appState.matches.find(x => x.match_id === matchId);
  if (m) info.textContent = m.round + " — " + (m.team_a || "TBD") + " vs " + (m.team_b || "TBD");
}

window.__sendUclWhatIf = async function (mode) {
  const matchId = document.getElementById("whatifMatch").value;
  const scenario = document.getElementById("whatifInput").value.trim();
  const resultDiv = document.getElementById("whatifResult");
  if (!matchId || !scenario) { resultDiv.style.display = "none"; return; }

  resultDiv.style.display = "none";
  resultDiv.innerHTML = "";
  const progressWrap = document.getElementById("whatifProgress");
  const progressBar = document.getElementById("whatifProgressBar");
  const progressText = document.getElementById("whatifProgressText");

  if (mode === "simulate") {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    progressWrap.style.display = "block";
    progressBar.style.width = "0%";
    progressText.textContent = "Starting...";

    try {
      const startResp = await (await fetch(API + "/what-if", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: matchId, scenario, mode: "simulate" }),
      })).json();

      if (startResp.error) {
        resultDiv.style.display = "block";
        resultDiv.innerHTML = '<div style="color:#ff6b6b">' + startResp.error + "</div>";
        progressWrap.style.display = "none";
        return;
      }

      simTaskId = startResp.task_id;
      pollTimer = setInterval(async () => {
        try {
          const pResp = await (await fetch(API + "/simulation/progress/" + simTaskId)).json();
          if (pResp.error) {
            clearInterval(pollTimer); pollTimer = null;
            progressWrap.style.display = "none";
            resultDiv.style.display = "block";
            resultDiv.innerHTML = '<div style="color:#ff6b6b">' + pResp.error + "</div>";
            return;
          }
          const pct = pResp.progress || 0;
          const iter = pResp.iteration || 0;
          const total = pResp.total_iterations || 0;
          progressBar.style.width = pct + "%";
          const elapsed = total > 0 && pct > 0
            ? Math.round((Date.now() - startTime) / 1000)
            : 0;
          const eta = total > 0 && pct > 0 && pct < 100
            ? Math.round((Date.now() - startTime) / pct * (100 - pct) / 1000)
            : 0;
          progressText.textContent = iter.toLocaleString() + " / " + total.toLocaleString() + " (" + pct + "%)"
            + (elapsed > 0 ? "  elapsed " + elapsed + "s" : "")
            + (eta > 0 ? "  ETA " + eta + "s" : "");

          if (pResp.status === "complete") {
            clearInterval(pollTimer); pollTimer = null;
            progressWrap.style.display = "none";
            resultDiv.style.display = "block";
            let html = "";
            if (pResp.insight) {
              html += '<div class="wir-insight">>> ' + pResp.insight.replace(/ >> /g, "<br>>></div><div class=\"wir-insight\">>> ") + "</div>";
            }
            if (pResp.result) {
              const r = pResp.result;
              if (r.baseline && r.adjusted) {
                Object.keys(r.baseline).forEach(t => {
                  const base = (r.baseline[t] * 100).toFixed(1);
                  const adj = (r.adjusted[t] * 100).toFixed(1);
                  const cls = adj >= base ? "wir-diff-pos" : "wir-diff-neg";
                  html += '<div class="wir-row"><span class="wir-label">' + t + '</span><span class="wir-val ' + cls + '">' + base + '% &#8594; ' + adj + '%</span></div>';
                });
              }
            }
            resultDiv.innerHTML = html;
          }
          if (pResp.status === "error") {
            clearInterval(pollTimer); pollTimer = null;
            progressWrap.style.display = "none";
            resultDiv.style.display = "block";
            resultDiv.innerHTML = '<div style="color:#ff6b6b">' + (pResp.error || "Simulation error") + "</div>";
          }
        } catch (e) {
          clearInterval(pollTimer); pollTimer = null;
          progressWrap.style.display = "none";
        }
      }, 200);
      const startTime = Date.now();
    } catch (e) {
      progressWrap.style.display = "none";
      resultDiv.style.display = "block";
      resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + "</div>";
    }
    return;
  }

  try {
    const resp = await (await fetch(API + "/what-if", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: matchId, scenario }),
    })).json();

    resultDiv.style.display = "block";

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

    if (!resp.insight && resp.original_prob_a !== undefined) {
      const deltaCls = resp.delta >= 0 ? "wir-diff-pos" : "wir-diff-neg";
      const deltaSign = resp.delta >= 0 ? "+" : "";
      html = '<div class="wir-row"><span class="wir-label">Original</span><span class="wir-val">' + (resp.team_a || "A") + " " + (resp.original_prob_a * 100).toFixed(1) + '%</span></div>' +
        '<div class="wir-row"><span class="wir-label">After scenario</span><span class="wir-val ' + deltaCls + '">' + (resp.team_a || "A") + " " + (resp.adjusted_prob_a * 100).toFixed(1) + '% <span class="' + deltaCls + '">(' + deltaSign + resp.delta_pct + '%)</span></span></div>';
    }

    resultDiv.innerHTML = html;
  } catch (e) {
    resultDiv.style.display = "block";
    resultDiv.innerHTML = '<div style="color:#ff6b6b">Error: ' + e.message + "</div>";
  }
};

function renderWhatIf() {
  const tab = document.getElementById("tab-whatif");
  if (!tab) return;
  const matches = appState.matches;
  if (!matches || !matches.length) {
    tab.innerHTML = '<div style="color:#15565B;font-size:12px;padding:12px">No match data available. Run a simulation first.</div>';
    return;
  }
  tab.innerHTML = `
    <div class="whatif-controls">
      <select id="whatifRound"><option value="">-- Round --</option></select>
      <select id="whatifMatch"><option value="">-- Match --</option></select>
      <input type="text" id="whatifInput" placeholder="Scenario (e.g. Man City stronger)">
      <button onclick="window.__sendUclWhatIf('instant')" title="Instant (signal-only)">&#9654;</button>
      <button onclick="window.__sendUclWhatIf('simulate')" title="Full MC re-simulation" style="margin-left:4px">&#9654;&#9654;</button>
    </div>
    <div id="whatifMatchInfo" style="color:#15565B;font-size:11px;margin-bottom:6px;"></div>
    <div id="whatifProgress" style="display:none;margin:6px 0">
      <div style="background:#0D1B2A;border-radius:4px;height:16px;overflow:hidden">
        <div id="whatifProgressBar" style="background:#16A085;height:100%;width:0%;transition:width 0.2s"></div>
      </div>
      <div id="whatifProgressText" style="color:#15565B;font-size:10px;margin-top:2px"></div>
    </div>
    <div class="whatif-result" id="whatifResult"></div>
  `;
  populateWhatIfSelectors();
}

// ── Terminal ──
function buildUCLTable(teams, cols) {
  const show = cols || ["champion_prob", "final_prob", "sf_prob", "qf_prob"];
  const labels = { champion_prob: "Champion", final_prob: "Final", sf_prob: "SF", qf_prob: "QF" };
  let h = "<tr><th>#</th><th>Team</th>";
  show.forEach(c => h += "<th>" + (labels[c] || c) + "</th>");
  h += "</tr>";
  let html = "<table>" + h;
  teams.forEach((t, i) => {
    html += '<tr><td class="num">' + (i + 1) + "</td><td>" + t.team + "</td>";
    show.forEach(c => html += '<td class="num">' + ((t[c] || 0) * 100).toFixed(1) + "%</td>");
    html += "</tr>";
  });
  return html + "</table>";
}

async function termBoot() {
  termBooting = true;
  termAdd('<span class="title">>> UCL 2025/26 — Champions League Predictor</span>');
  termAdd('<span class="banner">+------------------------------------+\n|      MONTE CARLO SIMULATION        |\n|      10 000 iterations             |\n+------------------------------------+</span>');
  termAdd("");

  let bootSteps;
  try { bootSteps = await (await fetch(API + "/boot")).json(); }
  catch { termAdd('<span class="danger">ERROR: Server unreachable.</span>'); termShowPrompt(); termBooting = false; return; }

  for (const step of bootSteps) await termRenderBootStep(step);
  termAdd("");

  const d = appState.data;
  if (d && d.all_teams) {
    termAdd('<span class="highlight">== Champion Probability Table ==</span>');
    termAdd("");
    termAdd(buildUCLTable(d.all_teams));
    termAdd("");
    termAdd('<span class="dim">>> System ready. ' + d.n_teams + " teams simulated. Type help to explore.</span>");
  } else {
    termAdd('<span class="danger">ERROR: Failed to load prediction data.</span>');
  }
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
    termAdd('<span class="prompt">table</span>       - full 36-team league table.');
    termAdd('<span class="prompt">odds</span>        - champion/qualification odds.');
    termAdd('<span class="prompt">bracket</span>     - knockout bracket rounds.');
    termAdd('<span class="prompt">playoff</span>     - playoff round results.');
    termAdd('<span class="prompt">signals</span>     - signal blend statistics.');
    termAdd('<span class="prompt">champion</span>    - show champion prediction.');
    termAdd('<span class="prompt">clear</span>       - reset screen.');
    termAdd('<span class="prompt">help</span>        - this message.');
    termAdd("");
  } else if (main === "clear") {
    document.getElementById("termOutput").innerHTML = "";
    termAdd('<span class="banner">+------------------------------------+\n|      MONTE CARLO SIMULATION        |\n|     ' + String((d ? d.n_iterations.toLocaleString() : "—")).padStart(10) + ' iterations           |\n+------------------------------------+</span>');
    termAdd("");
  } else if (main === "top") {
    const n = parseInt(parts[1]) || 5;
    const teams = (d && d.all_teams) ? d.all_teams.slice(0, Math.min(n, d.all_teams.length)) : [];
    if (!teams.length) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Top ' + teams.length + " -- Champion Probability ==</span>");
    termAdd(buildUCLTable(teams));
    termAdd("");
  } else if (main === "table") {
    const st = appState.standings;
    if (!st || !st.length) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== League Table (36 teams) ==</span>');
    let tbl = '<table><tr><th>Pos</th><th>Team</th><th>Pts</th><th>GD</th><th>GS</th><th>Zone</th></tr>';
    st.forEach(r => {
      const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
      tbl += '<tr><td class="num">' + r.position + '</td><td>' + r.team + '</td><td class="num">' + (r.pts !== null && r.pts !== undefined ? r.pts : "?") + '</td><td class="num">' + gd + '</td><td class="num">' + (r.gs || 0) + '</td><td>' + (r.zone || "") + "</td></tr>";
    });
    termAdd(tbl + "</table>");
    termAdd("");
  } else if (main === "odds") {
    const odds = appState.odds;
    if (!odds || !odds.length) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Champion / Qualification Odds ==</span>');
    termAdd(buildUCLTable(odds));
    termAdd("");
  } else if (main === "bracket") {
    const br = appState.bracket;
    if (!br) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    const rounds = br.bracket_rounds || {};
    termAdd("");
    termAdd('<span class="highlight">== Knockout Bracket ==</span>');
    const roundOrder = ["R16", "QF", "SF", "FINAL"];
    roundOrder.forEach(r => {
      const ms = rounds[r] || [];
      if (!ms.length) return;
      termAdd('<span class="highlight">--- ' + r + " ---</span>");
      ms.forEach(m => {
        const scoreStr = m.score ? m.score.home + "-" + m.score.away : (m.result && m.result.score_a !== undefined ? m.result.score_a + "-" + m.result.score_b + " agg" : "?-?");
        termAdd("  " + (m.team_a || "TBD") + " " + scoreStr + "  " + (m.team_b || "TBD") + (m.winner ? " -> " + m.winner : ""));
      });
    });
    const po = br.playoff || [];
    if (po.length) {
      termAdd("");
      termAdd('<span class="highlight">--- Playoff Results ---</span>');
      po.forEach(t => termAdd("  Tie " + t.tie_num + ": " + t.team_a + " " + t.aggregate_a + "-" + t.aggregate_b + " " + t.team_b + (t.et_played ? " (ET)" : "") + (t.penalties_played ? " (pens)" : "") + " -> " + t.winner));
    }
    termAdd("");
  } else if (main === "playoff") {
    const po = (appState.bracket && appState.bracket.playoff) || [];
    if (!po.length) { termAdd("No data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Playoff Round (9-24) ==</span>');
    po.forEach(t => termAdd("  Tie " + t.tie_num + ": " + t.team_a + " " + t.aggregate_a + "-" + t.aggregate_b + " " + t.team_b + " -> " + t.winner));
    termAdd("");
  } else if (main === "signals") {
    const sigs = appState.signals;
    const keys = Object.keys(sigs);
    if (!keys.length) { termAdd("No signal data.", "dim"); termShowPrompt(); return; }
    termAdd("");
    termAdd('<span class="highlight">== Signal Blend Status ==</span>');
    let tbl = '<table><tr><th>Signal</th><th>Avg Prob</th><th>Matches</th><th>Avail</th><th>Weight</th></tr>';
    keys.forEach(k => {
      const s = sigs[k];
      tbl += '<tr><td>' + k + '</td><td class="num">' + (s.avg_probability || 0).toFixed(3) + '</td><td class="num">' + s.n_matches + '</td><td class="num">' + (s.available_pct || 0) + '%</td><td class="num">' + ((s.weight || 0) * 100).toFixed(1) + "%</td></tr>";
    });
    termAdd(tbl + "</table>");
    termAdd("");
  } else if (main === "champion") {
    const ch = d ? d.champion : null;
    const top = appState.odds && appState.odds.length ? appState.odds[0] : null;
    termAdd("");
    if (ch) termAdd('Representative champion: <span class="highlight">' + ch + "</span>");
    if (top) termAdd('Probability favorite:   <span class="highlight">' + top.team + "</span> (" + (top.champion_prob * 100).toFixed(1) + "%)");
    else termAdd('<span class="dim">No champion data available.</span>');
    termAdd("");
  } else {
    termAdd("command not found: " + trimmed, "danger");
    termAdd('Type <span class="prompt">help</span> for available commands.', "dim");
  }
  termShowPrompt();
}
