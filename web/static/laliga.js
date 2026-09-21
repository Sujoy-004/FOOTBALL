// ═══ LaLiga EA Sports Module ═══
// League-only predictive console: Overview (acquisition + signals),
// Standings (20-team table), Fixtures (matchday accordion + match
// intelligence), Simulation (seeded Monte Carlo + what-if counterfactual).
// Mirrors the shared shell conventions used by wc.js/ucl.js.
import {
  destroyModalCharts, updateStatusBar,
  showSimPopup, buildTable, safeJson, renderAcquisitionPanel,
  openIntelModal, renderLoading, currentCompetition,
  configureCompetitionRefresh,
} from "./shared.js";

const API = "/laliga/api";
const DI = "laliga";
const appState = {
  data: null, standings: [], fixtures: [], odds: [], signals: {},
  sim: null, simMeta: null, validation: null,
  refresh: null, mode: "results", phase: {}, season: "",
  n_teams: 0, n_played: 0, n_unplayed: 0,
};
let simCompareTeams = [];

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
  configureCompetitionRefresh(DI, { reload: refreshLive });
  loadAll({ label: "Loading LaLiga…" });
}

let _transitionGen = 0;

function _isActive() {
  return !!(currentCompetition && currentCompetition.apiPrefix === API);
}

function _stale(gen) {
  return gen !== _transitionGen || !_isActive();
}

function _showTransitionLoading(label) {
  ["tab-overview", "tab-standings", "tab-fixtures", "tab-simulation",
   "tab-validation"].forEach(function(id) {
    const el = document.getElementById(id);
    if (el && typeof renderLoading === "function") renderLoading(el, label);
  });
}

function _surfaceTransitionError(e, o) {
  const tab = document.getElementById("tab-overview");
  if (!tab) return;
  const what = (o && o.season) ? ("Could not switch to " + o.season)
    : "Could not refresh LaLiga data";
  const notice = document.createElement("div");
  notice.style.cssText = "background:#ff6b6b22;color:#ff8a8a;padding:12px;margin:8px;"
    + "border:1px solid #ff6b6b55;border-radius:6px;font-family:var(--font-mono,monospace)";
  notice.textContent = what + ": " + (e && e.message ? e.message : String(e));
  tab.prepend(notice);
}

async function loadAll(o) {
  const gen = ++_transitionGen;
  _showTransitionLoading((o && o.label) || "Loading…");
  try {
    const [data, fixtures, sim, val] = await Promise.all([
      safeJson(API + "/data"),
      safeJson(API + "/fixtures"),
      safeJson(API + "/simulation"),
      safeJson(API + "/validation"),
    ]);
    if (_stale(gen)) return;
    appState.data = data;
    appState.standings = data.standings || [];
    appState.mode = data.mode || "results";
    appState.phase = data.phase || {};
    appState.season = data.season || "";
    appState.n_teams = data.n_teams || 0;
    appState.n_played = data.n_played || 0;
    appState.n_unplayed = data.n_unplayed != null ? data.n_unplayed : 0;
    appState.refresh = data.refresh || {};
    appState.fixtures = fixtures.matchdays || [];
    applySimulation(sim);
    appState.validation = val && val.validation ? val.validation : null;
    render();
  } catch (e) {
    if (_stale(gen)) return;
    render();
    _surfaceTransitionError(e, o || {});
  }
  if (gen === _transitionGen) refreshValidate();
}

// ── Simulation state ──
function applySimulation(sim) {
  if (!sim) return;
  appState.sim = sim;
  appState.simMeta = sim.simulation_meta || null;
}

function _simPct(v) {
  return typeof v === "number" ? (v * 100).toFixed(1) + "%" : "—";
}

function _simComparisonRows() {
  const sim = appState.sim || {};
  const odds = (sim.odds || []).slice();
  const rows = odds.map(function(o) {
    const pct = o.avg_position;
    const bot = (typeof o.bottom_prob === "number") ? o.bottom_prob * 100 : null;
    const mid = (typeof o.mid_table_prob === "number") ? o.mid_table_prob * 100 : null;
    const t6 = (typeof o.top_6_prob === "number") ? o.top_6_prob * 100 : null;
    const champ = (typeof o.champion_prob === "number") ? o.champion_prob * 100 : null;
    rowRef(o, champ, t6, mid, bot, pct);
    return o;
  });
  rows.forEach(function(o) {
    o._champ = o._champ;
  });
  return rows;
  function rowRef(o, champ, t6, mid, bot, pct) {
    o._champ = champ;
    o._t6 = t6;
    o._mid = mid;
    o._bot = bot;
    o._avgPos = pct;
  }
}

