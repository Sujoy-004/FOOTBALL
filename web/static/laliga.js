// ═══ LaLiga EA Sports Module ═══
// League-only predictive console: Overview (acquisition + signals),
// Standings (20-team table), Fixtures (matchday accordion + match
// intelligence), Simulation (seeded Monte Carlo + what-if counterfactual).
// Mirrors the shared shell conventions used by wc.js/ucl.js.
import {
  destroyModalCharts, updateStatusBar,
  safeJson, renderAcquisitionPanel,
  openIntelModal, renderLoading, currentCompetition,
  configureCompetitionRefresh,
  renderSimulationShell, bindSimulationShell,
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
  ["tab-overview", "tab-standings", "tab-fixtures",
   "tab-simulation"].forEach(function(id) {
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
      const el = document.getElementById("validationSection");
      if (el) {
        const html = _evalBlock();
        if (html) el.innerHTML = html;
      }
    }
  } catch { /* validation is best-effort */ }
}

// ── Render ──
function render() {
  const tabs = ["tab-overview", "tab-standings", "tab-fixtures", "tab-simulation"];
  tabs.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (id === "tab-overview") el.innerHTML = _overviewHtml() || "";
    else if (id === "tab-standings") el.innerHTML = _standingsHtml();
    else if (id === "tab-fixtures") { el.innerHTML = _fixturesHtml(); bindMatchClicks(el); }
    else if (id === "tab-simulation") el.innerHTML = _simulationHtml();
  });
  // The pure-Elo validation card lives inside Overview; bind the simulation
  // controls on every render so the Simulation tab works on FIRST visit (the
  // onComplete callback below also re-binds after a completed run).
  const acqHost = document.getElementById("acqHost");
  if (acqHost) renderAcquisitionPanel(acqHost, _acquisition());
  bindSimulation();
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
function _acquisition() {
  const phase = appState.phase || {};
  const prog = phase.progress || {};
  const reports = appState.refresh || {};
  return {
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
}

function _overviewHtml() {
  const phase = appState.phase || {};
  const prog = phase.progress || {};

  let html = '<div class="stats-row">'
    + '<div class="stat-card"><div class="val">' + _esc(appState.season || "—") + '</div><div class="lbl">Season</div></div>'
    + '<div class="stat-card"><div class="val">' + (prog.current_matchday || 0) + " / " + (prog.n_matchdays || 38) + '</div><div class="lbl">Matchday</div></div>'
    + '<div class="stat-card"><div class="val">' + (prog.n_played || 0) + " / " + (prog.n_total != null ? prog.n_total : (prog.n_played || 0)) + '</div><div class="lbl">Played</div></div>'
    + '<div class="stat-card"><div class="val">' + (prog.n_unplayed || 0) + '</div><div class="lbl">Remaining</div></div>'
    + '<div class="stat-card"><div class="val">' + _esc(appState.mode || "—") + '</div><div class="lbl">Mode</div></div>'
    + "</div>";

  html += '<div class="chart-section"><div class="title">Top of the Table</div>';
  const standings = appState.standings || [];
  if (!standings.length) {
    html += '<p class="m-sub">No standings yet.</p>';
  } else {
    html += '<table class="eval-table"><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th class="num">Pts</th></tr></thead><tbody>';
    standings.slice(0, 8).forEach(function(t) {
      const gd = t.goal_diff >= 0 ? "+" + t.goal_diff : String(t.goal_diff);
      html += '<tr><td class="num">' + t.position + '</td><td>' + _esc(t.team) + '</td>'
        + '<td class="num">' + t.played + '</td><td class="num">' + t.wins + '</td>'
        + '<td class="num">' + t.draws + '</td><td class="num">' + t.losses + '</td>'
        + '<td class="num">' + t.goals_for + '</td><td class="num">' + t.goals_against + '</td>'
        + '<td class="num">' + gd + '</td><td class="num"><strong>' + t.points + '</strong></td></tr>';
    });
    html += '</tbody></table>';
  }
  html += '</div>';

  html += '<div class="chart-section"><div class="title">Signal Evaluation (vs played results)</div>';
  const sigKeys = Object.keys(appState.signals || {});
  if (!sigKeys.length) {
    html += '<p class="m-sub">No signal evaluation yet.</p>';
  } else {
    html += '<table class="eval-table"><thead><tr><th>Signal</th><th class="num">Accuracy</th><th class="num">Brier</th><th class="num">Available</th></tr></thead><tbody>';
    sigOrder.forEach(function(name) {
      const s = appState.signals[name];
      if (!s) return;
      const acc = typeof s.accuracy === "number" ? (s.accuracy * 100).toFixed(0) + "%" : "—";
      const brier = typeof s.brier === "number" ? s.brier.toFixed(3) : "—";
      const avail = s.available != null ? s.available : "—";
      html += '<tr><td>' + _esc(sigLabels[name] || name) + '</td>'
        + '<td class="num">' + acc + '</td><td class="num">' + brier + '</td><td class="num">' + avail + '</td></tr>';
    });
    html += '</tbody></table>';
  }
  html += '</div>';

  html += '<div class="chart-section"><div class="title">Acquisition &amp; Status</div><div id="acqHost"></div></div>';
  html += '<div id="validationSection">' + (_evalBlock() || "") + "</div>";
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

  openIntelModal({ titleHtml: titleHtml, sub: sub, bodyHtml: body });
}

function bindMatchClicks(scope) {
  const rows = scope.querySelectorAll(".match-clickable");
  rows.forEach(function(row) {
    row.onclick = function() { openMatchModalFromEl(row); };
  });
}

// ── Simulation ──
// Rendered through the shared shell (shared.js): title/purpose/state line,
// launcher, and provenance footer all come from the shell. LaLiga supplies
// the notNeeded / resultSlot / whatIf blocks and the popup config. The
// launcher opens the SHARED seedable popup with LaLiga's 1K..500K bounds.
let _simShellConfig = null;

function _simulationShellConfig() {
  const sim = appState.sim || {};
  const meta = appState.simMeta || {};
  const odds = sim.odds || [];
  const d = appState.data || {};
  const simBlock = d.simulation || {};
  const availability = simBlock.availability === "not_needed" ? "not_needed"
    : (simBlock.availability || "available");
  const requestState = (meta.status === "completed" || meta.status === "failed")
    ? meta.status : (simBlock.request_state || "not_requested");
  const hasResults = meta.status === "completed" && odds.length > 0;
  const actual = sim.n_iterations || meta.count || 0;

  const state = {
    availability: availability,
    request_state: requestState,
    hasResults: hasResults,
    meta: {
      count: actual,
      seed: sim.seed != null ? sim.seed : (meta.seed != null ? meta.seed : null),
    },
  };

  const opts = {
    purpose: "Monte Carlo projection of the season outcome. Played matches are unchanged; simulate to project the finished season.",
    stateLine: function() {
      const total = d.n_total_fixtures || ((d.n_played || 0) + (d.n_unplayed || 0));
      return "Season " + (d.season || "") + " &middot; "
        + (d.n_played || 0) + "/" + total + " played";
    },
    launchLabel: "Run Simulation",
    notNeeded: function() {
      const champ = d.champion
        ? " The " + (d.season || "season") + " champion is " + d.champion + "."
        : "";
      return '<div class="dim" style="padding:4px 8px;font-size:11px">'
        + "The season is fully played out; the final table is a matter of record, not projection."
        + champ
        + " See the Standings tab for the final table and the Overview tab for the season summary."
        + (hasResults ? " The archived projections below are from a run completed earlier." : "")
        + "</div>";
    },
    resultSlot: _simulationResultSlot,
    whatIf: availability !== "not_needed" ? _simulationWhatIf : null,
    provenanceBody: "Played matches and the league table are unchanged.",
    popup: {
      apiPrefix: API,
      min: 1000,
      max: 500000,
      presets: [10000, 50000, 100000, 500000],
      seed: true,
      initial: 50000,
      bodyBuilder: function(iters, seed) {
        return (seed != null) ? { iterations: iters, seed: seed } : { iterations: iters };
      },
      onComplete: async function() {
        try {
          const sim = await safeJson(API + "/simulation");
          const data = await safeJson(API + "/data");
          if (_stale(_transitionGen)) return;
          applySimulation(sim);
          appState.data = data;
          appState.standings = data.standings || [];
          appState.mode = data.mode || appState.mode;
          appState.phase = data.phase || appState.phase;
          appState.season = data.season || appState.season;
          appState.n_teams = data.n_teams || appState.n_teams;
          appState.n_played = data.n_played || appState.n_played;
          appState.n_unplayed = data.n_unplayed != null ? data.n_unplayed : appState.n_unplayed;
          appState.refresh = data.refresh || appState.refresh;
          render();
        } catch (e) {
          console.error("LaLiga simulation completion failed:", e);
        }
      },
    },
  };
  return { state: state, opts: opts };
}

function _simulationHtml() {
  const cfg = _simulationShellConfig();
  _simShellConfig = cfg;
  return renderSimulationShell(cfg.state, cfg.opts);
}

// Result slot (shown only for a preserved completed run). Top-10 champion
// probabilities, full champion bars, and the new projection-detail metrics
// (average position, top-6 / mid-table / bottom probabilities).
function _simulationResultSlot() {
  const sim = appState.sim || {};
  const odds = sim.odds || [];
  if (!odds.length) return "";

  let html = '<div class="chart-section"><div class="title">Projected Championship &mdash; Top 10</div>'
    + '<table class="eval-table"><thead><tr><th>Team</th><th class="num">Champion probability</th></tr></thead><tbody>';
  odds.slice(0, 10).forEach(function(o) {
    html += "<tr><td>" + _esc(o.team) + "</td><td class=\"num\">" + _simPct(o.champion_prob) + "</td></tr>";
  });
  html += "</tbody></table></div>";

  html += '<div class="chart-section"><div class="title">Champion Probability</div>';
  odds.forEach(function(o) {
    const p = o.champion_prob || 0;
    html += '<div class="champ-bar-row"><span class="cname">' + _esc(o.team) + "</span>"
      + '<div class="cbar-wrap"><div class="cbar" style="width:' + (p * 100).toFixed(1) + '%"></div></div>'
      + '<span class="cpct">' + (p * 100).toFixed(1) + "%</span></div>";
  });
  html += "</div>";

  const detail = _simComparisonRows();
  if (detail.length) {
    html += '<div class="chart-section"><div class="title">Projection Detail</div>'
      + '<table class="eval-table"><thead><tr><th>Team</th><th class="num">Avg pos</th>'
      + '<th class="num">Top 6</th><th class="num">Mid table</th><th class="num">Bottom</th></tr></thead><tbody>';
    detail.forEach(function(o) {
      html += "<tr><td>" + _esc(o.team) + "</td>"
        + '<td class="num">' + (o._avgPos != null ? _esc(o._avgPos.toFixed(1)) : "—") + "</td>"
        + '<td class="num">' + (o._t6 != null ? (o._t6.toFixed(1) + "%") : "—") + "</td>"
        + '<td class="num">' + (o._mid != null ? (o._mid.toFixed(1) + "%") : "—") + "</td>"
        + '<td class="num">' + (o._bot != null ? (o._bot.toFixed(1) + "%") : "—") + "</td></tr>";
    });
    html += "</tbody></table></div>";
  }
  return html;
}

// What-if slot: the in-tab (non-modal) head-to-head counterfactual runner.
// Rendered only when the shell's what-if gate holds (live season + completed
// run). The modal duplicate was removed — this is the single canonical copy.
function _simulationWhatIf() {
  return '<div class="chart-section"><div class="title">Head-to-Head What-If</div>'
    + '<div class="form-grid">'
    + '<label class="form-field"><span class="lbl">Match (by ID or search below)</span>'
    + '<input type="text" id="wiMatchSearch" placeholder="Type team name…"></label>'
    + '<label class="form-field"><span class="lbl">Fixture</span><select id="wiMatchSelect"></select></label>'
    + "</div><div id=\"wiStandalone\"></div></div>";
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
        (r.top5_baseline || []).forEach(function(o) {
          const bp = o.champion || 0;
          html += '<div class="champ-bar-row"><span class="cname">' + _esc(o.team) + "</span>"
            + '<div class="cbar-wrap"><div class="cbar" style="width:' + (bp * 100).toFixed(1) + '%"></div></div>'
            + '<span class="cpct">' + (bp * 100).toFixed(1) + '%</span></div>';
        });
        resEl.innerHTML = html;
      } catch (e) {
        resEl.innerHTML = '<span class="m-sub" style="color:#ff8a8a">Failed: ' + _esc(e.message) + "</span>";
      }
    };
  };
}

function bindSimulation() {
  // The shared shell owns the launcher wiring; the what-if select is the
  // single in-tab panel this module keeps.
  if (_simShellConfig) bindSimulationShell(_simShellConfig.state, _simShellConfig.opts);
  _populateWhatIfSelect();
}

async function refreshLive() {
  try {
    const data = await safeJson(API + "/data");
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
    // refreshLive is factual-only: it re-fetches /api/data (played results,
    // mode, phase) and re-renders. It deliberately does NOT re-fetch or
    // re-apply the simulation endpoint, so an existing simulation result /
    // sim tab state survives ordinary live refreshes (the sim tab only
    // re-renders from held appState.sim / appState.simMeta).
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