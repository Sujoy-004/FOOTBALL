// ═══ UCL 2025/26 Module ═══
import {
  destroyModalCharts, modalCharts, drawBracketConnectors,
  updateStatusBar, competitions, showSimPopup,
  buildTable, safeJson,
} from "./shared.js";

const API = "/ucl/api";
const appState = { data: null, standings: [], bracket: null, odds: [], signals: {}, matches: [] };

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

    const matches = [];
    const lmd = br.league_matchdays || {};
    Object.keys(lmd).sort().forEach(md => {
      (lmd[md] || []).forEach(m => matches.push({ ...m, matchday: md }));
    });
    if (br.bracket_rounds) {
      Object.entries(br.bracket_rounds).forEach(([rnd, ms]) => {
        ms.forEach(m => matches.push({ ...m, round: rnd }));
      });
    }
    appState.matches = matches;
  } catch (e) {
    console.error("loadAll API fetch failed:", e);
    const tab = document.getElementById("tab-overview");
    if (tab) tab.innerHTML = '<div class="stat-card" style="color:#ff6b6b">Failed to load UCL data: ' + e.message + '</div>';
    return;
  }

  renderOverview();
  renderStandings();
  renderBracket();
  renderOdds();
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
  renderOverview(); renderStandings(); renderBracket(); renderOdds(); updateStatus();
}

function updateStatus() {
  const d = appState.data;
  if (!d) return;
  const signals = appState.signals;
  const sigKeys = Object.keys(signals);
  const stale = d.refresh && d.refresh.stale;
  updateStatusBar(
    d.n_teams + " teams  |  " + (d.n_played || 0) + " matches played",
    stale ? '<span style="color:#e6a817">\u26A0 STALE \u2014 live refresh failed; showing snapshot data</span>' : ""
  );
}

window.__resetResults = async function () {
  try {
    const resp = await safeJson(API + "/reset", { method: "POST" });
    if (resp.status === "error") { console.error("Reset error:", resp.error); return; }
    await reloadData();
    renderOverview(); renderStandings(); renderBracket(); renderOdds();
  } catch (e) { console.error("Reset failed:", e); }
};

// ── Overview ─────────────────────────────────────────────────────────