async function refreshValidate() {
  try {
    const v = await safeJson(API + "/validation");
    if (!_stale(_transitionGen)) {
      appState.validation = v && v.validation ? v.validation : null;
      const el = document.getElementById("tab-validation");
      if (el) {
        const html = _evalBlock();
        if (html) el.innerHTML = html;
      }
    }
  } catch { /* validation is best-effort */ }
}

// ── Render ──
function render() {
  const tabs = ["tab-overview", "tab-standings", "tab-fixtures", "tab-simulation", "tab-validation"];
  tabs.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (id === "tab-overview") el.innerHTML = _overviewHtml() || "";
    else if (id === "tab-standings") el.innerHTML = _standingsHtml();
    else if (id === "tab-fixtures") { el.innerHTML = _fixturesHtml(); bindMatchClicks(el); }
    else if (id === "tab-simulation") el.innerHTML = _simulationHtml();
    else if (id === "tab-validation") el.innerHTML = _evalBlock() || "";
  });
  updateStatusBar(
    _esc(appState.season || "") + " &middot; " + appState.n_played + "/"
      + (appState.n_played + appState.n_unplayed) + " played &middot; "
      + _esc(sigInfo()),
    (_staleProvenanceChip())
  );
}

function _staleProvenanceChip() {
  const r = appState.refresh || {};
  if (r.skipped_reason) return "offline snapshot";
  if (r.deferred) return "data provider deferred";
  if (r.error) return "refresh failed";
  if (r.provider) return "live: " + (r.provider || "");
  return "";
}

function sigInfo() {
  const s = appState.signals || {};
  const keys = Object.keys(s);
  if (!keys.length) return appState.mode === "results" ? "results mode" : "simulation mode";
  return "mode: " + (appState.mode || "?");
}

// ── Overview ──
function _overviewHtml() {
  const d = appState.data || {};
  const phase = appState.phase || {};
  const prog = phase.progress || {};
  const reports = appState.refresh || {};

  const acquisition = {
    competition: "LaLiga EA Sports " + (appState.season || ""),
    source: reports.skipped_reason ? "snapshot (offline)" : (reports.error ? "stale/error" : (reports.provider || "shipped data")),
    mode: reports.skipped_reason ? "snapshot" : "live",
    stale: !!(reports.error && !reports.skipped_reason),
    error: reports.error && !reports.skipped_reason ? reports.error : null,
    notice: reports.deferred ? "Provider has no published data yet — deferred." : null,
    updatedAt: reports.last_refresh || "",
    stages: [
      { key: "fixtures", label: "Schedule (38 matchdays)", state: "ok", count: (prog.n_total != null ? prog.n_total : "--") },
      { key: "results", label: "Played results", state: "ok", count: prog.n_played != null ? prog.n_played : "--" },
      { key: "quality", label: "Prediction signals", state: Object.keys(appState.signals).length ? "ok" : "pending", count: Object.keys(appState.signals).length ? Object.keys(appState.signals).length : 0 },
    ],
  };
  let html = '<div class="chart-section"><div class="title">Acquisition &amp; Status</div>';
  html += '<div id="acqHost"></div></div>';
  html += '<div class="section-title">' + _esc("Season Phase") + "</div>";
  html += '<div class="phase-card"><div><span class="lbl">Season</span><span class="val">' + _esc(appState.season || "—") + "</span></div>";
  html += '<div><span class="lbl">Matchday</span><span class="val">' + (prog.current_matchday || 0) + " / " + (prog.n_matchdays || 38) + "</span></div>";
  html += '<div><span class="lbl">Played</span><span class="val">' + (prog.n_played || 0) + "</span></div>";
  html += '<div><span class="lbl">Remaining</span><span class="val">' + (prog.n_unplayed || 0) + "</span></div>";
  html += '<div><span class="lbl">Mode</span><span class="val">' + _esc(appState.mode || "—") + "</span></div></div>";

  html += '<div class="chart-section"><div class="title">Signal Evaluation (vs played results)</div><div class="ol-signal-list">';
  if (!Object.keys(appState.signals).length) {
    html += '<div class="m-sub">No signal evaluation yet.</div>';
  } else {
    sigOrder.forEach(function(name) {
      const s = appState.signals[name];
      if (!s) return;
      const acc = typeof s.accuracy === "number" ? (s.accuracy * 100).toFixed(0) + "%" : "—";
      const brier = typeof s.brier === "number" ? s.brier.toFixed(3) : "—";
      const avail = s.available != null ? s.available : "—";
      html += '<div class="md-row" style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid rgba(21,61,76,.12)">'
        + '<span class="md-team">' + _esc(sigLabels[name] || name) + "</span>"
        + '<span class="md-score">acc ' + acc + " &middot; brier " + brier
        + " &middot; avail " + avail + "</span></div>";
    });
  }
  html += "</div></div>";
  html += '<div class="chart-section"><div class="title">Top of the Table</div>'
    + buildTable((appState.standings || []).slice(0, 5).map(t => ({ name: t.team, prized: t.points / 100 })), ["prized"], { prized: "Pts/100" })
    + "</div>";
  return html;
}

