// ── World Cup 2026 Module ──
import {
  termAdd, termScroll, termShowPrompt, termRenderBootStep, termBooting,
  wireTerminal, buildTable, destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions,
} from "./shared.js";

const API = "/worldcup/api";
const sigLabels = { elo: "Elo", form: "Form", lineup_strength: "Lineup", defensive_quality: "Defense", manager_effect: "Manager", market_odds: "Odds", catboost: "CatBoost" };
const appState = { data: null, standings: null, bracket: null, fullBracket: null, eval: null, blend: null, signalCache: {} };
let initialLoad = true;
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
  const [d, s, fb, ev, bl] = await Promise.all([
    fetch(API + "/data").then(r => r.json()),
    fetch(API + "/standings").then(r => r.json()),
    fetch(API + "/bracket/full").then(r => r.json()),
    fetch(API + "/evaluation").then(r => r.json()),
    fetch(API + "/blend").then(r => r.json()),
  ]);
  appState.data = d;
  appState.standings = s;
  appState.fullBracket = fb;
  appState.eval = ev;
  appState.blend = bl;
  renderDashboard();
  renderStandings();
  renderBracket();
  updateStatus();
  const sigNames = Object.keys(bl.blend_weights || {});
  sigNames.forEach(async name => {
    try { appState.signalCache[name] = await (await fetch(API + "/signal/" + name)).json(); } catch {}
  });
  if (initialLoad) {
    initialLoad = false;
    doRefresh();
  }
}

let refreshProgressEl = null;

function refreshProgressHTML() {
  return '<div id="wcRefreshProgress" class="progress-bar-wrap" style="display:flex;margin:0 0 4px">' +
    '<div class="progress-bar-fill" id="wcRefreshFill" style="width:0%"></div>' +
    '</div><div class="progress-lbl" id="wcRefreshLbl" style="font-size:9px;margin-bottom:2px">Starting...</div>';
}

function updateStatus() {
  const d = appState.data;
  if (!d) return;
  if (refreshing) return;
  const btn = '<button class="status-btn" onclick="window.__refreshWC()">>> Refresh</button>';
  updateStatusBar(
    ">> " + d.n_teams + " teams  |  " + d.n_played + " matches played  |  " + d.total_iterations.toLocaleString() + " sims",
    btn + (autoRefreshOn ? '  <span style="color:#168777;font-size:10px">auto</span>' : "")
  );
}

async function doRefresh() {
  if (refreshing) return;
  refreshing = true;

  const statusEl = document.getElementById("statusBar");
  if (statusEl) {
    const prog = document.getElementById("wcRefreshProgress");
    if (!prog) {
      statusEl.insertAdjacentHTML("beforebegin", refreshProgressHTML());
    } else {
      prog.style.display = "flex";
      document.getElementById("wcRefreshFill").style.width = "0%";
      document.getElementById("wcRefreshLbl").textContent = "Starting...";
    }
  }

  try {
    const { task_id } = await (await fetch(API + "/refresh", { method: "POST" })).json();
    if (!task_id) throw new Error("no task_id");

    await new Promise((resolve, reject) => {
      const poll = setInterval(async () => {
        try {
          const p = await (await fetch(API + "/refresh/progress/" + task_id)).json();
          if (p.error) { clearInterval(poll); reject(new Error(p.error)); return; }
          const fill = document.getElementById("wcRefreshFill");
          const lbl = document.getElementById("wcRefreshLbl");
          if (fill) fill.style.width = p.progress + "%";
          if (lbl) lbl.textContent = (p.stage || "Working...") + "  " + Math.round(p.progress) + "%";
          if (p.status === "complete") {
            clearInterval(poll);
            resolve(p.result || {});
          }
          if (p.status === "error") {
            clearInterval(poll);
            reject(new Error(p.error || "refresh failed"));
          }
        } catch (e) {
          clearInterval(poll);
          reject(e);
        }
      }, 300);
    });

    await loadAll();
    const prog = document.getElementById("wcRefreshProgress");
    if (prog) prog.style.display = "none";
    const btn = '<button class="status-btn" onclick="window.__refreshWC()">>> Refresh</button>';
    updateStatusBar('<span style="color:#168777">Refresh complete</span>', btn);
    setTimeout(() => updateStatus(), 3000);
  } catch (e) {
    const prog = document.getElementById("wcRefreshProgress");
    if (prog) prog.style.display = "none";
    const btn = '<button class="status-btn" onclick="window.__refreshWC()">>> Refresh</button>';
    updateStatusBar('<span style="color:#ff6b6b">Refresh failed: ' + (e.message || "") + '</span>', btn);
    setTimeout(() => updateStatus(), 5000);
  }
  refreshing = false;
}
window.__refreshWC = doRefresh;

function toggleAuto(on) {
  autoRefreshOn = on;
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  if (on) autoTimer = setInterval(() => doRefresh(), 60000);
  updateStatus();
}

