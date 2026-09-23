// ── Shared live-refresh manager (Exchange 9C) ────────────────────────
// One manager instance per page; configuration lives on each registry
// entry, the reload hook is supplied by each competition module, and the
// shell owns all lifecycle wiring (activate/stop/visibility/tab clicks).
import { createRefreshManager } from "./refresh.js";

// ── Safe JSON fetch ──────────────────────────────────────────────────
// Never blindly parse: surfaces status + URL + body snippet on failure so
// empty/truncated/error responses produce a readable message instead of
// "Unexpected end of input".
async function safeJson(url, options) {
  const r = await fetch(url, options);
  const t = await r.text();
  if (!r.ok) {
    throw new Error("[" + r.status + "] " + url + ": "
      + (t.slice(0, 120) || "empty body"));
  }
  try {
    return JSON.parse(t);
  } catch (e) {
    throw new Error("[" + r.status + "] " + url
      + ": non-JSON response (" + (t.slice(0, 80) || "empty body") + ")");
  }
}

// ── Lightweight loading indicator ────────────────────────────────────
// Injects a small, theme-consistent spinner + label into targetEl, REPLACING
// its current content. Callers show it immediately before real async work
// (fetch/build) and let the subsequent real render overwrite it — the loader
// therefore reflects genuine in-flight work only, never an artificial delay.
// Safe to call repeatedly (idempotent replace) and with a null/absent target.
function renderLoading(targetEl, label) {
  if (!targetEl) return;
  const text = (label == null || label === "") ? "Loading..." : String(label);
  targetEl.innerHTML =
    '<div class="loading-state" role="status" aria-live="polite">'
    + '<span class="loading-spinner" aria-hidden="true"></span>'
    + '<span class="loading-label">' + _esc(text) + "</span>"
    + "</div>";
}

// ── Competition Registry ──
const competitions = {
  worldcup: {
    label: "World Cup 2026",
    short: "WC",
    module: "wc",
    route: "/worldcup",
    apiPrefix: "/worldcup/api",
    tabs: ["Overview", "Standings", "Bracket", "Simulation"],
    liveRefresh: { enabled: true, intervalMs: 45000, refreshOnActivation: true },
  },
  ucl: {
    label: "UEFA Champions League",
    short: "UCL",
    module: "ucl",
    route: "/ucl",
    apiPrefix: "/ucl/api",
    tabs: ["Overview", "Standings", "Bracket", "Simulation"],
    liveRefresh: { enabled: true, intervalMs: 90000, refreshOnActivation: true },
  },
  laliga: {
    label: "LaLiga EA Sports",
    short: "LaLiga",
    module: "laliga",
    route: "/laliga",
    apiPrefix: "/laliga/api",
    tabs: ["Overview", "Standings", "Fixtures", "Simulation"],
    liveRefresh: { enabled: true, intervalMs: 90000, refreshOnActivation: true },
  },
};

// ── Live-refresh wiring (Exchange 9C) ────────────────────────────────
// The manager polls the ACTIVE competition only, and only while the
// document is visible and the competition is enabled. All timing/visibility
// policy lives in refresh.js; these wrappers glue it to the SPA lifecycle.
const refreshManager = createRefreshManager();

function configureCompetitionRefresh(slug, opts) {
  const cfg = (competitions[slug] && competitions[slug].liveRefresh) || {};
  refreshManager.registerRefresh(slug, {
    reload: (opts && opts.reload) || (() => null),
    enabled: (opts && opts.enabled != null) ? opts.enabled : !!cfg.enabled,
    intervalMs: (opts && opts.intervalMs) || cfg.intervalMs || 60000,
    refreshOnActivation: (opts && opts.refreshOnActivation != null)
      ? opts.refreshOnActivation
      : cfg.refreshOnActivation !== false,
  });
}

// Shell call after a competition module boots: stop any prior timer, arm
// this competition's. Immediate refresh is intentionally NOT requested here
// — the module just kicked off its own first load.
function activateCompetitionRefresh(slug) {
  refreshManager.activateRefresh(slug, { immediate: false });
}

// Tab activation / visibility catch-up: never silently reuse stale data
// when the user returns to a live-data tab.
function requestCompetitionRefresh(slug) {
  refreshManager.requestRefresh(slug);
}

// Leaving to the landing page: full stop (timers + pending follow-ups).
function stopAllCompetitionRefresh() {
  refreshManager.stopAllRefresh();
}

// Visibility catch-up: the page became visible again — refresh the active
// competition (same activation semantics, still gated by its config).
document.addEventListener("visibilitychange", () => {
  refreshManager.notifyVisible();
});

// ── State ──
let currentCompetition = null;
let loadedModules = {};