// ── Standings ──
function _zoneOf(pos) {
  if (pos <= 1) return "Champions";
  if (pos <= 4) return "Champions League";
  if (pos <= 5) return "Europa League";
  if (pos <= 6) return "Conference League";
  if (pos <= 17) return "";
  return "Relegation";
}

function _standingsHtml() {
  const rows = appState.standings || [];
  if (!rows.length) return '<div class="m-sub">No standings yet.</div>';
  let html = '<div class="chart-section"><div class="title">LaLiga Table — ' + _esc(appState.season || "") + "</div>";
  html += '<table class="league-table"><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Zone</th></tr></thead><tbody>';
  rows.forEach(function(t) {
    const zone = _zoneOf(t.position);
    const gd = t.goal_diff >= 0 ? "+" + t.goal_diff : String(t.goal_diff);
    html += '<tr' + (zone === "Relegation" ? ' class="zone-relegation"' : "")
      + '><td class="num">' + t.position + "</td><td>" + _esc(t.team) + "</td>"
      + '<td class="num">' + t.played + "</td><td class=\"num\">" + t.wins + "</td>"
      + '<td class="num">' + t.draws + "</td><td class=\"num\">" + t.losses + "</td>"
      + '<td class="num">' + t.goals_for + "</td><td class=\"num\">" + t.goals_against + "</td>"
      + '<td class="num">' + gd + "</td><td class=\"num\"><strong>" + t.points + "</strong></td>"
      + '<td class="num">' + (zone ? '<span class="zone-badge">' + _esc(zone) + "</span>" : "") + "</td></tr>";
  });
  html += "</tbody></table></div>";
  return html;
}

// ── Fixtures (matchday accordion) ──
function _fixturesHtml() {
  const matchdays = appState.fixtures || [];
  if (!matchdays.length) return '<div class="m-sub">No fixtures yet.</div>';
  let html = '<div class="chart-section"><div class="title">Match Schedule</div><div class="md-accordion">';
  matchdays.forEach(function(mdRow, i) {
    const md = mdRow.matchday;
    const ms = mdRow.matches || [];
    const open = i === 0;
    html += '<div class="md-card"><div class="md-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">';
    html += '<span class="md-label">Matchday ' + md + "</span>";
    html += '<span class="md-count">' + ms.length + " matches</span>";
    html += '<span class="md-arrow">' + (open ? "-" : "+") + "</span></div>";
    html += '<div class="md-body' + (open ? " open" : "") + '">';
    ms.forEach(function(m) {
      const played = !!(m.home_score != null && m.away_score != null);
      const dot = played ? '<span class="dot-green">\u25CF</span>' : '<span class="dot-orange">\u25CF</span>';
      const scoreStr = played ? m.home_score + " – " + m.away_score : "vs";
      html += '<div class="md-row match-clickable"'
        + ' data-match-id="' + _esc(m.match_id) + '"'
        + ' style="cursor:pointer;transition:background .15s;display:flex;justify-content:space-between;align-items:center;padding:5px 8px;border-bottom:1px solid rgba(21,61,76,.15)"'
        + '><span class="md-team" style="flex:1;text-align:right">' + _esc(m.team_a) + "</span>"
        + '<span class="md-score" style="margin:0 12px;font-weight:bold;min-width:46px;text-align:center">' + scoreStr + "</span>"
        + '<span class="md-team" style="flex:1">' + _esc(m.team_b) + "</span>"
        + '<span style="font-size:10px;margin-left:8px">' + dot + "</span></div>";
    });
    html += "</div></div>";
  });
  html += "</div></div>";
  return html;
}