// ── Dashboard ──
function renderDashboard() {
  const tab = document.getElementById("tab-dashboard");
  if (!tab) return;
  const d = appState.data;
  if (!d) return;
  const sigs = appState.eval ? Object.keys(appState.eval).filter(k => appState.eval[k].n_matches > 0).length : 0;
  const top4 = d.teams.slice(0, 4);
  const ringColors = ["#168777", "#156F69", "#15565B", "#153D4C"];
  const top10 = d.teams.slice(0, 10);
  const maxC = top10[0].champion;
  const ev = appState.eval;

  tab.innerHTML = `
    <div class="stats-row" id="statsRow">
      <div class="stat-card"><div class="val">${d.n_teams}</div><div class="lbl">Teams</div></div>
      <div class="stat-card"><div class="val">${d.n_played}</div><div class="lbl">Played</div><div class="sub">${d.total_iterations.toLocaleString()} simulations</div></div>
      <div class="stat-card"><div class="val">${sigs}</div><div class="lbl">Active Signals</div></div>
      <div class="stat-card"><div class="val">${d.teams[0].name.split(" ").pop()}</div><div class="lbl">Leader</div><div class="sub">${d.teams[0].champion}% champion</div></div>
    </div>
    <div class="team-cards" id="teamCards">
      ${top4.map(t => `
        <div class="team-card">
          <div class="name">${t.name}</div>
          <div class="elo">Elo ${t.elo}</div>
          <div class="ring-row">
            ${["qf","sf","final","champion"].map((k,i) => `
              <div><div class="ring"><div class="ring-fill" style="width:${t[k]}%;background:${ringColors[i]}"></div></div>
              <div class="ring-lbl">${k==="champion"?"Champ":k.toUpperCase()}</div></div>
            `).join("")}
          </div>
        </div>
      `).join("")}
    </div>
    <div class="chart-section" id="chartSection">
      <div class="title">Champion Probability</div>
      ${top10.map(t => `
        <div class="chart-row">
          <div class="cname">${t.name}</div>
          <div class="cbar-wrap"><div class="cbar" style="width:${(t.champion/maxC*100)}%"></div></div>
          <div class="cpct">${t.champion}%</div>
        </div>
      `).join("")}
    </div>
    <div class="chart-section" id="evalSection">
      <div class="title">Signal Accuracy</div>
      ${ev ? (() => {
        const keys = Object.keys(ev).filter(k => ev[k].n_matches > 0);
        let h = '<table class="eval-table"><tr><th>Signal</th><th>Brier</th><th>Accuracy</th><th>N</th><th></th></tr>';
        keys.forEach(k => {
          const s = ev[k];
          const dot = s.brier < 0.15 ? "dot-green" : s.brier < 0.25 ? "dot-orange" : "dot-red";
          const status = s.brier < 0.15 ? "Calibrated" : s.brier < 0.25 ? "Adequate" : "Uncalibrated";
          h += `<tr><td>${k}</td><td class="num">${s.brier.toFixed(4)}</td><td class="num">${(s.accuracy*100).toFixed(1)}%</td><td class="num">${s.n_matches}</td><td class="num"><span class="${dot}">&#9679;</span> ${status}</td></tr>`;
        });
        return h + "</table>";
      })() : ""}
    </div>
  `;
}

// ── Bracket ──
function renderBracket() {
  const tab = document.getElementById("tab-bracket");
  if (!tab) return;
  const fb = appState.fullBracket;
  if (!fb || !fb.rounds) return;
  const rounds = ["R32", "R16", "QF", "SF", "TPP", "FINAL"];
  const roundLabel = { R32: "Round of 32", R16: "Round of 16", QF: "Quarter-Finals", SF: "Semi-Finals", TPP: "3rd Place", FINAL: "Final" };

  // Store for shared connector drawing
  window.__bracketData = fb.rounds;

  tab.innerHTML = `
    <div class="bracket-wrap">
      <div class="bracket-grid" id="bracketGrid"></div>
      <svg class="bracket-svg" id="bracketSvg"></svg>
    </div>
  `;

  const grid = document.getElementById("bracketGrid");
  const byId = {};
  for (const [, ms] of Object.entries(fb.rounds)) for (const m of ms) byId[m.match_id] = m;

  function getLeafOrder(mid) {
    const m = byId[mid];
    if (!m || !m.source_matches) return [mid];
    return [...getLeafOrder(m.source_matches[0]), ...getLeafOrder(m.source_matches[1])];
  }
  const leafOrder = getLeafOrder("FINAL");
  const leafIdx = {};
  leafOrder.forEach((id, i) => leafIdx[id] = i);

  function getRowRange(mid) {
    const m = byId[mid];
    if (!m) return { start: 0, end: 2 };
    if (m.round === "FINAL" || m.round === "TPP") return { start: 0, end: leafOrder.length };
    const leaves = getLeafOrder(mid);
    if (leaves.length === 0) return { start: 0, end: 2 };
    return { start: leafIdx[leaves[0]], end: leafIdx[leaves[leaves.length - 1]] + 1 };
  }

  const ROW_UNIT = 28;
  rounds.forEach((r, ri) => {
    const col = document.createElement("div");
    col.className = "bracket-col";
    col.style.flex = String(1 + (ri === rounds.length - 1 ? 0.5 : 0));
    col.innerHTML = '<div class="col-head">' + (roundLabel[r] || r) + "</div>";

    const ms = (fb.rounds[r] || []).slice().sort((a, b) => {
      return getRowRange(a.match_id).start - getRowRange(b.match_id).start;
    });

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
      const scoreStr = m.score ? m.score.home + "-" + m.score.away : "?-?";
      const isPlayed = m.played;
      const isTbd = !m.team_a && !m.team_b;
      const cardClass = isTbd ? "tbd" : isPlayed ? "played" : "upcoming";
      const probStr = m.prob_a != null ? (m.prob_a * 100).toFixed(1) + "%" : "";
      const wStr = m.winner ? m.winner + " won" : "";

      slot.innerHTML = `
        <div class="match-card ${cardClass}" data-mid="${m.match_id}">
          <div class="m-teams">
            <span class="m-team ${m.winner === ta ? "winner" : ""}">${ta}</span>
            <span class="m-score">${scoreStr}</span>
            <span class="m-team ${m.winner === tb ? "winner" : ""}">${tb}</span>
          </div>
          ${wStr ? '<div class="m-winner-label">' + wStr + "</div>" : ""}
          ${probStr ? '<div class="m-prob">' + ta + " win " + probStr + "</div>" : ""}
        </div>`;
      slot.querySelector(".match-card").onclick = () => openMatchModal(m.match_id);
      col.appendChild(slot);
    });
    grid.appendChild(col);
  });

  setTimeout(drawBracketConnectors, 50);
}

// ── Match Insight Modal ──
async function openMatchModal(mid) {
  const fb = appState.fullBracket;
  let match = null;
  for (const [, ms] of Object.entries(fb.rounds)) {
    const found = ms.find(m => m.match_id === mid);
    if (found) { match = found; break; }
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
  if (!s || !s.standings) return;
  const letters = Object.keys(s.standings).sort();

  tab.innerHTML = `
    <div class="standings-grid" id="standingsGrid">
      ${letters.map(letter => {
        const rows = s.standings[letter];
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
    <div class="bubble-section" id="bubbleSection"></div>
  `;

  const tp = s.third_place;
  if (tp && tp.length >= 9) {
    let html = '<div class="g-title">Third-Place Bubble</div><table class="bubble-table"><tr><th>#</th><th>Group</th><th>Team</th><th>Pts</th><th>GD</th><th>GS</th></tr>';
    tp.forEach((r, i) => {
      const cls = i < 8 ? "advancing" : i === 8 ? "cutoff-line" : "eliminated";
      const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
      html += '<tr class="' + cls + '"><td class="num">' + (i + 1) + '</td><td>' + r.group + '</td><td>' + r.team + '</td><td class="num">' + r.pts + '</td><td class="num">' + gd + '</td><td class="num">' + r.gs + '</td></tr>';
    });
    html += "</table>";
    if (tp[7] && tp[8]) {
      const m = tp[7], n = tp[8];
      const margin = m.pts !== n.pts ? (m.pts - n.pts) + " pts" : (m.gd !== n.gd ? "GD " + (m.gd - n.gd) : "GS " + (m.gs - n.gs));
      html += '<div style="font-size:10px;color:#F6DBC088;margin-top:4px">>> 8th advances, 9th out. Cutoff margin = ' + margin + ".</div>";
    }
    document.getElementById("bubbleSection").innerHTML = html;
  }
}

// ── Terminal ──
function buildWCTable(teams, cols) {
  const show = cols || ["champion", "final", "sf", "qf"];
  const labels = { champion: "Champion", final: "Final", sf: "SF", qf: "QF" };
  let h = '<tr><th>#</th><th>Team</th><th>ELO</th>';
  show.forEach(c => h += "<th>" + (labels[c] || c) + "</th>");
  h += "<th></th></tr>";
  let html = "<table>" + h;
  teams.forEach((t, i) => {
    const pct = t[show[0]] || 0;
    const barW = Math.max(2, pct * 2);
    html += '<tr><td class="num">' + (i + 1) + "</td><td>" + t.name + '</td><td class="num">' + t.elo + "</td>";
    show.forEach(c => html += '<td class="num">' + (t[c] || 0).toFixed(1) + "%</td>");
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
    termAdd('<span class="prompt">refresh</span>     - fetch latest matches from BSD API (if .env configured).');
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
  } else if (main === "refresh") {
    try {
      const resp = await (await fetch(API + "/refresh", { method: "POST" })).json();
      termAdd("");
      termAdd('<span class="highlight">== Refresh Result ==</span>');
      termAdd(JSON.stringify(resp, null, 2).replace(/\n/g, "<br>").replace(/  /g, "&nbsp;&nbsp;"));
      // Reload
      await loadAll();
      termAdd('<span class="ok">Data reloaded.</span>');
      termAdd("");
    } catch { termAdd("Failed to refresh.", "danger"); }
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
  } else {
    termAdd("command not found: " + trimmed, "danger");
    termAdd('Type <span class="prompt">help</span> for available commands.', "dim");
  }
  termShowPrompt();
}