// ── SPA Router ──
function navigate(hash) {
  const route = hash.replace(/^#/, "") || "/";
  if (route === "/") {
    renderLanding();
    return;
  }
  for (const [slug, comp] of Object.entries(competitions)) {
    if (route === comp.route) {
      loadCompetition(slug);
      return;
    }
  }
  renderLanding();
}

window.addEventListener("hashchange", () => navigate(window.location.hash));
window.addEventListener("load", () => navigate(window.location.hash));

document.addEventListener("click", e => {
  const el = e.target.closest("[data-route]");
  if (!el || el.dataset.disabled) return;
  const route = el.dataset.route;
  if (!route) return;
  if (el.tagName === "A" && el.getAttribute("href")) return;
  window.location.hash = "#" + route;
});

// ── Landing Page ──
function renderLanding() {
  currentCompetition = null;
  stopAllCompetitionRefresh();
  document.body.className = "";
  document.getElementById("landingBackdrop").classList.add("show");

  renderNavBar(null);

  document.getElementById("contentArea").innerHTML = `
    <div class="landing-hero">
      <div class="lh-badge">PREDICTIVE ANALYTICS</div>
      <h1 class="lh-title">FOOTBALL</h1>
      <p class="lh-sub">Multi-Competition Predictor</p>
      <p class="lh-tagline">Real-time match forecasting powered by Elo ratings, multi-signal blending, and Monte Carlo simulation across football's biggest tournaments.</p>
      <div class="lh-actions">
        <a class="lh-btn lh-btn-primary" href="#/worldcup">Explore WorldCup 2026</a>
        <a class="lh-btn lh-btn-primary" href="#/ucl">Explore UEFA Champions League</a>
        <a class="lh-btn lh-btn-primary" href="#/laliga">Explore LaLiga EA Sports</a>
      </div>
    </div>

    <div class="landing-section">
      <h2 class="ls-title">Competitions</h2>
      <div class="landing-cards">
        ${Object.entries(competitions).map(([slug, c]) => `
          <div class="lc-card ${slug} ${c.disabled ? "lc-disabled" : ""}" data-route="${c.route}"${c.disabled ? ' data-disabled="1"' : ""}>
            <div class="lcc-top">
              <div class="lcc-badge">${c.short}</div>
              <div class="lcc-name">${c.label}</div>
            </div>
            <div class="lcc-meta" id="lccMeta-${slug}">
              ${c.disabled
                ? '<span class="lcc-coming-soon">Coming Soon</span>'
                : '<span class="lcc-loading">Loading stats &hellip;</span>'}
            </div>
            <div class="lcc-chevron">${c.disabled ? 'Unavailable' : 'Launch Predictor &rarr;'}</div>
          </div>
        `).join("")}
      </div>
    </div>

    <div class="landing-section">
      <h2 class="ls-title">Prediction Engine</h2>
      <div class="lf-grid">
        <div class="lf-card">
          <div class="lfc-icon"><span class="lfc-dot"></span></div>
          <div class="lfc-name">Elo Ratings</div>
          <div class="lfc-desc">Dynamic team strength ratings updated with every match result, drawn from international and club competition history.</div>
        </div>
        <div class="lf-card">
          <div class="lfc-icon"><span class="lfc-dot"></span><span class="lfc-dot"></span></div>
          <div class="lfc-name">Multi-Signal Blending</div>
          <div class="lfc-desc">Refined Elo, market odds, rolling form, squad value, and rest days &mdash; blended by a transparent weighted ensemble.</div>
        </div>
        <div class="lf-card">
          <div class="lfc-icon"><span class="lfc-dot"></span><span class="lfc-dot"></span><span class="lfc-dot"></span></div>
          <div class="lfc-name">Monte Carlo Simulation</div>
          <div class="lfc-desc">Seeded tournament simulations projecting every knockout path, group outcome, and championship probability. You choose whether to simulate and how many runs to run.</div>
        </div>
        <div class="lf-card">
          <div class="lfc-icon"><span class="lfc-dot"></span><span class="lfc-dot"></span><span class="lfc-dot"></span><span class="lfc-dot"></span></div>
          <div class="lfc-name">What-If Analysis</div>
          <div class="lfc-desc">Adjust a team&rsquo;s Elo rating and re-run the seeded simulation &mdash; see exactly how championship probabilities shift.</div>
        </div>
      </div>
    </div>
  `;

  document.getElementById("statusBar").innerHTML =
    '<span id="statusLeft">Select a competition to begin</span><span id="statusRight"></span>';

  loadLandingStats();
}

async function loadLandingStats() {
  const results = await Promise.allSettled([
    safeJson("/worldcup/api/data"),
    safeJson("/ucl/api/data"),
    safeJson("/laliga/api/data"),
  ]);
  if (results[0].status === "fulfilled") {
    const wc = results[0].value;
    const el = document.getElementById("lccMeta-worldcup");
    if (el) el.innerHTML = [
      '<span class="lcc-stat"><strong>' + (wc.n_teams || '&hellip;') + '</strong> teams</span>',
      '<span class="lcc-stat"><strong>' + (wc.n_played || 0) + '</strong> matches played</span>',
    ].join('');
  }
  if (results[1].status === "fulfilled") {
    const ucl = results[1].value;
    const el = document.getElementById("lccMeta-ucl");
    if (el) {
      const parts = [
        '<span class="lcc-stat"><strong>' + (ucl.n_teams || '&hellip;') + '</strong> teams</span>',
      ];
      if (ucl.n_iterations > 100) {
        parts.push('<span class="lcc-stat"><strong>' + (ucl.n_iterations / 1000).toFixed(0) + 'K</strong> simulations</span>');
      } else if (ucl.n_iterations) {
        parts.push('<span class="lcc-stat"><strong>' + ucl.n_iterations + '</strong> matchdays</span>');
      }
      if (ucl.champion) {
        parts.push('<span class="lcc-stat"><strong>' + ucl.champion + '</strong> champion</span>');
      }
      el.innerHTML = parts.join('');
    }
  }
  if (results[2].status === "fulfilled") {
    const laliga = results[2].value;
    const el = document.getElementById("lccMeta-laliga");
    if (el) {
      const parts = [
        '<span class="lcc-stat"><strong>' + (laliga.n_teams || '&hellip;') + '</strong> teams</span>',
        '<span class="lcc-stat"><strong>' + (laliga.n_played || 0) + '/' + (laliga.n_total_fixtures || '&hellip;') + '</strong> matches</span>',
      ];
      if (laliga.n_iterations > 0) {
        parts.push('<span class="lcc-stat"><strong>' + (laliga.n_iterations / 1000).toFixed(0) + 'K</strong> simulations</span>');
      }
      el.innerHTML = parts.join('');
    }
  }
}

function renderNavBar(activeSlug) {
  document.getElementById("navBar").innerHTML = `
    <div class="nav-logo" data-route="/">
      <span class="nl-indicator"></span>
      <span class="nl-text">FOOTBALL</span>
    </div>
    <div class="nav-divider"></div>
    <div class="nav-section-label">Competitions</div>
    ${Object.entries(competitions).map(([s, c]) => `
      <button class="nav-btn ${s === activeSlug ? "active" : ""} ${c.disabled ? "disabled" : ""}"
        data-route="${c.route}"${c.disabled ? ' data-disabled="1"' : ""}>
        <span class="nb-badge">${c.short}</span>
        <span class="nb-label">${c.label}</span>
      </button>
    `).join("")}
  `;
}

// ── Load Competition Module ──
async function loadCompetition(slug) {
  const comp = competitions[slug];
  if (!comp) { renderLanding(); return; }
  document.getElementById("landingBackdrop").classList.remove("show");
  document.body.className = "competition-" + slug;
  currentCompetition = comp;

  renderNavBar(slug);

  // Build shell
  const tabHtml = comp.tabs.map((t, i) =>
    `<button class="tab-btn" role="tab" aria-selected="${i === 0}" data-tab="${t.toLowerCase().replace(/\s+/g, "")}">>> ${t}</button>`
  ).join("");
  const contentHtml = comp.tabs.map(t =>
    `<div class="tab-content" role="tabpanel" id="tab-${t.toLowerCase().replace(/\s+/g, "")}"></div>`
  ).join("");

  document.getElementById("contentArea").innerHTML = `
    <div class="tab-bar" id="tabBar">${tabHtml}</div>
    ${contentHtml}
    <div class="modal-overlay" id="modalOverlay">
      <div class="modal">
        <button class="modal-close" id="modalClose">&times;</button>
        <h2 id="modalTitle"></h2>
        <div class="m-sub" id="modalSub"></div>
        <div id="modalBody"></div>
      </div>
    </div>
  `;

  document.getElementById("statusBar").innerHTML =
    '<span id="statusLeft"></span><span id="statusRight"></span>';

  // Activate first tab
  const firstTab = document.querySelector(".tab-btn");
  if (firstTab) {
    firstTab.classList.add("active");
    const firstContent = document.getElementById("tab-" + firstTab.dataset.tab);
    if (firstContent) firstContent.classList.add("active");
  }

  // Wire tab switching
  document.getElementById("tabBar").addEventListener("click", e => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    document.querySelectorAll(".tab-btn").forEach(b => {
      const active = b === btn;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    const tabId = "tab-" + btn.dataset.tab;
    const tabEl = document.getElementById(tabId);
    if (tabEl) {
      tabEl.classList.add("active");
      // Surface a loader ONLY when this tab has no content yet — its first
      // reveal while the initial data load is still in flight. Already-built
      // tabs (and re-clicking the active tab) switch instantly with no flash.
      if (!tabEl.innerHTML.trim()) {
        const name = (btn.textContent || "").replace(/>/g, "").trim();
        renderLoading(tabEl, name ? "Loading " + name + "..." : undefined);
      }
    }
    if (btn.dataset.tab === "bracket") setTimeout(drawBracketConnectors, 300);
    // Returning to a live-data tab must not silently reuse stale data: ask
    // for a catch-up refresh (gated by the competition's liveRefresh config).
    requestCompetitionRefresh(slug);
  });

  // Wire modal
  document.getElementById("modalClose").onclick = () => {
    document.getElementById("modalOverlay").classList.remove("show");
    destroyModalCharts();
  };
  document.getElementById("modalOverlay").onclick = e => {
    if (e.target === document.getElementById("modalOverlay")) {
      document.getElementById("modalOverlay").classList.remove("show");
      destroyModalCharts();
    }
  };

  // Competition swap: show a loader in the visible (active) tab while the
  // module is dynamically imported and boots its first data load. The
  // module's own render overwrites this loader once real content is ready,
  // so it lasts exactly as long as the real work does.
  const activeContent = document.querySelector(".tab-content.active");
  if (activeContent) renderLoading(activeContent, "Loading " + comp.label + "...");

  // Load competition module
  try {
    const mod = await import("./" + (comp.module || slug) + ".js");
    loadedModules[slug] = mod;
    mod.init(comp);
    // Arm live refresh now that the module registered its reload hook.
    activateCompetitionRefresh(slug);
  } catch (e) {
    document.getElementById("contentArea").innerHTML =
      '<div style="color:#ff6b6b;padding:20px">Failed to load ' + comp.label + ': ' + e.message + '</div>';
  }
}



function buildTable(teams, cols, keyMap) {
  const show = cols || Object.keys(keyMap || {champion: "Champion"});
  const labels = keyMap || {champion: "Champion", final: "Final", sf: "SF", qf: "QF"};
  let h = "<tr><th>#</th><th>Team</th>";
  show.forEach(c => h += "<th>" + (labels[c] || c) + "</th>");
  h += "<th></th></tr>";
  let html = "<table>" + h;
  teams.forEach((t, i) => {
    const pct = t[show[0]] || 0;
    const barW = Math.max(2, pct * 2);
    html += '<tr><td class="num">' + (i + 1) + "</td><td>" + t.name + "</td>";
    show.forEach(c => html += '<td class="num">' + (t[c] || 0).toFixed(1) + "%</td>");
    html += '<td><div class="bar-wrap"><div class="bar" style="width:' + barW + 'px"></div></div></td></tr>';
  });
  return html + "</table>";
}

// ── Modal chart cleanup ──
let modalCharts = {};

function destroyModalCharts() {
  Object.values(modalCharts).forEach(c => { try { c.destroy(); } catch {} });
  modalCharts = {};
}

// ── Intelligence modal opener (thin shared wrapper) ──────────────────
// Fills the standard competition modal shell (#modalOverlay/#modalTitle/
// #modalSub/#modalBody) with caller-supplied content and shows it. No
// redesign: same ids/classes and close wiring installed by loadCompetition.
function openIntelModal(opts) {
  const overlay = document.getElementById("modalOverlay");
  if (!overlay) return null;
  const o = opts || {};
  const titleEl = document.getElementById("modalTitle");
  const subEl = document.getElementById("modalSub");
  const bodyEl = document.getElementById("modalBody");
  if (titleEl && o.titleHtml != null) titleEl.innerHTML = o.titleHtml;
  if (subEl) subEl.textContent = o.sub != null ? String(o.sub) : "";
  if (bodyEl && o.bodyHtml != null) bodyEl.innerHTML = o.bodyHtml;
  overlay.classList.add("show");
  const modal = overlay.querySelector(".modal");
  if (modal) modal.scrollTop = 0;
  return overlay;
}

// ── Bracket connector helpers (shared between wc.js and ucl.js) ──
// Connectors are computed purely from the rendered DOM: each .match-card
// carries data-mid plus a JSON-encoded data-parents array. No module-level
// bracket globals are involved. Call with explicit elements, or no-arg to
// target the default #bracketGrid/#bracketSvg pair (transition shim).
function drawBracketConnectors(gridEl, svgEl) {
  const grid = gridEl || document.getElementById("bracketGrid");
  const svg = svgEl || document.getElementById("bracketSvg");
  if (!svg || !grid) return;
  const cols = grid.querySelectorAll(".bracket-col");
  if (cols.length < 2) return;

  svg.style.width = grid.scrollWidth + "px";
  svg.style.height = grid.scrollHeight + "px";

  const colRects = [];
  cols.forEach(c => {
    const r = c.getBoundingClientRect();
    colRects.push({ left: r.left, right: r.right, top: r.top, bottom: r.bottom });
  });
  const gridRect = grid.getBoundingClientRect();
  const relX = (colIdx, side) => colRects[colIdx][side] - gridRect.left;
  const relY = (el) => { const r = el.getBoundingClientRect(); return (r.top + r.bottom) / 2 - gridRect.top; };

  let paths = "";
  for (let ci = 0; ci < cols.length - 1; ci++) {
    const rightCards = cols[ci + 1].querySelectorAll(".match-card");
    rightCards.forEach(card => {
      let parentIds = [];
      try { parentIds = JSON.parse(card.dataset.parents || "[]"); } catch { parentIds = []; }
      if (!parentIds.length) return;
      const x1 = relX(ci, "right");
      const x2 = relX(ci + 1, "left");
      const xm = (x1 + x2) / 2;
      const parentY = relY(card);

      parentIds.forEach(pid => {
        const srcEl = cols[ci].querySelector('.match-card[data-mid="' + pid + '"]');
        if (!srcEl) return;
        const childY = relY(srcEl);
        paths += '<path d="M ' + x1 + " " + childY + " L " + xm + " " + childY + " L " + xm + " " + parentY + " L " + x2 + " " + parentY + '" fill="none" stroke="#153D4C" stroke-width="1.5"/>';
      });
    });
  }
  svg.innerHTML = paths;
}

// ── Shared bracket renderer ──────────────────────────────────────────
// Generic knockout-tree renderer. Competition vocabulary (labels, ordering,
// formatting) lives entirely in bracketState/adapter — never here.
// Geometry replicates the WC tree: one flex column per stage, leaf-order
// ROW_UNIT spacer math, SVG connectors wired from each card's data-parents.
const _ROW_UNIT = 28;

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function _matchStatusClass(m) {
  const isPlayed = m.status === "played";
  const isTbd = (!m.teamA && !m.teamB) || (!isPlayed && !m.winner);
  if (isTbd) return "tbd mc-tbd";
  if (isPlayed) return "played mc-played";
  return "upcoming mc-upcoming";
}

function _buildMatchCard(m, adapter) {
  const card = document.createElement("div");
  card.className = "match-card " + _matchStatusClass(m)
    + (adapter.cardThemeClass ? " " + adapter.cardThemeClass : "");
  card.dataset.mid = m.id || "";
  card.dataset.parents = JSON.stringify(m.parents || []);

  const ta = m.teamA || "TBD";
  const tb = m.teamB || "TBD";
  let inner = '<div class="m-teams">'
    + '<span class="m-team' + (m.winner && m.winner === m.teamA ? " winner" : "") + '">' + _esc(ta) + "</span>"
    + '<span class="m-score">' + (m.resultLine != null ? _esc(m.resultLine) : "?-?") + "</span>"
    + '<span class="m-team' + (m.winner && m.winner === m.teamB ? " winner" : "") + '">' + _esc(tb) + "</span></div>";

  if (m.provenance === "simulated") {
    inner += '<span class="badge-sim">' + _esc(adapter.simLabel || "SIM") + "</span>";
  } else if (m.provenance === "manual") {
    inner += '<span class="badge-manual">' + _esc(adapter.manualLabel || "MAN") + "</span>";
  }

  const winnerLine = adapter.winnerLabel ? adapter.winnerLabel(m) : null;
  if (winnerLine) inner += '<div class="m-winner-label">' + winnerLine + "</div>";

  if (m.detailHtml) inner += '<div class="tie-detail">' + m.detailHtml + "</div>";

  if (m.sim) {
    if (m.sim.line) inner += '<div class="m-sim-line">' + _esc(m.sim.line) + "</div>";
    if (typeof m.sim.probA === "number") {
      const pct = Math.round(m.sim.probA * 100);
      inner += '<div class="m-sim-line">SIM ' + pct + "% / " + (100 - pct) + "%</div>";
    }
  }

  if (adapter.cardExtrasHtml) inner += adapter.cardExtrasHtml(m);

  card.innerHTML = inner;
  if (m.clickable && adapter.onMatch) {
    card.onclick = () => adapter.onMatch(m);
  }
  return card;
}

function renderBracketTree(containerEl, bracketState, adapter) {
  if (!containerEl || !bracketState || !Array.isArray(bracketState.stages)) return;
  const a = adapter || {};
  const stages = bracketState.stages.filter(st => st && Array.isArray(st.matches) && st.matches.some(m => m && m.id));
  if (!stages.length) return;

  // id -> match across every stage (parents may reference any stage)
  const byId = {};
  stages.forEach(st => st.matches.forEach(m => { if (m && m.id) byId[m.id] = m; }));

  // Leaf order derives from the first tree stage's matches, in array order.
  // Deeper matches map onto these leaves by recursive parents expansion
  // (positional: parents[0] feeds slot A, parents[1] slot B).
  const treeStages = stages.filter(st => st.layout !== "list");
  const leafSource = treeStages.length ? treeStages[0] : stages[0];
  const leafOrder = leafSource.matches.map(m => m.id).filter(Boolean);
  const leafIdx = {};
  leafOrder.forEach((id, i) => { if (leafIdx[id] === undefined) leafIdx[id] = i; });

  function leafOrderOf(mid) {
    if (mid == null) return [];
    const m = byId[mid];
    if (!m) return [mid];
    if (leafIdx[mid] !== undefined) return [mid];
    if (!m.parents || !m.parents.length) return [mid];
    return [...leafOrderOf(m.parents[0]), ...leafOrderOf(m.parents[1])];
  }

  function rowRange(mid) {
    const m = byId[mid];
    if (!m) return { start: 0, end: Math.max(1, leafOrder.length) };
    const leaves = leafOrderOf(mid);
    const selfIdx = leafIdx[mid] !== undefined ? leafIdx[mid] : 0;
    const firstIdx = leaves.length && leafIdx[leaves[0]] !== undefined ? leafIdx[leaves[0]] : selfIdx;
    const lastRaw = leaves.length ? leafIdx[leaves[leaves.length - 1]] : undefined;
    const lastIdx = lastRaw !== undefined ? lastRaw : firstIdx;
    return { start: firstIdx, end: Math.max(lastIdx + 1, firstIdx + 1) };
  }

  const wrap = document.createElement("div");
  wrap.className = "bracket-wrap";
  const grid = document.createElement("div");
  grid.className = "bracket-grid";
  grid.id = "bracketGrid";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "bracket-svg");
  svg.id = "bracketSvg";
  wrap.appendChild(grid);
  wrap.appendChild(svg);

  const nStages = stages.length;
  stages.forEach((st, si) => {
    const col = document.createElement("div");
    col.className = "bracket-col";
    col.style.flex = a.columnFlex ? String(a.columnFlex(st, si, nStages)) : "1";
    col.innerHTML = '<div class="col-head">' + _esc(st.label || st.id || "") + "</div>";

    if (st.layout === "list" && a.listLayout && typeof a.listLayout.render === "function") {
      const body = document.createElement("div");
      body.innerHTML = a.listLayout.render(st);
      while (body.firstChild) col.appendChild(body.firstChild);
    } else if (st.layout === "list") {
      st.matches.forEach(m => {
        const slot = document.createElement("div");
        slot.className = "match-slot";
        slot.appendChild(_buildMatchCard(m, a));
        col.appendChild(slot);
      });
    } else {
      const ms = st.matches.slice().sort((x, y) => rowRange(x.id).start - rowRange(y.id).start);
      let lastEnd = 0;
      ms.forEach(m => {
        const rr = rowRange(m.id);
        const gap = rr.start - lastEnd;
        if (gap > 0) {
          const sp = document.createElement("div");
          sp.className = "match-slot";
          sp.style.minHeight = (gap * _ROW_UNIT) + "px";
          col.appendChild(sp);
        }
        lastEnd = rr.end;

        const slot = document.createElement("div");
        slot.className = "match-slot";
        slot.style.minHeight = Math.max((rr.end - rr.start) * _ROW_UNIT, 40) + "px";
        slot.appendChild(_buildMatchCard(m, a));
        col.appendChild(slot);
      });
    }
    grid.appendChild(col);
  });

  containerEl.appendChild(wrap);
  setTimeout(() => drawBracketConnectors(grid, svg), 50);
}

// ── Acquisition status panel ─────────────────────────────────────────
// Truthful data-acquisition checklist: every glyph/label/detail is rendered
// verbatim from the passed structure — nothing here infers or embellishes.
const _ACQ_GLYPHS = { ok: "OK", pending: "...", error: "ERR", unavailable: "--" };

function renderAcquisitionPanel(el, acq) {
  if (!el || !acq) return;
  const staleCls = (acq.stale || acq.error) ? " acq-src-stale" : "";
  const srcCls = acq.mode === "snapshot" ? "acq-src-snap" : "acq-src-live";

  let h = '<div class="acq-panel">';
  h += '<div class="acq-head"><span class="acq-comp">' + _esc(acq.competition || "") + "</span>"
    + '<span class="acq-src ' + srcCls + staleCls + '">' + _esc(acq.source || "") + "</span></div>";
  if (acq.updatedAt) h += '<div class="acq-updated">Updated: ' + _esc(acq.updatedAt) + "</div>";
  if (acq.error) h += '<div class="acq-error-line">' + _esc(acq.error) + "</div>";
  if (acq.notice) h += '<div class="acq-notice-line">' + _esc(acq.notice) + "</div>";
  (acq.stages || []).forEach(s => {
    const state = _ACQ_GLYPHS[s.state] ? s.state : "unavailable";
    const cls = state === "pending" ? "pend" : state;
    let detail = s.detail ? _esc(s.detail) : "";
    if (state === "unavailable" && !detail) detail = "unavailable";
    h += '<div class="acq-stage acq-' + cls + '">'
      + '<span class="acq-glyph">' + _ACQ_GLYPHS[state] + "</span>"
      + '<span class="acq-label">' + _esc(s.label || s.key || "") + "</span>"
      + (typeof s.count === "number" ? '<span class="acq-count">' + s.count + "</span>" : "")
      + (detail ? '<span class="acq-detail">' + detail + "</span>" : "")
      + "</div>";
  });
  h += "</div>";
  el.innerHTML = h;
}

// ── Status bar helpers ──
function updateStatusBar(left, right) {
  const leftEl = document.getElementById("statusLeft");
  const rightEl = document.getElementById("statusRight");
  if (leftEl) leftEl.innerHTML = left;
  if (rightEl && right) rightEl.innerHTML = right;
}

// ── Shared Simulation Popup ──
let _simOverlay = null;
let _simPolling = false;

function createSimPopup() {
  if (_simOverlay) return _simOverlay;
  const overlay = document.createElement("div");
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
      <div id="simSeedRow" style="display:none">
        <p style="margin-bottom:4px">Optional seed:</p>
        <input type="number" id="simSeedInput" placeholder="seed (auto)">
      </div>
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
  overlay.querySelectorAll(".sim-presets button").forEach(btn => {
    btn.addEventListener("click", () => {
      overlay.querySelectorAll(".sim-presets button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("simCustomIters").value = btn.dataset.iters;
    });
  });
  document.getElementById("simCancelBtn").addEventListener("click", () => overlay.classList.remove("show"));
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.classList.remove("show"); });
  _simOverlay = overlay;
  return overlay;
}