// ── Match intelligence modal ──
function openMatchModalFromEl(el) {
  const mid = el.dataset.matchId;
  if (!mid) return;
  openMatchModal(mid);
}

async function openMatchModal(mid) {
  let ins = null;
  try {
    ins = await safeJson(API + "/match/insight?match_id=" + encodeURIComponent(mid));
  } catch (e) { ins = { error: "fetch failed: " + e.message }; }
  if (_stale(_transitionGen)) return;
  if (!ins || ins.error) {
    openIntelModal({ titleHtml: "Match Intelligence", sub: String((ins && ins.error) || "error"),
      bodyHtml: "<p class=\"m-sub\">Could not load match insight.</p>" });
    return;
  }
  const teams = ins.teams || {};
  const ta = teams.a || "";
  const tb = teams.b || "";
  const played = ins.played === true;
  const score = ins.score;
  const scoreLine = (played && score)
    ? score.home + " – " + score.away : "vs";
  const provChip = '<span class="prov-chip">' + _esc(String(ins.provenance || "official")) + "</span>";
  const titleHtml = _esc(ta) + " <span class=\"vs-sep\">v</span> " + _esc(tb)
    + ' <span class="m-score-big">' + scoreLine + "</span>";
  const sub = "Round: " + _esc(String(ins.round || "Regular Season")) + " &middot; "
    + (played ? "Played" : "Scheduled") + " &middot; " + provChip;

  let body = "";
  if (typeof ins.blended_prob === "number" && ins.blended_prob >= 0) {
    body += '<div class="chart-section"><div class="title">Prediction</div>'
      + '<div class="pred-grid"><div class="pred-cell"><span class="lbl">Blend HOME</span>'
      + '<span class="val">' + _simPct(ins.blended_prob) + "</span></div>"
      + '<div class="pred-cell"><span class="lbl">Elo HOME</span>'
      + '<span class="val">' + _simPct(ins.elo_prob) + "</span></div></div></div>";
  }
  const sigs = ins.signals || {};
  const sigKeys = Object.keys(sigs);
  if (sigKeys.length) {
    body += '<div class="chart-section"><div class="title">Signal Breakdown</div><table class="eval-table">'
      + "<thead><tr><th>Signal</th><th>Home</th><th>Weight</th></tr></thead><tbody>";
    sigOrder.forEach(function(name) {
      const sd = sigs[name];
      if (!sd) return;
      body += "<tr><td>" + _esc(sd.label || name) + "</td>"
        + '<td class="num">' + _simPct(sd.probability) + "</td>"
        + '<td class="num">' + _simPct(sd.weight) + "</td></tr>";
    });
    body += "</tbody></table></div>";
  }
  const h2h = ins.head_to_head || {};
  if (h2h.total) {
    body += '<div class="chart-section"><div class="title">Head to Head</div>'
      + "<p>" + _esc(ta) + " " + (h2h.a_wins || 0) + " – " + (h2h.draws || 0) + " – "
      + (h2h.b_wins || 0) + " " + _esc(tb) + " (" + h2h.total + " meetings)</p></div>";
  }
  const ft = ins.form_trends || {};
  const formTeam = [ta, tb].filter(function(t) { return ft[t]; });
  if (formTeam.length) {
    body += '<div class="chart-section"><div class="title">Recent Form</div>';
    formTeam.forEach(function(t) {
      const streak = (ft[t] || []).map(function(r) { return r.result; }).join("");
      const n = (ft[t] || []).length;
      body += "<p>" + _esc(t) + ": <span class=\"form-line\">" + _esc(streak || "—") + "</span> (last " + n + ")</p>";
    });
    body += "</div>";
  }
  if (ins.insight) {
    body += '<div class="chart-section"><div class="title">Insight</div>'
      + "<p class=\"insight-text\">" + _esc(ins.insight) + "</p></div>";
  }
  // What-if quick link
  body += '<div class="chart-section"><div class="title">What-If</div>'
    + '<button class="status-btn" id="whatifOpenBtn">Adjust Elo &amp; re-run simulation</button></div>';

  openIntelModal({ titleHtml: titleHtml, sub: sub, bodyHtml: body });
  const wb = document.getElementById("whatifOpenBtn");
  if (wb) wb.onclick = function() { openWhatIf(mid, ta, tb); };
}