async function renderOverview() {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const d = appState.data;
  if (!d) { tab.innerHTML = '<div class="dim">Loading\u2026</div>'; return; }

  const standings = appState.standings || [];
  const signals = appState.signals || {};
  const sigKeys = Object.keys(signals);
  const odds = appState.odds || [];

  // Stat cards
  let html = '<div class="stats-row">';
  html += '<div class="stat-card"><div class="val">' + (d.n_teams || 0) + '</div><div class="lbl">Teams</div></div>';
  html += '<div class="stat-card"><div class="val">' + (d.n_played || 0) + '</div><div class="lbl">Matches Played</div></div>';
  html += '<div class="stat-card"><div class="val">' + sigKeys.length + ' / ' + sigOrder.length + '</div><div class="lbl">Signals Active</div></div>';
  if (d.snapshot_date) html += '<div class="stat-card"><div class="val" style="font-size:.8em">' + d.snapshot_date + '</div><div class="lbl">Season</div></div>';
  html += '</div>';

  // Top teams preview (top 8 by position)
  if (standings.length >= 8) {
    html += '<div class="chart-section"><div class="title">Top Teams \u2014 League Phase</div>';
    html += '<table class="eval-table"><tr><th>#</th><th>Team</th><th>Pts</th><th>GD</th><th>Form</th></tr>';
    standings.slice(0, 8).forEach(function(r, i) {
      const gd = r.gd > 0 ? "+" + r.gd : String(r.gd);
      const zoneCls = i < 8 ? 'zone-top8' : '';
      html += '<tr><td class="num">' + (i + 1) + '</td><td>' + r.team + '</td>'
        + '<td class="num">' + (r.pts !== undefined ? r.pts : '-') + '</td>'
        + '<td class="num">' + gd + '</td>'
        + '<td' + (i < 2 ? ' style="color:#16A085"' : '') + '>' + (i < 8 ? '\u25B2 TOP 8' : '') + '</td></tr>';
    });
    html += '</table></div>';
  }

  // Signal availability
  if (sigKeys.length > 0) {
    html += '<div class="chart-section"><div class="title">Signal Availability</div>';
    html += '<table class="eval-table"><tr><th>Signal</th><th>Status</th></tr>';
    sigOrder.forEach(function(sk) {
      const s = signals[sk];
      const available = s !== undefined;
      html += '<tr><td>' + (sigLabels[sk] || sk) + '</td><td>'
        + '<span class="' + (available ? 'dot-green' : 'dot-red') + '">\u25CF</span> '
        + (available ? 'Available' : 'Unavailable') + '</td></tr>';
    });
    html += '</table></div>';
  }

  // Odds preview
  if (odds.length >= 5) {
    html += '<div class="chart-section"><div class="title">Championship Odds (Top 5)</div>';
    html += '<table class="eval-table"><tr><th>#</th><th>Team</th><th>Champion %</th><th></th></tr>';
    odds.slice(0, 5).forEach(function(o, i) {
      const pct = ((o.champion_prob || 0) * 100).toFixed(1);
      html += '<tr><td class="num">' + (i + 1) + '</td><td>' + o.team + '</td>'
        + '<td class="num">' + pct + '%</td>'
        + '<td><div class="bar-wrap"><div class="bar" style="width:' + Math.max(2, (o.champion_prob || 0) * 200) + '%"></div></div></td></tr>';
    });
    html += '</table></div>';
  }

  tab.innerHTML = html;
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
    html += '<div class="chart-section"><div class="title">\u26BD League Phase \u2014 Matchday Explorer</div><div class="md-accordion">';
    const firstMid = lmdKeys[0];
    lmdKeys.forEach(function(md, mdi) {
      const ms = lmd[md] || [];
      const isFirst = mdi === 0;
      mdHtml = '<div class="md-card"><div class="md-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">';
      mdHtml += '<span class="md-label">' + md.replace(/^MD/, "Matchday ") + '</span>';
      mdHtml += '<span class="md-count">' + ms.length + " matches</span>";
      mdHtml += '<span class="md-arrow">' + (isFirst ? "\u25BC" : "\u25B6") + "</span></div>";
      mdHtml += '<div class="md-body' + (isFirst ? " open" : "") + '">';
      ms.forEach(function(m) {
        const hs = m.home_score !== undefined && m.home_score !== null ? m.home_score : "-";
        const as_ = m.away_score !== undefined && m.away_score !== null ? m.away_score : "-";
        const played = hs !== "-" && as_ !== "-";
        const statusDot = played
          ? '<span class="dot-green">\u25CF</span>'
          : '<span class="dot-orange">\u25CF</span>';
        const scoreStr = played ? hs + " - " + as_ : "vs";
        mdHtml += '<div class="md-row match-clickable"'
          + ' data-match-id="' + m.match_id + '"'
          + ' data-team-a="' + m.team_a + '"'
          + ' data-team-b="' + m.team_b + '"'
          + ' onclick="openMatchModalFromEl(this)"'
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

  // ── Section 2: Knockout Playoffs (if data exists) ──
  if (playoff.length) {
    html += '<div class="chart-section"><div class="title">\u26BE Knockout Playoffs</div><div class="playoff-grid">';
    playoff.forEach(function(t) {
      const aggStr = t.aggregate_a + "-" + t.aggregate_b;
      let detail = aggStr + " agg";
      if (t.et_played) detail += " (ET)";
      if (t.penalties_played) detail += " (pens)";
      html += '<div class="playoff-card match-clickable" data-match-id="' + (t.match_id || "") + '"'
        + ' data-team-a="' + (t.team_a || "") + '" data-team-b="' + (t.team_b || "") + '"'
        + ' onclick="openMatchModalFromEl(this)"'
        + ' style="cursor:pointer">'
        + '<div class="p-title">Tie ' + t.tie_num + '</div>'
        + '<div class="p-teams"><span class="p-team">' + (t.team_a || "?") + '</span><span class="p-score">' + aggStr + '</span><span class="p-team">' + (t.team_b || "?") + '</span></div>'
        + '<div class="p-detail">' + detail + "</div></div>";
    });
    html += "</div></div>";
  } else {
    html += '<div class="chart-section"><div class="title">\u26BE Knockout Playoffs</div>';
    html += '<div class="dim" style="padding:8px;color:#15565B;font-size:11px">Playoff results not yet available in snapshot data.</div></div>';
  }

  // ── Section 3: Knockout Rounds (R16 → QF → SF → Final) ──
  const roundMeta = [
    { key: "R16", label: "Round of 16" },
    { key: "QF", label: "Quarter-Finals" },
    { key: "SF", label: "Semi-Finals" },
    { key: "FINAL", label: "Final" },
  ];

  let koSection = '<div class="chart-section"><div class="title">\uD83C\uDFC6 Knockout Stage</div>';
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
        + ' data-team-a="' + ta + '" data-team-b="' + tb + '"'
        + ' onclick="openMatchModalFromEl(this)">'
        + '<div class="ko-round-tag">' + rm.label + '</div>'
        + '<div class="ko-teams"><span>' + ta + '</span><span class="ko-vs">vs</span><span>' + tb + '</span></div>'
        + '<div class="ko-score">' + agg + '</div>'
        + (winner ? '<div class="ko-winner">\u2713 ' + winner + '</div>' : '')
        + '</div>';
    });
    koSection += '</div>';
  });

  if (!anyKoData) {
    koSection += '<div class="dim" style="padding:8px;font-size:11px">Knockout stage has not started yet. Results will appear here once the playoff round begins.</div>';
  }
  koSection += '</div>';
  html += koSection;

  tab.innerHTML = html;
}

