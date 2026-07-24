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
    tabs: ["Terminal", "Overview", "League Table", "Bracket", "Odds", "Signals"],
  },
  euro: {
    label: "Euro 2028",
    short: "EUR",
    module: null,
    route: "/euro",
    apiPrefix: "/euro/api",
    disabled: true,
    tabs: [],
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
          <div class="lfc-desc">Dynamic team strength ratings updated with every match result, calibrated across international and club competitions.</div>
        </div>
        <div class="lf-card">
          <div class="lfc-icon"><span class="lfc-dot"></span><span class="lfc-dot"></span></div>
          <div class="lfc-name">Multi-Signal Blending</div>
          <div class="lfc-desc">Refined Elo, market odds, manager effect, squad value, defensive quality, availability, and team synergy &mdash; weighted by proven accuracy.</div>
        </div>
        <div class="lf-card">
          <div class="lfc-icon"><span class="lfc-dot"></span><span class="lfc-dot"></span><span class="lfc-dot"></span></div>
          <div class="lfc-name">Monte Carlo Simulation</div>
          <div class="lfc-desc">50,000 tournament simulations projecting every knockout path, group outcome, and championship probability with statistical confidence.</div>
        </div>
        <div class="lf-card">
          <div class="lfc-icon"><span class="lfc-dot"></span><span class="lfc-dot"></span><span class="lfc-dot"></span><span class="lfc-dot"></span></div>
          <div class="lfc-name">What-If Analysis</div>
          <div class="lfc-desc">Ask &ldquo;what if my team&rsquo;s star player is injured?&rdquo; or &ldquo;what if they hit peak form?&rdquo; &mdash; see instant probability shifts.</div>
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
    fetch("/worldcup/api/data").then(r => r.json()),
    fetch("/ucl/api/data").then(r => r.json()),
  ]);
  if (results[0].status === "fulfilled") {
    const wc = results[0].value;
    const el = document.getElementById("lccMeta-worldcup");
    if (el) el.innerHTML = [
      '<span class="lcc-stat"><strong>' + (wc.n_teams || '&hellip;') + '</strong> teams</span>',
      '<span class="lcc-stat"><strong>' + (wc.total_iterations ? (wc.total_iterations / 1000).toFixed(0) + 'K' : '&hellip;') + '</strong> simulations</span>',
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
    '<span id="statusLeft"></span><span id="statusRight"><button class="drawer-btn" id="drawerToggle">>_</button></span>';

  document.getElementById("drawerToggle").onclick = toggleDrawer;

  // Activate first tab
  const firstTab = document.querySelector(".tab-btn");
  if (firstTab) {
    firstTab.classList.add("active");
    const firstContent = document.getElementById("tab-" + firstTab.dataset.tab);
    if (firstContent) firstContent.classList.add("active");
    if (firstTab.dataset.tab === "terminal") focusTermInput();
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
    if (btn.dataset.tab === "terminal") focusTermInput();
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

// ── Terminal (shared) ──
let termBuffer = "";
let termHistory = [];
let termHistoryIdx = -1;
let termBooting = false;

function termAdd(text, cls) {
  const termOutput = document.getElementById("termOutput");
  const drawerOutput = document.getElementById("drawerOutput");
  if (termOutput) {
    const div = document.createElement("div");
    div.className = "line";
    if (text) {
      const span = document.createElement("span");
      if (cls) span.className = cls;
      span.innerHTML = text;
      div.appendChild(span);
    }
    termOutput.appendChild(div);
  }
  if (drawerOutput) {
    const div = document.createElement("div");
    div.className = "line";
    if (text) {
      const span = document.createElement("span");
      if (cls) span.className = cls;
      span.innerHTML = text;
      div.appendChild(span);
    }
    drawerOutput.appendChild(div);
    drawerOutput.scrollTop = drawerOutput.scrollHeight;
  }
}

function termScroll() {
  const tt = document.getElementById("tab-terminal");
  if (tt && tt.classList.contains("active")) tt.scrollIntoView(false);
}

function focusTermInput() {
  const inp = document.getElementById("terminal-input");
  if (inp) inp.focus();
}

function toggleDrawer() {
  const drawer = document.getElementById("terminalDrawer");
  if (!drawer) return;
  drawer.classList.toggle("open");
  const btn = document.querySelector(".drawer-btn");
  if (drawer.classList.contains("open")) {
    if (btn) btn.classList.add("active");
    focusTermInput();
    const drawerOutput = document.getElementById("drawerOutput");
    if (drawerOutput) drawerOutput.scrollTop = drawerOutput.scrollHeight;
  } else {
    if (btn) btn.classList.remove("active");
  }
}

function closeDrawer() {
  const drawer = document.getElementById("terminalDrawer");
  if (drawer) drawer.classList.remove("open");
}

document.addEventListener("keydown", e => {
  if (e.ctrlKey && e.key === "`") {
    e.preventDefault();
    toggleDrawer();
  }
});

document.addEventListener("click", e => {
  if (e.target.id === "drawerClose") closeDrawer();
});

function termShowPrompt() {
  const line = document.getElementById("termInputLine");
  const display = document.getElementById("termInputDisplay");
  const cursor = document.querySelector(".term-cursor");
  if (line) line.style.display = "flex";
  termBuffer = "";
  if (display) display.textContent = "";
  if (cursor) cursor.style.display = "inline";
  termScroll();
  focusTermInput();
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

async function termRenderBootStep(step) {
  const timeStr = step.output.split("]")[0].replace("[", "") || "--";
  const statusChar = step.status === "ok" ? "OK" : "FAIL";
  const cls = step.status === "ok" ? "ok" : "danger";
  termAdd('<span class="ts">[' + timeStr + ']</span> <span class="dim">' + step.step + "...</span>");
  termScroll();
  await new Promise(r => setTimeout(r, Math.min(300 + step.elapsed * 50, 800)));
  const termOutput = document.getElementById("termOutput");
  const last = termOutput ? termOutput.lastElementChild : null;
  if (last) last.innerHTML = '<span class="ts">[' + timeStr + ']</span> <span class="' + cls + '">' + statusChar + '</span> <span class="dim">' + step.step + '</span> <span class="dim">(' + step.elapsed.toFixed(1) + "s)</span>";
}

// ── Modal chart cleanup ──
let modalCharts = {};

function destroyModalCharts() {
  Object.values(modalCharts).forEach(c => { try { c.destroy(); } catch {} });
  modalCharts = {};
}

// ── Terminal input wiring (called by competition modules) ──
let termInputHandler = null;

function wireTerminal(onExec) {
  termInputHandler = onExec;
  const inp = document.getElementById("terminal-input");
  if (!inp) return;
  inp.addEventListener("keydown", e => {
    if (termBooting) { e.preventDefault(); return; }
    const display = document.getElementById("termInputDisplay");
    const drawerDisplay = document.getElementById("drawerInputDisplay");
    const cursor = document.querySelector(".term-cursor");
    function syncDisplay() {
      if (display) display.textContent = termBuffer;
      if (drawerDisplay) drawerDisplay.textContent = termBuffer;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const cmd = termBuffer;
      termAdd('<span class="prompt"></span>' + cmd);
      termHistory.push(cmd);
      termHistoryIdx = termHistory.length;
      if (display) display.textContent = "";
      if (drawerDisplay) drawerDisplay.textContent = "";
      if (cursor) cursor.style.display = "none";
      if (termInputHandler) termInputHandler(cmd);
    } else if (e.key === "Backspace") {
      termBuffer = termBuffer.slice(0, -1);
      syncDisplay();
    } else if (e.key === "ArrowUp") {
      if (!termHistory.length) return;
      termHistoryIdx = Math.max(0, termHistoryIdx - 1);
      termBuffer = termHistory[termHistoryIdx] || "";
      syncDisplay();
    } else if (e.key === "ArrowDown") {
      termHistoryIdx = Math.min(termHistory.length, termHistoryIdx + 1);
      termBuffer = termHistoryIdx >= termHistory.length ? "" : termHistory[termHistoryIdx] || "";
      syncDisplay();
    } else if (e.key.length === 1) {
      termBuffer += e.key;
      syncDisplay();
    }
  });
}

// ── Bracket connector helpers (shared between wc.js and ucl.js) ──
function drawBracketConnectors() {
  const svg = document.getElementById("bracketSvg");
  const grid = document.getElementById("bracketGrid");
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

  // Get bracket data from whichever module loaded it
  const bracketData = window.__bracketData || {};
  const byId = {};
  for (const [, ms] of Object.entries(bracketData)) for (const m of ms) byId[m.match_id] = m;

  let paths = "";
  for (let ci = 0; ci < cols.length - 1; ci++) {
    const rightCards = cols[ci + 1].querySelectorAll(".match-card");
    rightCards.forEach(card => {
      const mid = card.dataset.mid;
      const m = byId[mid];
      if (!m || !m.source_matches) return;
      const x1 = relX(ci, "right");
      const x2 = relX(ci + 1, "left");
      const xm = (x1 + x2) / 2;
      const parentY = relY(card);

      m.source_matches.forEach(sm => {
        const srcEl = cols[ci].querySelector('.match-card[data-mid="' + sm + '"]');
        if (!srcEl) return;
        const childY = relY(srcEl);
        paths += '<path d="M ' + x1 + " " + childY + " L " + xm + " " + childY + " L " + xm + " " + parentY + " L " + x2 + " " + parentY + '" fill="none" stroke="#153D4C" stroke-width="1.5"/>';
      });
    });
  }
  svg.innerHTML = paths;
}

// ── Status bar helpers ──
function updateStatusBar(left, right) {
  const leftEl = document.getElementById("statusLeft");
  const rightEl = document.getElementById("statusRight");
  if (leftEl) leftEl.innerHTML = left;
  if (rightEl) {
    if (right) rightEl.innerHTML = right;
    const btn = document.createElement("button");
    btn.className = "drawer-btn";
    btn.textContent = ">_";
    btn.onclick = toggleDrawer;
    rightEl.appendChild(btn);
  }
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
          if (p.status === "complete") { clearInterval(poll); resolve(); }
          if (p.status === "error") { clearInterval(poll); reject(new Error(p.error || "simulation failed")); }
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

// ── Terminal Simulation Runner ──
async function termRunSimulation(apiPrefix, iterations, onComplete) {
  const displayPfx = '<span class="highlight">Simulate</span> ';
  termAdd(displayPfx + 'Starting simulation with ' + iterations.toLocaleString() + ' iterations...');
  termScroll();
  try {
    const resp = await (await fetch(apiPrefix + "/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ iterations }),
    })).json();
    if (resp.error) { termAdd(displayPfx + '<span class="danger">Error: ' + resp.error + '</span>'); termShowPrompt(); return; }
    const taskId = resp.task_id;
    const t0 = Date.now();
    const progressLineId = "prog-" + taskId;
    termAdd('<span id="' + progressLineId + '">' + displayPfx + PROGRESS_SPINNER_FRAMES[0] + ' queued...</span>');
    termScroll();
    await termProgressLoop(apiPrefix, taskId, progressLineId, displayPfx, t0,
      p => (p.iteration || 0).toLocaleString() + '/' + (p.total_iterations || iterations).toLocaleString());
    const line = document.getElementById(progressLineId);
    if (line) line.innerHTML = displayPfx + '<span class="ok">' + renderProgressBar(100) + ' 100%</span> <span class="dim">(' + ((Date.now() - t0) / 1000).toFixed(1) + 's)</span>';
    termScroll();
    if (onComplete) await onComplete();
  } catch (e) {
    termAdd(displayPfx + '<span class="danger">Error: ' + (e.message || "unknown") + '</span>');
  }
  termShowPrompt();
}

async function termRunCalibration(apiPrefix) {
  const displayPfx = '<span class="highlight">Calibrate</span> ';
  termAdd(displayPfx + 'Starting calibration...');
  termScroll();
  try {
    const resp = await (await fetch(apiPrefix + "/calibrate", {
      method: "POST", headers: { "Content-Type": "application/json" },
    })).json();
    if (resp.error) { termAdd(displayPfx + '<span class="danger">Error: ' + resp.error + '</span>'); termShowPrompt(); return; }
    const taskId = resp.task_id;
    const t0 = Date.now();
    const progressLineId = "prog-" + taskId;
    termAdd('<span id="' + progressLineId + '">' + displayPfx + PROGRESS_SPINNER_FRAMES[0] + ' queued...</span>');
    termScroll();
    await termProgressLoop(apiPrefix, taskId, progressLineId, displayPfx, t0, "");
    const line = document.getElementById(progressLineId);
    if (line) line.innerHTML = displayPfx + '<span class="ok">' + renderProgressBar(100) + ' 100%</span> <span class="dim">(' + ((Date.now() - t0) / 1000).toFixed(1) + 's)</span>';
    termAdd(displayPfx + '<span class="ok">Calibration complete.</span>');
    termScroll();
  } catch (e) {
    termAdd(displayPfx + '<span class="danger">Error: ' + (e.message || "unknown") + '</span>');
  }
  termShowPrompt();
}

// ── Inline Progress Bar Utilities (C5) ──

const PROGRESS_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function renderProgressBar(pct, width = 20) {
  pct = Math.max(0, Math.min(100, pct || 0));
  const filled = Math.round((pct / 100) * width);
  const head = filled < width ? 1 : 0;
  const eq = Math.max(0, filled - head);
  const sp = Math.max(0, width - eq - head);
  return '[' + '='.repeat(eq) + '>'.repeat(head) + ' '.repeat(sp) + ']';
}

async function termRenderProgress(lineId, pct, elapsed, extra = "") {
  const el = document.getElementById(lineId);
  if (!el) return;
  const bar = renderProgressBar(pct);
  const label = bar + ' ' + pct.toFixed(0) + '%' + (extra ? '  ' + extra : '');
  el.innerHTML = label + '  <span class="dim">' + elapsed + 's</span>';
}

async function termProgressLoop(apiPrefix, taskId, progressLineId, displayPfx, t0, extras) {
  return new Promise((resolve, reject) => {
    const spinner = { i: 0 };
    const spinInt = setInterval(() => {
      const el = document.getElementById(progressLineId);
      if (el) el.innerHTML = displayPfx + PROGRESS_SPINNER_FRAMES[spinner.i % PROGRESS_SPINNER_FRAMES.length] + ' working...';
      spinner.i++;
    }, 120);
    const poll = setInterval(async () => {
      try {
        const p = await (await fetch(apiPrefix + "/simulation/progress/" + taskId)).json();
        if (p.error) { clearInterval(poll); clearInterval(spinInt); reject(new Error(p.error)); return; }
        const pct = p.progress || 0;
        const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
        const extra = typeof extras === "function" ? extras(p) : extras;
        clearInterval(spinInt);
        await termRenderProgress(progressLineId, pct, elapsed, extra);
        if (p.status === "complete") { clearInterval(poll); resolve(); }
        if (p.status === "error") { clearInterval(poll); reject(new Error(p.error || "task failed")); }
      } catch (e) { clearInterval(poll); clearInterval(spinInt); reject(e); }
    }, 300);
  });
}

// ── Sparkline Renderer (C6) ──
const SPARKLINE_CHARS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"];

function renderSparkline(val) {
  val = Math.max(0, Math.min(1, val || 0));
  const idx = Math.min(SPARKLINE_CHARS.length - 1, Math.floor(val * SPARKLINE_CHARS.length));
  return '<span class="spark">' + SPARKLINE_CHARS[idx] + '</span>';
}

// ── Terminal Spinner for One-Shot API Calls (C6) ──
async function termRunWithSpinner(displayPfx, apiCall, onSuccess) {
  const lineId = "spin-" + Date.now() + "-" + Math.random().toString(36).slice(2, 6);
  const idx = { i: 0 };
  termAdd('<span id="' + lineId + '">' + displayPfx + ' ' + PROGRESS_SPINNER_FRAMES[0] + '</span>');
  termScroll();
  const int = setInterval(() => {
    const el = document.getElementById(lineId);
    if (el) el.innerHTML = displayPfx + ' ' + PROGRESS_SPINNER_FRAMES[idx.i % PROGRESS_SPINNER_FRAMES.length];
    idx.i++;
  }, 100);
  try {
    const result = await apiCall();
    clearInterval(int);
    const el = document.getElementById(lineId);
    if (el) el.innerHTML = displayPfx + ' <span class="ok">\u2713</span>';
    if (onSuccess) await onSuccess(result);
    return result;
  } catch (e) {
    clearInterval(int);
    const el = document.getElementById(lineId);
    if (el) el.innerHTML = displayPfx + ' <span class="danger">\u2717</span> <span class="dim">' + e.message + '</span>';
  }
}

// ── Exports ──
export {
  competitions,
  currentCompetition,
  termAdd,
  termScroll,
  termShowPrompt,
  termBooting,
  termRenderBootStep,
  wireTerminal,
  buildTable,
  destroyModalCharts,
  modalCharts,
  drawBracketConnectors,
  updateStatusBar,
  focusTermInput,
  toggleDrawer,
  closeDrawer,
  termRunSimulation,
  termRunCalibration,
  renderProgressBar,
  termRenderProgress,
  termProgressLoop,
  renderSparkline,
  termRunWithSpinner,
  createSimPopup,
  showSimPopup,
};