// ── What-If (match Elo counterfactual) ──
function openWhatIf(mid, ta, tb) {
  const iters = 10000;
  const body = '<div class="chart-section"><div class="title">What-If &mdash; ' + _esc(ta) + " v " + _esc(tb) + "</div>"
    + '<div class="form-grid">'
    + '<label class="form-field"><span class="lbl">' + _esc(ta) + ' Elo delta</span>'
    + '<input type="number" id="wiDelta" value="50" min="-200" max="200"></label>'
    + "</div>"
    + '<div class="sim-actions"><button class="status-btn" id="wiRunBtn">Run ' + iters.toLocaleString() + " simulations</button></div>"
    + '<div id="wiResult" style="margin-top:12px"></div></div>';
  openIntelModal({ titleHtml: "What-If Analysis", sub: "Apply an Elo shift to one fixture and re-run the seeded Monte Carlo.", bodyHtml: body });
  document.getElementById("wiRunBtn").onclick = async function() {
    const delta = parseInt(document.getElementById("wiDelta").value) || 50;
    const resEl = document.getElementById("wiResult");
    resEl.innerHTML = '<span class="m-sub">Running ' + iters.toLocaleString() + " simulations&hellip;</span>";
    try {
      const r = await safeJson(API + "/what-if", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: mid, elo_delta: delta, iterations: iters }),
      });
      if (r.error) throw new Error(r.error);
      let html = '<table class="eval-table"><thead><tr><th>Team</th><th>Baseline</th><th>Adjusted</th><th>Delta</th></tr></thead><tbody>';
      (Object.keys(r.teams || {})).forEach(function(t) {
        const e = r.teams[t];
        html += "<tr><td>" + _esc(t) + "</td>"
          + '<td class="num">' + _simPct(e.baseline) + "</td>"
          + '<td class="num">' + _simPct(e.adjusted) + "</td>"
          + '<td class="num">' + (e.delta >= 0 ? "+" : "") + (e.delta * 100).toFixed(1) + "%</td></tr>";
      });
      html += "</tbody></table>";
      html += '<div style="margin-top:10px" class="m-sub">Iterations: ' + r.iterations + "</div>";
      resEl.innerHTML = html;
    } catch (e) {
      resEl.innerHTML = '<span class="m-sub" style="color:#ff8a8a">Failed: ' + _esc(e.message) + "</span>";
    }
  };
}

function bindMatchClicks(scope) {
  const rows = scope.querySelectorAll(".match-clickable");
  rows.forEach(function(row) {
    row.onclick = function() { openMatchModalFromEl(row); };
  });
}

