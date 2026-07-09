// ── Competition Registry ──
const competitions = {
  worldcup: {
    label: "World Cup 2026",
    short: "WC",
    module: "wc",
    route: "/worldcup",
    apiPrefix: "/worldcup/api",
    tabs: ["Dashboard", "Bracket", "Standings", "Terminal"],
  },
  ucl: {
    label: "UCL 2025/26",
    short: "UCL",
    module: "ucl",
    route: "/ucl",
    apiPrefix: "/ucl/api",
    tabs: ["Overview", "League Table", "Bracket", "Odds", "Signals", "Terminal"],
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
  document.getElementById("contentArea").innerHTML = `
    <div class="landing-header">
      <div class="landing-title">FOOTBALL</div>
      <div class="landing-sub">Multi-Competition Predictor</div>
    </div>
    <div class="landing-grid">
      ${Object.entries(competitions).map(([slug, c]) => `
        <div class="landing-card ${c.disabled ? "disabled" : ""}" data-route="${c.route}"${c.disabled ? ' data-disabled="1"' : ""}>
          <div class="lc-badge">${c.short}</div>
          <div class="lc-name">${c.label}</div>
          <div class="lc-desc">${c.disabled ? "Coming Soon" : "Click to explore"}</div>
        </div>
      `).join("")}
    </div>
  `;
  document.getElementById("navBar").innerHTML = `
    <div class="nav-logo" data-route="/">FOOTBALL</div>
    ${Object.entries(competitions).map(([slug, c]) => `
      <button class="nav-btn ${c.disabled ? "disabled" : ""}" data-route="${c.route}"${c.disabled ? ' data-disabled="1"' : ""}>${c.short}<span class="nav-full"> ${c.label}</span></button>
    `).join("")}
  `;
  document.getElementById("statusBar").innerHTML =
    '<span id="statusLeft">Select a competition</span><span id="statusRight"></span>';
}

// ── Load Competition Module ──
async function loadCompetition(slug) {
  const comp = competitions[slug];
  if (!comp) { renderLanding(); return; }
  currentCompetition = comp;

  // Highlight nav
  document.getElementById("navBar").innerHTML = `
    <div class="nav-logo" data-route="/" style="cursor:pointer">FOOTBALL</div>
    ${Object.entries(competitions).map(([s, c]) => `
      <button class="nav-btn ${s === slug ? "active" : ""} ${c.disabled ? "disabled" : ""}"
        data-route="${c.route}"${c.disabled ? ' data-disabled="1"' : ""}>${c.short}<span class="nav-full"> ${c.label}</span></button>
    `).join("")}
  `;

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
  if (!termOutput) return;
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

function termScroll() {
  const tt = document.getElementById("tab-terminal");
  if (tt && tt.classList.contains("active")) tt.scrollIntoView(false);
}

function focusTermInput() {
  const inp = document.getElementById("terminal-input");
  if (inp) inp.focus();
}

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
    const cursor = document.querySelector(".term-cursor");
    if (e.key === "Enter") {
      e.preventDefault();
      const cmd = termBuffer;
      termAdd('<span class="prompt"></span>' + cmd);
      termHistory.push(cmd);
      termHistoryIdx = termHistory.length;
      if (display) display.textContent = "";
      if (cursor) cursor.style.display = "none";
      if (termInputHandler) termInputHandler(cmd);
    } else if (e.key === "Backspace") {
      termBuffer = termBuffer.slice(0, -1);
      if (display) display.textContent = termBuffer;
    } else if (e.key === "ArrowUp") {
      if (!termHistory.length) return;
      termHistoryIdx = Math.max(0, termHistoryIdx - 1);
      termBuffer = termHistory[termHistoryIdx] || "";
      if (display) display.textContent = termBuffer;
    } else if (e.key === "ArrowDown") {
      termHistoryIdx = Math.min(termHistory.length, termHistoryIdx + 1);
      termBuffer = termHistoryIdx >= termHistory.length ? "" : termHistory[termHistoryIdx] || "";
      if (display) display.textContent = termBuffer;
    } else if (e.key.length === 1) {
      termBuffer += e.key;
      if (display) display.textContent = termBuffer;
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
  if (rightEl) rightEl.innerHTML = right;
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
};
