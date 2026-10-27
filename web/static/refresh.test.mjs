// Exchange 9C — createRefreshManager unit tests (node:test, fake clock).
// Zero network, zero DOM: browser scheduling/visibility primitives are
// injected, so every policy guard (active/enabled/visible, one timer,
// in-flight coalescing, stop-all, activation catch-up) is asserted
// deterministically against a controllable clock.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRefreshManager } from "./refresh.js";

// ── Fake clock ───────────────────────────────────────────────────────
// Minimal deterministic scheduler for setInterval/setTimeout. Step-time to
// run due timers in timestamp order; intervals re-arm themselves at their
// next due time, one-shot timeouts are removed after firing.
class FakeClock {
  constructor() {
    this.now = 0;
    this.nextId = 1;
    this.timers = new Map();
    this.fired = [];
  }

  _alloc(entry) {
    const id = this.nextId++;
    this.timers.set(id, { id, ...entry });
    return id;
  }

  setInterval(fn, ms) {
    return this._alloc({ fn, ms, at: this.now + ms, kind: "interval" });
  }

  clearInterval(id) { this.timers.delete(id); }

  setTimeout(fn, ms) {
    return this._alloc({ fn, ms, at: this.now + ms, kind: "timeout" });
  }

  clearTimeout(id) { this.timers.delete(id); }