function showSimPopup(apiPrefix, opts = {}) {
  const overlay = createSimPopup();
  // Per-competition bounds/presets. Defaults preserve LaLiga's existing
  // behavior; WC overrides {min:1, max:1000000}. Preset row + input are
  // rebuilt on each show so a later competition cannot inherit stale bounds.
  const presets = Array.isArray(opts.presets) ? opts.presets
    : [10000, 50000, 100000, 500000];
  const min = opts.min != null ? opts.min : 1000;
  const max = opts.max != null ? opts.max : 500000;
  const initial = opts.initial != null ? opts.initial : 50000;

  const presetsEl = document.getElementById("simPresets");
  if (presetsEl) {
    presetsEl.innerHTML = presets.map(p =>
      '<button data-iters="' + p + '"' + (p === initial ? ' class="active"' : "") + ">"
      + (p >= 1000 ? (p / 1000) + "K" : String(p)) + "</button>"
    ).join("");
    presetsEl.querySelectorAll(".sim-presets button").forEach(btn => {
      btn.addEventListener("click", () => {
        presetsEl.querySelectorAll(".sim-presets button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const input = document.getElementById("simCustomIters");
        if (input) input.value = btn.dataset.iters;
      });
    });
  }
  const customInput = document.getElementById("simCustomIters");
  if (customInput) {
    customInput.min = String(min);
    customInput.max = String(max);
    customInput.value = String(initial);
  }
  // Seed row: shown only when opts.seed is truthy; hidden state clears any
  // stale value so a prior competition's seed never leaks into this run.
  const seedRow = document.getElementById("simSeedRow");
  if (seedRow) seedRow.style.display = opts.seed ? "" : "none";
  const seedInput = document.getElementById("simSeedInput");
  if (seedInput && !opts.seed) seedInput.value = "";

  overlay.classList.add("show");
  document.getElementById("simStartBtn").onclick = () =>
    _startSim(apiPrefix, opts.onComplete, opts.bodyBuilder || (iters => ({ iterations: iters })));
}

async function _startSim(apiPrefix, onComplete, bodyBuilder) {
  if (_simPolling) return;
  _simPolling = true;
  const iters = parseInt(document.getElementById("simCustomIters").value) || 50000;
  const seedEl = document.getElementById("simSeedInput");
  let seed = null;
  if (seedEl && seedEl.value !== "") {
    const n = parseInt(seedEl.value, 10);
    seed = Number.isFinite(n) ? n : null;
  }
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
    const resp = await (await fetch(apiPrefix + "/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyBuilder(iters, seed)),
    })).json();
    if (resp.error) throw new Error(resp.error);
    if (resp.status === "not_needed") {
      progressLbl.textContent = resp.message || "Nothing to simulate.";
      startBtn.disabled = false;
      cancelBtn.style.display = "";
      _simPolling = false;
      return;
    }
    if (resp.status === "validation_error") {
      throw new Error(resp.error || "invalid simulation request");
    }
    const taskId = resp.task_id;
    const t0 = Date.now();
    await new Promise((resolve, reject) => {
      const poll = setInterval(async () => {
        try {
          const p = await (await fetch(apiPrefix + "/simulation/progress/" + taskId)).json();
          if (p.error) { clearInterval(poll); reject(new Error(p.error)); return; }
          progressFill.style.width = p.progress + "%";
          const elapsed = ((Date.now() - t0) / 1000).toFixed(0);
          let label = p.stage || "Simulating...";
          if (p.total_iterations > 0) label += "  " + (p.iteration || 0).toLocaleString() + "/" + p.total_iterations.toLocaleString();
          label += "  (" + p.progress.toFixed(0) + "%)  " + elapsed + "s";
          if (p.elapsed) label += "  ETA: " + Math.max(0, Math.round(p.elapsed * ((100 - p.progress) / Math.max(p.progress, 1)))) + "s";
          progressLbl.textContent = label;
          if (p.status === "completed") { clearInterval(poll); resolve(); }
          if (p.status === "failed" || p.status === "not_found") { clearInterval(poll); reject(new Error(p.error || "simulation failed")); }
        } catch (e) { clearInterval(poll); reject(e); }
      }, 200);
    });
    document.getElementById("simPopupOverlay").classList.remove("show");
    progressWrap.style.display = "none";
    progressLbl.style.display = "none";
    _simPolling = false;
    if (onComplete) onComplete(iters);
  } catch (e) {
    progressLbl.textContent = "Error: " + (e.message || "unknown");
    startBtn.disabled = false;
    cancelBtn.style.display = "";
    _simPolling = false;
  }
}

