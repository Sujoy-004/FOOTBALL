// web/static/api.js
// Unified client API adapter and dynamic URL resolution for decoupled edge deployment.
// In local development, getApiBaseUrl() returns "" preserving relative same-origin paths.
// In production on Cloudflare Pages, resolves window.__APP_CONFIG__.API_URL.

export function getApiBaseUrl() {
  if (typeof window !== "undefined" && window.__APP_CONFIG__ && window.__APP_CONFIG__.API_URL) {
    return String(window.__APP_CONFIG__.API_URL).replace(/\/+$/, "");
  }
  const meta = typeof document !== "undefined" ? document.querySelector('meta[name="api-url"]') : null;
  if (meta && meta.content) {
    return String(meta.content).replace(/\/+$/, "");
  }
  return "";
}

export function resolveApiUrl(path) {
  if (!path) return path;
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  const base = getApiBaseUrl();
  if (!base) return path;
  const cleanPath = path.replace(/^\/+/, "");
  return `${base}/${cleanPath}`;
}

export async function safeJson(url, options = {}) {
  const targetUrl = resolveApiUrl(url);
  const r = await fetch(targetUrl, options);
  const t = await r.text();
  if (!r.ok) {
    throw new Error("[" + r.status + "] " + targetUrl + ": "
      + (t.slice(0, 120) || "empty body"));
  }
  try {
    return JSON.parse(t);
  } catch (e) {
    throw new Error("[" + r.status + "] " + targetUrl
      + ": non-JSON response (" + (t.slice(0, 80) || "empty body") + ")");
  }
}

if (typeof window !== "undefined") {
  window.getApiBaseUrl = getApiBaseUrl;
  window.resolveApiUrl = resolveApiUrl;
  window.safeJson = safeJson;
} else if (typeof globalThis !== "undefined") {
  globalThis.getApiBaseUrl = getApiBaseUrl;
  globalThis.resolveApiUrl = resolveApiUrl;
  globalThis.safeJson = safeJson;
}