  step(ms) {
    const target = this.now + ms;
    for (;;) {
      let due = null;
      for (const t of this.timers.values()) {
        if (t.at <= target && (due === null || t.at < due.at)) due = t;
      }
      if (!due) break;
      if (due.at > this.now) this.now = due.at;
      if (due.kind === "interval") due.at = due.at + due.ms;
      else this.timers.delete(due.id);
      this.fired.push(due.kind);
      due.fn();
    }
    this.now = target;
  }
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function makeHarness({ refreshOnActivation = true, enabled = true } = {}) {
  const clock = new FakeClock();
  let visible = true;
  let reloadCalls = 0;
  let resolveReload = null;
  const reloadReturned = [];
  const reload = () => {
    reloadCalls++;
    const p = new Promise((r, j) => {
      resolveReload = { r, j };
    });
    return p;
  };
  const mgr = createRefreshManager({
    setInterval: (fn, ms) => clock.setInterval(fn, ms),
    clearInterval: (id) => clock.clearInterval(id),
    setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
    clearTimeout: (id) => clock.clearTimeout(id),
    isVisible: () => visible,
  });
  mgr.registerRefresh("wc", {
    reload,
    enabled,
    intervalMs: 100,
    refreshOnActivation,
  });
  return {
    clock, mgr, reload,
    setVisible: (v) => { visible = v; },
    get reloadCalls() { return reloadCalls; },
    resolveReload: () => { const r = resolveReload; resolveReload = null; return r; },
  };
}

// ── 1. Timer gating: active + enabled + visible ───────────────────────

test("interval refresh fires for the active, visible competition", async () => {
  const h = makeHarness();
  h.mgr.activateRefresh("wc");
  h.clock.step(100);
  await flush();
  assert.equal(h.reloadCalls, 1, "interval fired a reload");
  h.resolveReload().r();
  await flush();
});

test("no refresh while a competition is not activated", async () => {
  const h = makeHarness();
  h.clock.step(1000);
  await flush();
  assert.equal(h.reloadCalls, 0, "no timer armed before activation");
});

test("hidden document suppresses the interval refresh", async () => {
  const h = makeHarness();
  h.mgr.activateRefresh("wc");
  h.setVisible(false);
  h.clock.step(300);
  await flush();
  assert.equal(h.reloadCalls, 0, "hidden tab does not poll");
});

test("returning to the visible tab requests an immediate catch-up refresh", async () => {
  const h = makeHarness();
  h.mgr.activateRefresh("wc");
  h.setVisible(false);
  h.clock.step(300);
  await flush();
  assert.equal(h.reloadCalls, 0);
  h.setVisible(true);
  h.mgr.notifyVisible();
  h.clock.step(0);     // runs the deferred 0-ms catch-up call
  await flush();
  assert.equal(h.reloadCalls, 1, "visibility return triggered refresh");
  h.resolveReload().r();
  await flush();
});

test("disabled competition never refreshes, even when active", async () => {
  const h = makeHarness({ enabled: false });
  h.mgr.activateRefresh("wc");
  h.clock.step(300);
  await flush();
  assert.equal(h.reloadCalls, 0, "disabled competition does not poll");
  h.mgr.requestRefresh("wc");
  await flush();
  assert.equal(h.reloadCalls, 0, "disabled competition ignores activation catch-up");
});

// ── 2. One timer / switch stops the old one ───────────────────────────

test("activating a different competition stops the previous timer", async () => {
  const h = makeHarness();
  const calls2 = [];
  h.mgr.registerRefresh("ucl", {
    reload: () => { calls2.push(1); return Promise.resolve(); },
    enabled: true,
    intervalMs: 50,
    refreshOnActivation: true,
  });
  h.mgr.activateRefresh("wc");
  h.clock.step(100);
  await flush();
  assert.equal(h.reloadCalls, 1, "wc polls while active");
  h.resolveReload().r();
  await flush();

  h.mgr.activateRefresh("ucl");
  // Flush between ticks so each interval fires a distinct (non-coalesced)
  // reload — proving the ucl timer, not the old wc one, is now running.
  for (let i = 0; i < 4; i++) {
    h.clock.step(50);
    await flush();
  }
  assert.equal(h.reloadCalls, 1, "wc timer stopped after switch");
  assert.equal(calls2.length, 4, "ucl timer fires for the active competition only");
});

// ── 3. In-flight coalescing ───────────────────────────────────────────

test("a refresh requested mid-flight coalesces to one follow-up run", async () => {
  const h = makeHarness();
  h.mgr.activateRefresh("wc");
  h.clock.step(100);          // interval fires -> in-flight reload starts
  await flush();
  assert.equal(h.reloadCalls, 1);

  h.mgr.requestRefresh("wc"); // activation catch-up while in flight
  h.clock.step(200);          // second interval also hits while in flight
  await flush();
  assert.equal(h.reloadCalls, 1, "no overlap while in flight");

  h.resolveReload().r();
  await flush();       // in-flight completes (finally schedules follow-up)
  h.clock.step(0);     // coalesced follow-up (deferred 0-ms call) fires
  await flush();       // follow-up reload runs
  assert.equal(h.reloadCalls, 2, "exactly one follow-up after completion");
  h.resolveReload().r();
  await flush();
});

// ── 4. stopAllRefresh ─────────────────────────────────────────────────

test("stopAllRefresh clears timers and pending follow-ups", async () => {
  const h = makeHarness();
  h.mgr.activateRefresh("wc");
  h.clock.step(100);
  await flush();
  assert.equal(h.reloadCalls, 1);
  h.mgr.requestRefresh("wc");   // pending while in flight
  h.mgr.stopAllRefresh();
  h.resolveReload().r();
  await flush();
  await flush();
  assert.equal(h.reloadCalls, 1, "pending follow-up cleared by stopAll");

  h.clock.step(1000);
  await flush();
  assert.equal(h.reloadCalls, 1, "no timer after stopAll");
});

// ── 5. Activation catch-up semantics ──────────────────────────────────

test("requestRefresh respects refreshOnActivation=false", async () => {
  const h = makeHarness({ refreshOnActivation: false });
  h.mgr.activateRefresh("wc");
  h.mgr.requestRefresh("wc");
  await flush();
  await flush();
  assert.equal(h.reloadCalls, 0, "activation catch-up disabled by config");
  h.clock.step(100);            // interval still polls
  await flush();
  assert.equal(h.reloadCalls, 1, "interval polling unaffected");
  h.resolveReload().r();
  await flush();
});

test("requestRefresh on a non-active competition does nothing", async () => {
  const h = makeHarness();
  h.mgr.requestRefresh("wc");   // never activated
  await flush();
  await flush();
  assert.equal(h.reloadCalls, 0);
});

test("activateRefresh with immediate=true schedules one catch-up", async () => {
  const h = makeHarness();
  h.mgr.activateRefresh("wc", { immediate: true });
  h.clock.step(0);     // runs the immediate->request refresh chain
  await flush();
  assert.equal(h.reloadCalls, 1, "immediate activation refreshed");
  h.resolveReload().r();
  await flush();
});

// ── 6. Robustness ─────────────────────────────────────────────────────

test("a throwing reload hook neither wedges nor crashes the loop", async () => {
  const clock = new FakeClock();
  const mgr = createRefreshManager({
    setInterval: (fn, ms) => clock.setInterval(fn, ms),
    clearInterval: (id) => clock.clearInterval(id),
    setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
    isVisible: () => true,
  });
  let calls = 0;
  mgr.registerRefresh("wc", {
    reload: () => { calls++; throw new Error("boom"); },
    enabled: true,
    intervalMs: 100,
    refreshOnActivation: true,
  });
  mgr.activateRefresh("wc");
  // Flush between ticks so each interval fires a fresh (non-coalesced) run,
  // proving a throwing reload never wedges the timer loop.
  for (let i = 0; i < 3; i++) {
    clock.step(100);
    await flush();
  }
  assert.equal(calls, 3, "interval keeps firing after a failed reload");
});

// ── 7. Phase 02-08 shared render helpers (C1/C2/C3/C4) ──────────────
// shared.js registers top-level DOM listeners at import time, so the
// document/window stubs must land BEFORE the dynamic import.
globalThis.document = {
  addEventListener() {}, querySelector() { return null; },
  querySelectorAll() { return []; }, getElementById() { return null; },
  createElement() {
    return { style: {}, classList: { add() {}, remove() {} }, setAttribute() {}, appendChild() {} };
  },
  body: { contains() { return false; }, className: "" },
};
globalThis.window = {
  addEventListener() {}, location: { hash: "" },
  matchMedia() { return { matches: false }; },
};
const shared = await import("./shared.js");

test("re-registering the active competition re-arms its timer", async () => {

test("refresh button copy: idle vs in-flight (I2, D-01)", () => {
  const idle = shared.refreshButtonHtml("worldcup", false);
  assert.ok(idle.includes("Refresh results"), "idle label");
  assert.ok(!idle.includes("disabled"), "idle not disabled");
  const inFlight = shared.refreshButtonHtml("worldcup", true);
  assert.ok(inFlight.includes("Refreshing…"), "in-flight label");
  assert.ok(inFlight.includes("disabled"), "in-flight disabled");
  assert.ok(inFlight.includes('aria-busy="true"'), "in-flight aria-busy");
});

test("missing panel carries D-04 copy verbatim", () => {
  const html = shared.renderAvailPanel({ state: "missing", comp: "World Cup" });
  assert.ok(html.includes("No data yet — tap Refresh to fetch results"), "D-04 locked copy");
  assert.ok(html.includes("No data yet"), "heading");
});

test("empty and unavailable panels substitute provider/timestamp/reason", () => {
  const empty = shared.renderAvailPanel({ state: "empty", comp: "LaLiga", provider: "fdo", lastRefresh: "2026-10-08T10:00:00Z" });
  assert.ok(empty.includes("The LaLiga store is present but contains no finished matches."), "EMPTY body");
  assert.ok(empty.includes("Provider: fdo"), "provider substituted");
  assert.ok(empty.includes("Last refresh: 2026-10-08T10:00:00Z"), "timestamp substituted");
  const unav = shared.renderAvailPanel({ state: "unavailable", reason: "corrupt JSON", provider: "fdo", lastRefresh: "2026-10-08T10:00:00Z" });
  assert.ok(unav.includes("Store unavailable: corrupt JSON."), "UNAVAILABLE body");
  assert.ok(unav.includes("Try Refresh results."), "UNAVAILABLE tail");
});

test("panel and banner escape server-side strings (T-08-X)", () => {
  const xss = '<img src=x onerror=alert(1)>';
  const panel = shared.renderAvailPanel({ state: "unavailable", reason: xss, provider: xss, lastRefresh: xss });
  assert.ok(!panel.includes("<img src=x"), "no raw img tag in panel");
  assert.ok(panel.includes("&lt;img src=x"), "escaped in panel");
  const banner = shared.renderAvailabilityBanner("refreshing", { comp: xss });
  assert.ok(!banner.includes("<img src=x"), "no raw img tag in banner");
  assert.ok(banner.includes("&lt;img src=x"), "escaped in banner");
});

test("banner and panel carry role=status and aria-live=polite", () => {
  const banner = shared.renderAvailabilityBanner("failed", {});
  assert.ok(banner.includes('role="status"'), "banner role");
  assert.ok(banner.includes('aria-live="polite"'), "banner aria-live");
  const panel = shared.renderAvailPanel({ state: "missing", comp: "UCL" });
  assert.ok(panel.includes('role="status"'), "panel role");
  assert.ok(panel.includes('aria-live="polite"'), "panel aria-live");
});

test("caption renders only when the report carries counters", () => {
  const el = { innerHTML: "" };
  shared.renderAcquisitionPanel(el, {
    competition: "X", source: "live", mode: "live", stages: [],
    finished: { ingested: 3, skipped_unmatchable: 1, skipped_no_target: 0, skipped_missing_score: 0, not_finished: 2 },
  });
  assert.ok(el.innerHTML.includes("Ingested 3 · Skipped 1 · Not finished 2"), "caption with counters");
  const el2 = { innerHTML: "" };
  shared.renderAcquisitionPanel(el2, { competition: "X", source: "live", mode: "live", stages: [] });
  assert.ok(!el2.innerHTML.includes(".acq-caption"), "no caption without counters");
});

test("legacy SNAPSHOT/STALE/DEFERRED wording is byte-identical", () => {
  assert.equal(shared.renderAvailabilityBanner("snapshot", {}).includes("SNAPSHOT - showing stored data (live refresh skipped)"), true);
  assert.equal(shared.renderAvailabilityBanner("stale", {}).includes("STALE - live refresh failed; showing last known data"), true);
  assert.equal(shared.renderAvailabilityBanner("deferred", {}).includes("Provider has no published match data yet - showing draw-derived fixtures"), true);
});

test("I6 predicate: panel replaces table only for unhealthy states", () => {
  assert.equal(shared.renderAvailPanel({ state: "available" }), "");
  assert.equal(shared.renderAvailPanel({ state: "unknown" }), "");
  assert.ok(shared.renderAvailPanel({ state: "empty", comp: "UCL" }) !== "");
  assert.ok(shared.renderAvailPanel({ state: "missing", comp: "UCL" }) !== "");
  assert.ok(shared.renderAvailPanel({ state: "unavailable", comp: "UCL" }) !== "");
});
  const h = makeHarness();
  h.mgr.activateRefresh("wc");
  h.clock.step(50);
  await flush();
  assert.equal(h.reloadCalls, 0, "first interval not yet due");
  h.mgr.registerRefresh("wc", { reload: h.reload, enabled: true, intervalMs: 100, refreshOnActivation: true });
  h.clock.step(100);
  await flush();
  assert.equal(h.reloadCalls, 1, "re-registered timer is armed for the active slug");
  h.resolveReload().r();
  await flush();
});

// ── Phase 05 — the retirement marker builders (DOM-free) ──
// shared.js was already imported (and its document/window globals already
// stubbed) at the top of this file, so the builders are in scope here.

test("retiredCountLine omits an unknown count", () => {
  assert.equal(shared.retiredCountLine(undefined), "");
  assert.equal(shared.retiredCountLine(null), "");
  assert.equal(shared.retiredCountLine({}), "");
  assert.equal(shared.retiredCountLine({ retired_count: null }), "");
  assert.equal(shared.retiredCountLine({ retired_count: "3" }), "");
  assert.equal(shared.retiredCountLine({ retired_count: 0 }), "");
  assert.equal(shared.retiredCountLine({ retired_count: -2 }), "");
  // A reconciliation that was never established may never show a count.
  assert.equal(shared.retiredCountLine({ retired_count: 3, not_established: true }), "");
});

test("retiredCountLine renders a positive count", () => {
  assert.equal(shared.retiredCountLine({ retired_count: 3 }), "  |  3 retired");
  assert.equal(shared.retiredCountLine({ retired_count: 1 }), "  |  1 retired");
});

test("retiredBadgeHtml escapes its label", () => {
  assert.equal(shared.retiredBadgeHtml(), '<span class="badge-retired">Retired</span>');
  assert.equal(
    shared.retiredBadgeHtml('<script>'),
    '<span class="badge-retired">&lt;script&gt;</span>'
  );
});
