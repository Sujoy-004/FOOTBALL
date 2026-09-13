// ── Competition live-refresh manager (Exchange 9C) ───────────────────
// Framework-free ESM: ONE manager instance per page, shared by every
// competition module through shared.js. Browser scheduling primitives are
// injectable ({setInterval, clearInterval, setTimeout, isVisible}) so the
// whole timing/visibility policy is unit-testable with a fake clock (see
// refresh.test.mjs) while the page uses its real primitives.
//
// Policy contract (mirrored in web/ARCHITECTURE.md):
//   * A competition's live data is polled ONLY while it is (a) the active
//     competition, (b) enabled, and (c) the document is visible. Polling a
//     hidden tab is wasted work; returning to the tab triggers a refresh.
//   * One timer + one in-flight refresh per competition. A refresh
//     requested while another is in flight coalesces into exactly one
//     follow-up run — overlapping fetches never happen.
//   * The reload hook (owned by each module) decides WHAT to refetch and
//     HOW to commit; the manager never touches DOM or appState. Modules
//     keep their own generation-token guard so a live refresh can never
//     commit over a newer full load (activateRefresh/requestRefresh only
//     schedule; correctness of commit is the module's job).

export function createRefreshManager(deps = {}) {
  const setters = deps.setInterval || ((fn, ms) => setInterval(fn, ms));
  const unsetters = deps.clearInterval || ((id) => clearInterval(id));
  const later = deps.setTimeout || ((fn, ms) => setTimeout(fn, ms));
  const isVisible = deps.isVisible || (() => (typeof document !== "undefined")
      ? document.visibilityState === "visible" : true);

  const entries = new Map(); // slug -> {enabled, intervalMs, refreshOnActivation, reload, timerId, inFlight, pending}
  let activeSlug = null;

  function _st(slug) {
    return entries.get(slug);
  }

  function _allowed(slug) {
    const st = _st(slug);
    if (!st || slug !== activeSlug) return false;
    if (!st.enabled || !isVisible()) return false;
    return true;
  }

  async function _run(slug) {
    const st = _st(slug);
    if (!st) return;
    if (st.inFlight) { st.pending = true; return; }
    if (!_allowed(slug)) return;
    st.inFlight = true;
    try {
      await Promise.resolve().then(() => st.reload());
    } catch (e) {
      // The reload hook is competition-owned and may throw; a live refresh
      // is best-effort and must never wedge the timer loop.
      console.error("[" + slug + "] live refresh failed:", e);
    } finally {
      st.inFlight = false;
      if (st.pending) {
        st.pending = false;
        later(() => _run(slug), 0);
      }
    }
  }

  function registerRefresh(slug, opts = {}) {
    const prev = _st(slug);
    if (prev && prev.timerId != null) unsetters(prev.timerId);
    const st = {
      reload: opts.reload || (() => null),
      enabled: !!opts.enabled,
      intervalMs: opts.intervalMs || 60000,
      refreshOnActivation: opts.refreshOnActivation !== false,
      timerId: null,
      inFlight: false,
      pending: false,
    };
    entries.set(slug, st);
    // Re-arm when the ACTIVE competition re-registers (hot module reload)
    // so a stale timer is never kept alive for a re-registered slug.
    if (slug === activeSlug && st.enabled) {
      st.timerId = setters(() => _run(slug), st.intervalMs);
    }
    return st;
  }

  // Switching competitions stops every prior timer: only the active
  // competition ever polls, so at most one interval exists at a time.
  function activateRefresh(slug, o = {}) {
    for (const [, st] of entries) {
      if (st.timerId != null) { unsetters(st.timerId); st.timerId = null; }
    }
    activeSlug = slug;
    const st = _st(slug);
    if (st && st.enabled) {
      st.timerId = setters(() => _run(slug), st.intervalMs);
      if (o && o.immediate) later(() => requestRefresh(slug), 0);
    }
  }

  function deactivateRefresh() {
    for (const [, st] of entries) {
      if (st.timerId != null) { unsetters(st.timerId); st.timerId = null; }
    }
    activeSlug = null;
  }

  // Full stop: used on leaving to the landing page. In-flight reloads are
  // not cancellable and commit only if the module's own guard passes; the
  // pending flag is cleared so no backlog survives a later activation.
  function stopAllRefresh() {
    deactivateRefresh();
    for (const st of entries.values()) st.pending = false;
  }

  // Activation catch-up: immediate (microtask-deferred) refresh for a
  // visible, enabled, active competition — gated by refreshOnActivation.
  // Scheduled through later(..., 0) so the caller never blocks and the run
  // order stays relative to any pending timer callbacks.
  function requestRefresh(slug) {
    const st = _st(slug);
    if (!st || !st.enabled || !st.refreshOnActivation) return;
    later(() => _run(slug), 0);
  }

  // Visibility catch-up: the page became visible again — refresh the active
  // competition (same activation semantics).
  function notifyVisible() {
    if (!isVisible()) return;
    if (activeSlug) requestRefresh(activeSlug);
  }

  return {
    registerRefresh,
    activateRefresh,
    deactivateRefresh,
    stopAllRefresh,
    requestRefresh,
    notifyVisible,
  };
}