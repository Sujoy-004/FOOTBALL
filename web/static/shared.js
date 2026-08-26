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

// ── Competition Registry ──
const competitions = {
  worldcup: {
    label: "World Cup 2026",
    short: "WC",
    module: "wc",
    route: "/worldcup",
    apiPrefix: "/worldcup/api",
    tabs: ["Overview", "Bracket", "Standings"],
  },
  ucl: {
    label: "UCL 2025/26",
    short: "UCL",
    module: "ucl",
    route: "/ucl",
    apiPrefix: "/ucl/api",
    tabs: ["Overview", "Bracket", "Standings"],
  },
};

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
        <a class="lh-btn lh-btn-primary" href="#/ucl">Explore UCL 2025/26</a>
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
  const tabHtml = comp.tabs.map(t =>
    `<button class="tab-btn" data-tab="${t.toLowerCase().replace(/\s+/g, "")}">>> ${t}</button>`
  ).join("");
  const contentHtml = comp.tabs.map(t =>
    `<div class="tab-content" id="tab-${t.toLowerCase().replace(/\s+/g, "")}"></div>`
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
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    const tabId = "tab-" + btn.dataset.tab;
    const tabEl = document.getElementById(tabId);
    if (tabEl) tabEl.classList.add("active");
    if (btn.dataset.tab === "bracket") setTimeout(drawBracketConnectors, 300);
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

  // Load competition module
  try {
    const mod = await import("./" + (comp.module || slug) + ".js");
    loadedModules[slug] = mod;
    mod.init(comp);
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
  overlay.classList.add("show");
  document.getElementById("simStartBtn").onclick = () =>
    _startSim(apiPrefix, opts.onComplete, opts.bodyBuilder || (iters => ({ iterations: iters })));
}

async function _startSim(apiPrefix, onComplete, bodyBuilder) {
  if (_simPolling) return;
  _simPolling = true;
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
    const resp = await (await fetch(apiPrefix + "/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyBuilder(iters)),
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
  safeJson,
};
