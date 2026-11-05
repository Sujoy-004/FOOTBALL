// web/static/wake_up.js
// Client-side Render free-tier cold-start detection and non-blocking status banner UX.
// Provides non-blocking feedback during spin-up (~30-50s) and exponential backoff /health polling.

let isProbing = false;

export function showWakeUpBanner(message = "Waking prediction engine (~30s)...") {
  if (typeof document === "undefined") return null;

  let banner = document.getElementById("render-wake-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "render-wake-banner";
    banner.className = "wake-banner active";
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");

    const content = document.createElement("div");
    content.className = "wake-content";

    const spinner = document.createElement("div");
    spinner.className = "wake-spinner";
    spinner.setAttribute("aria-hidden", "true");

    const text = document.createElement("span");
    text.id = "wake-banner-text";
    text.className = "wake-text";
    text.textContent = message;

    content.appendChild(spinner);
    content.appendChild(text);
    banner.appendChild(content);

    if (document.body) {
      document.body.prepend(banner);
    }
  } else {
    const text = document.getElementById("wake-banner-text");
    if (text) {
      text.textContent = message;
    }
    banner.classList.add("active");
    const spinner = banner.querySelector(".wake-spinner");
    if (spinner) {
      spinner.style.display = "";
    }
  }

  return banner;
}

export function hideWakeUpBanner() {
  if (typeof document === "undefined") return;
  const banner = document.getElementById("render-wake-banner");
  if (banner) {
    banner.classList.remove("active");
  }
}

export function probeBackendHealth(apiBaseUrl = "", onReady = null) {
  if (isProbing) {
    return;
  }
  isProbing = true;

  showWakeUpBanner("Waking prediction engine (~30s)...");

  const start = Date.now();
  const deadline = start + 65000;
  let delay = 3000;
  const maxDelay = 10000;

  const base = String(apiBaseUrl || "").replace(/\/+$/, "");
  const healthUrl = base ? `${base}/health` : "/health";

  async function check() {
    try {
      const res = await fetch(healthUrl, { method: "GET", cache: "no-store" });
      if (res && res.status === 200) {
        isProbing = false;
        showWakeUpBanner("✓ Prediction engine online. Syncing data...");
        const banner = typeof document !== "undefined" ? document.getElementById("render-wake-banner") : null;
        if (banner) {
          const spinner = banner.querySelector(".wake-spinner");
          if (spinner) spinner.style.display = "none";
        }
        setTimeout(() => {
          hideWakeUpBanner();
          if (typeof onReady === "function") {
            try {
              onReady();
            } catch (err) {
              console.warn("onReady callback error:", err);
            }
          }
        }, 1500);
        return;
      }
    } catch (_) {
      // Network error or 502/503 during cold-start
    }

    if (Date.now() >= deadline) {
      isProbing = false;
      showWakeUpBanner("Engine wake timeout. Refresh page to retry.");
      const banner = typeof document !== "undefined" ? document.getElementById("render-wake-banner") : null;
      if (banner) {
        const spinner = banner.querySelector(".wake-spinner");
        if (spinner) spinner.style.display = "none";
      }
      return;
    }

    const nextDelay = delay;
    delay = Math.min(delay * 1.5, maxDelay);
    setTimeout(check, nextDelay);
  }

  // Kick off initial health poll
  setTimeout(check, delay);
}

if (typeof window !== "undefined") {
  window.showWakeUpBanner = showWakeUpBanner;
  window.hideWakeUpBanner = hideWakeUpBanner;
  window.probeBackendHealth = probeBackendHealth;
} else if (typeof globalThis !== "undefined") {
  globalThis.showWakeUpBanner = showWakeUpBanner;
  globalThis.hideWakeUpBanner = hideWakeUpBanner;
  globalThis.probeBackendHealth = probeBackendHealth;
}