// ── Odds ─────────────────────────────────────────────────────────────

function renderOdds() {
  const tab = document.getElementById("tab-odds");
  if (!tab) return;
  const odds = appState.odds;
  if (!odds || !odds.length) {
    tab.innerHTML = '<div style="color:#15565B;font-size:12px">No odds data.</div>';
    return;
  }
  tab.innerHTML = '<div class="odds-wrap"><table class="odds-table">'
    + '<tr><th>#</th><th>Team</th><th>Champion</th><th>Final</th><th>SF</th><th>QF</th><th>Top 8</th></tr>'
    + odds.map(function(t, i) {
      return '<tr><td class="num">' + (i + 1) + '</td><td>' + t.team + '</td>'
        + ['champion', 'final', 'sf', 'qf', 'top_8'].map(function(k) {
          const v = t[k + '_prob'];
          return '<td class="num">' + (v != null ? (v * 100).toFixed(1) + '%' : '-')
            + '<span class="odds-bar-wrap"><span class="odds-bar" style="width:' + Math.max(2, (v || 0) * 200) + '%"></span></span></td>';
        }).join("") + '</tr>';
    }).join("") + '</table></div>';
}

// ── Signals ──────────────────────────────────────────────────────────

function renderSignals() {
  const meta = compute_signals_meta();
  const signals = meta.signals || [];
  let html = "";
  signals.forEach(function(s) {
    html += '<div class="signal-row"><span>' + s.name + '</span>'
      + '<span class="' + (s.available ? 'dot-green' : 'dot-red') + '">\u25CF</span>'
      + '<span class="dim">' + (s.last_updated || 'never') + '</span></div>';
  });
}

function openMatchModalFromEl(el) {
  const mid = el.getAttribute('data-match-id');
  if (!mid) return;
  openMatchModal({ match_id: mid, team_a: el.getAttribute('data-team-a') || '', team_b: el.getAttribute('data-team-b') || '' });
}

function getScoreStr(m) {
  if (m.score) return m.score.home + '-' + m.score.away;
  if (m.result && m.result.score_a !== undefined) return m.result.score_a + '-' + m.result.score_b;
  if (m.home_score !== undefined) return m.home_score + '-' + m.away_score;
  return 'No result';
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
  var bp = insight.blended_prob || 0.5;
  var outcome = insight.outcome_distribution || {};
  var ft = insight.form_trends || {};

  left.innerHTML =
    '<div class="sec-title">Blended Prediction</div>' +
    '<div class="stat-card" style="margin:4px 0"><div class="val">' +
    Math.round(bp * 100) + '%</div><div class="lbl">' + ta + ' win</div></div>' +
    '<div class="sec-title">Form Trend</div><div class="form-charts">' +
    [ta, tb].map(function(team) {
      return '<div class="form-chart-box"><div class="fc-label">' + team +
        '</div><canvas id="fc-' + team.replace(/\s/g, "") + '"></canvas></div>';
    }).join("") +
    '</div><div class="sec-title">Signal Comparison</div>' +
    '<div class="chart-box"><canvas id="sigChart"></canvas></div>' +
    '<div class="sec-title">Outcome Distribution</div><div class="outcome-charts">' +
    '<div class="outcome-chart-box"><canvas id="outcomeChart"></canvas></div></div>';

  var sigHtml = '<div class="sec-title">Signal Breakdown</div>';
  sigHtml += '<table class="insight-table"><tr><th>Signal</th><th>Prob</th><th>Weight</th></tr>';
  var hasSignals = false;
  sigKeys.forEach(function(sk) {
    var sd = sigs[sk];
    if (!sd) return;
    hasSignals = true;
    sigHtml += '<tr><td>' + (sd.label || sk) + '</td><td class="num">' +
      Math.round((sd.probability || 0.5) * 100) + '%</td><td class="num">' +
      ((sd.weight || 0) * 100).toFixed(1) + '%</td></tr>';
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
    '<button onclick="window.__sendUclWhatIf(\'' + mid.replace(/'/g, "\\'") + '\',\'' + ta.replace(/'/g, "\\'") + '\',\'' + tb.replace(/'/g, "\\'") + '\')">&#9654;</button></div>' +
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
      return Math.round((sigs[sk].probability || 0.5) * 100);
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

  var ocCanvas = document.getElementById("outcomeChart");
  if (ocCanvas && typeof Chart !== "undefined" && outcome.a_win !== undefined) {
    modalCharts.outcome = new Chart(ocCanvas.getContext("2d"), {
      type: "doughnut",
      data: { labels: [ta + " win", "Draw", tb + " win"],
        datasets: [{ data: [outcome.a_win || 0.33, outcome.draw || 0.33, outcome.b_win || 0.33],
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