// ── Simulation ──
function _simulationHtml() {
  const sim = appState.sim || {};
  const meta = appState.simMeta || {};
  const odds = sim.odds || [];
  const requested = meta.requested_count || 0;
  const actual = sim.n_iterations || 0;
  let html = '<div class="chart-section"><div class="title">Monte Carlo Projection' + (requested ? " — " + requested.toLocaleString() + " iterations" : "") + "</div>";

  if (!odds.length) {
    html += '<p class="m-sub">No simulation requested yet. The deterministic table reflects played matches; simulate to project the finished season.</p>';
  } else {
    html += buildTable(odds.slice(0, 10).map(function(o) {
      return { name: o.team, champ: o.champion_prob };
    }), ["champ"], { champ: "Champion" });
    html += '<div class="chart-section"><div class="title">Champion Probability</div>';
    odds.forEach(function(o) {
      const p = o.champion_prob || 0;
      html += '<div class="champ-bar-row"><span class="cpct">' + (p * 100).toFixed(1) + "%</span>"
        + '<span class="cteam">' + _esc(o.team) + "</span>"
        + '<div class="cbar-wrap"><div class="cbar" style="width:' + (p * 100).toFixed(1) + '%"></div></div></div>';
    });
    html += "</div>";
  }

  html += '<div class="chart-section"><div class="title">Simulation Controls</div>'
    + '<div class="sim-actions">'
    + '<button class="status-btn" id="simRunBtn">Run Simulation</button> '
    + "<span class=\"m-sub\">" + (actual ? actual.toLocaleString() + " iterations completed" : "no simulation cached")
    + (sim.seed != null ? " &middot; seed " + sim.seed : "") + "</span>"
    + "</div></div>";

  html += '<div class="chart-section"><div class="title">Head-to-Head What-If</div>'
    + '<div class="form-grid">'
    + '<label class="form-field"><span class="lbl">Match (by ID or search below)</span>'
    + '<input type="text" id="wiMatchSearch" placeholder="Type team name…"></label>'
    + '<label class="form-field"><span class="lbl">Fixture</span><select id="wiMatchSelect"></select></label>'
    + "</div><div id=\"wiStandalone\"></div></div>";

  html += '<div class="chart-section"><div class="title">Live Refresh</div>'
    + '<button class="status-btn" id="rofRefreshBtn">Re-fetch live data</button></div>';
  return html;
}

function _populateWhatIfSelect() {
  const sel = document.getElementById("wiMatchSelect");
  if (!sel) return;
  const search = document.getElementById("wiMatchSearch");
  if (search) search.oninput = function() {
    const q = search.value.toLowerCase();
    const opts = sel.querySelectorAll("option");
    opts.forEach(function(o) {
      o.style.display = (!q || o.textContent.toLowerCase().indexOf(q) >= 0) ? "" : "none";
    });
  };
  const seen = {};
  (appState.fixtures || []).forEach(function(mdRow) {
    (mdRow.matches || []).forEach(function(m) {
      const label = m.team_a + " v " + m.team_b;
      if (seen[label]) return;
      seen[label] = 1;
      const opt = document.createElement("option");
      opt.value = m.match_id;
      opt.textContent = "MD" + mdRow.matchday + " " + label;
      sel.appendChild(opt);
    });
  });
  sel.onchange = function() {
    const mid = sel.value;
    const host = document.getElementById("wiStandalone");
    if (!mid) { host.innerHTML = ""; return; }
    let ta = "", tb = "";
    (appState.fixtures || []).forEach(function(mdRow) {
      (mdRow.matches || []).forEach(function(m) {
        if (m.match_id === mid) { ta = m.team_a; tb = m.team_b; }
      });
    });
    host.innerHTML = '<div class="chart-section"><div class="title">What-If &mdash; ' + _esc(ta) + " v " + _esc(tb) + "</div>"
      + '<label class="form-field"><span class="lbl">' + _esc(ta) + ' Elo delta</span>'
      + '<input type="number" id="wiDelta2" value="50" min="-200" max="200"></label>'
      + '<div class="sim-actions"><button class="status-btn" id="wiRun2">Run 10K simulations</button></div>'
      + '<div id="wiResult2" style="margin-top:12px"></div></div>';
    document.getElementById("wiRun2").onclick = async function() {
      const delta = parseInt(document.getElementById("wiDelta2").value) || 50;
      const resEl = document.getElementById("wiResult2");
      resEl.innerHTML = '<span class="m-sub">Running&hellip;</span>';
      try {
        const r = await safeJson(API + "/what-if", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ match_id: mid, elo_delta: delta, iterations: 10000 }),
        });
        if (r.error) throw new Error(r.error);
        let html = '<table class="eval-table"><thead><tr><th>Team</th><th>Baseline</th><th>Adjusted</th><th>Delta</th></tr></thead><tbody>';
        Object.keys(r.teams || {}).forEach(function(t) {
          const e = r.teams[t];
          html += "<tr><td>" + _esc(t) + "</td><td class=\"num\">" + _simPct(e.baseline) + "</td>"
            + '<td class="num">' + _simPct(e.adjusted) + "</td>"
            + '<td class="num">' + (e.delta >= 0 ? "+" : "") + (e.delta * 100).toFixed(1) + "%</td></tr>";
        });
        html += "</tbody></table>";
        (r.top5_baseline || []).forEach(function(o, i) {
          html += '<div class="champ-bar-row"><span class="cpct">' + (o.champion * 100).toFixed(1) + "%</span>"
            + '<span class="cteam">' + _esc(o.team) + " <span class=\"m-sub\">baseline</span></span></div>";
        });
        resEl.innerHTML = html;
      } catch (e) {
        resEl.innerHTML = '<span class="m-sub" style="color:#ff8a8a">Failed: ' + _esc(e.message) + "</span>";
      }
    };
  };
}