// ── Shared Simulation Shell (Phase 12D) ──────────────────────────────
// Pure presentation shell for the Simulation tab: one canonical layout,
// one state machine driven solely by availability/request_state, one
// provenance footer. Competition modules supply the slot callbacks
// (resultSlot / whatIf / notNeeded) and the popup config; structure only
// lives here. Deterministic string in/string out — usable without a DOM.

const _SIM_HONESTY = "Projected probabilities, not real results. Played results are unchanged.";
const _SIM_FAILED_BODY = "The last simulation failed; no projected probabilities exist.";
const _SIM_IDLE_LINE = "No simulation has been run in this session yet.";
const _SIM_RUNNING_LINE = "A simulation is currently running. Progress shows in the popup.";

function _simProvenanceFooter(state, opts) {
  const meta = (state && state.meta) || {};
  const count = typeof meta.count === "number" ? meta.count : 0;
  const seed = meta.seed != null ? meta.seed : "auto";
  let body = _SIM_HONESTY;
  if (opts && opts.provenanceBody) body += " " + opts.provenanceBody;
  return '<div class="sim-provenance">'
    + '<div class="title">SIMULATION &middot; ' + count.toLocaleString() + ' RUNS'
    + ' &middot; seed ' + _esc(String(seed)) + "</div>"
    + '<div class="body">' + _esc(body) + "</div></div>";
}

