// web/static/config.js
// Default runtime configuration for FOOTBALL SPA.
// In local development, API_URL is "" (same-origin relative paths).
// When deploying to Cloudflare Pages, set API_URL to your Render backend:
// window.__APP_CONFIG__ = { API_URL: "https://football-api.onrender.com" };

window.__APP_CONFIG__ = window.__APP_CONFIG__ || {
  API_URL: "https://football-api-c83v.onrender.com",
  ENVIRONMENT: "production",
  VERSION: "2.0.0",
};