function bindSimulation() {
  const runBtn = document.getElementById("simRunBtn");
  if (runBtn) {
    runBtn.onclick = function() {
      showSimPopup(API, {
        onComplete: async function() {
          try {
            const sim = await safeJson(API + "/simulation");
            if (!_stale(_transitionGen)) applySimulation(sim);
            setUpRefreshBtn();
          } catch {
            try {
              const sim = await safeJson(API + "/simulation");
              if (!_stale(_transitionGen)) applySimulation(sim);
            } catch { /* ignore */ }
          }
          if (!_stale(_transitionGen)) {
            const el = document.getElementById("tab-simulation");
            if (el) { el.innerHTML = _simulationHtml(); bindSimulation(); }
          }
        },
        bodyBuilder: function(iters) { return { iterations: iters }; },
      });
    };
  }
  setUpRefreshBtn();
  _populateWhatIfSelect();
}

function setUpRefreshBtn() {
  const btn = document.getElementById("rofRefreshBtn");
  if (btn) {
    btn.onclick = async function() {
      btn.disabled = true;
      btn.textContent = "Refreshing…";
      try {
        const r = await safeJson(API + "/refresh", { method: "POST" });
        if (r && r.status) {
          btn.textContent = r.status === "ok" ? "Refreshed" : "Refresh skipped";
        }
        await loadAll({ label: "Reloading LaLiga…" });
      } catch (e) {
        btn.textContent = "Refresh failed";
      }
      setTimeout(function() { btn.disabled = false; }, 2000);
    };
  }
}

async function refreshLive() {
  try {
    const [data, sim] = await Promise.all([
      safeJson(API + "/data"),
      safeJson(API + "/simulation"),
    ]);
    if (_stale(_transitionGen)) return null;
    appState.data = data;
    appState.standings = data.standings || [];
    appState.mode = data.mode || appState.mode;
    appState.phase = data.phase || appState.phase;
    appState.season = data.season || appState.season;
    appState.n_teams = data.n_teams || appState.n_teams;
    appState.n_played = data.n_played || appState.n_played;
    appState.n_unplayed = data.n_unplayed != null ? data.n_unplayed : appState.n_unplayed;
    appState.refresh = data.refresh || appState.refresh;
    applySimulation(sim);
    render();
    return true;
  } catch (e) {
    return null;
  }
}

// ── Validation (pure-Elo) ──
function _evalBlock() {
  const v = appState.validation;
  if (!v || !v.prediction_metrics) return "";
  const pm = v.prediction_metrics;
  let html = '<div class="chart-section"><div class="title">Model Validation</div>'
    + '<p class="m-sub">Pure-Elo home-win prediction vs the played results ledger.</p>'
    + '<div class="phase-card">'
    + '<div><span class="lbl">Matches</span><span class="val">' + (v.n_matches_fetched || 0) + "</span></div>"
    + '<div><span class="lbl">Accuracy</span><span class="val">' + (pm.accuracy * 100).toFixed(1) + "%</span></div>"
    + '<div><span class="lbl">Brier</span><span class="val">' + pm.brier.toFixed(4) + "</span></div>"
    + '<div><span class="lbl">Log-loss</span><span class="val">' + pm.log_loss.toFixed(4) + "</span></div>"
    + "</div></div>";
  return html;
}