function _simProvenanceFailed() {
  return '<div class="sim-provenance failed">'
    + '<div class="title">SIMULATION &middot; FAILED</div>'
    + '<div class="body">' + _esc(_SIM_FAILED_BODY) + "</div></div>";
}

function renderSimulationShell(state, opts) {
  const o = opts || {};
  const st = state || {};
  const availability = st.availability || "available";
  const req = st.request_state || "not_requested";
  const hasResults = !!st.hasResults;
  const notNeeded = availability === "not_needed";
  const title = o.title != null ? o.title : "Simulation";
  const launchLabel = o.launchLabel != null ? o.launchLabel : "Run Simulation";

  // Section 1 — title + purpose + current-state line + launcher + run line.
  let h = '<div class="chart-section"><div class="title">' + _esc(title) + "</div>";
  if (o.purpose) h += '<p class="m-sub">' + _esc(o.purpose) + "</p>";
  const stateLine = typeof o.stateLine === "function" ? o.stateLine(st)
    : (o.stateLine != null ? o.stateLine : "");
  if (stateLine) h += '<div class="dim">' + _esc(stateLine) + "</div>";

  if (!notNeeded) {
    const running = req === "running";
    h += '<div style="padding:4px 0 4px">'
      + '<button class="status-btn" id="simLaunchBtn"'
      + (running ? " disabled" : "") + ">" + _esc(launchLabel) + "</button>"
      + ' <span id="simLaunchState" class="dim" style="font-size:11px"></span>'
      + "</div>";
    if (running) h += '<div class="dim">' + _SIM_RUNNING_LINE + "</div>";
    else if (req === "failed") h += '<div class="dim">' + _esc(_SIM_FAILED_BODY) + "</div>";
    else if (!(req === "completed" && hasResults)) h += '<div class="dim">' + _SIM_IDLE_LINE + "</div>";
  }
  h += "</div>";

  // Decided-state block: after the title section, before any slot. The
  // launcher is never rendered under not_needed.
  if (notNeeded && typeof o.notNeeded === "function") h += o.notNeeded(st) || "";

  // Competition slots: only for a preserved completed run (failed never
  // shows fabricated numbers; running keeps a prior finished run visible).
  const showResults = notNeeded
    ? (req === "completed" && hasResults)
    : (hasResults && (req === "completed" || req === "running"));
  if (showResults && typeof o.resultSlot === "function") h += o.resultSlot(st) || "";
  if (!notNeeded && req === "completed" && hasResults && typeof o.whatIf === "function") {
    h += o.whatIf(st) || "";
  }

  // Provenance footer.
  if (notNeeded) {
    if (req === "completed" && hasResults) h += _simProvenanceFooter(st, o);
  } else if (req === "failed") {
    h += _simProvenanceFailed();
  } else if (showResults) {
    h += _simProvenanceFooter(st, o);
  }
  return h;
}

// DOM wiring after the shell HTML is injected. onclick assignment (not
// addEventListener) makes repeated re-binds idempotent; clicks on a
// disabled launcher are ignored; a missing button is a quiet no-op.
function bindSimulationShell(state, opts) {
  const btn = document.getElementById("simLaunchBtn");
  if (!btn) return;
  const o = opts || {};
  const popup = o.popup || {};
  const st = state || {};
  const running = st.availability !== "not_needed" && st.request_state === "running";
  btn.disabled = running;
  btn.onclick = () => {
    if (btn.disabled) return;
    showSimPopup(popup.apiPrefix, {
      min: popup.min,
      max: popup.max,
      presets: popup.presets,
      seed: popup.seed,
      initial: popup.initial,
      onComplete: popup.onComplete,
      bodyBuilder: popup.bodyBuilder,
    });
  };
}

// ── Exports ──
export {
  competitions,
  currentCompetition,
  buildTable,
  destroyModalCharts,
  modalCharts,
  drawBracketConnectors,
  renderBracketTree,
  renderAcquisitionPanel,
  updateStatusBar,
  createSimPopup,
  showSimPopup,
  renderSimulationShell,
  bindSimulationShell,
  openIntelModal,
  safeJson,
  renderLoading,
  configureCompetitionRefresh,
  activateCompetitionRefresh,
  requestCompetitionRefresh,
  stopAllCompetitionRefresh,
};
