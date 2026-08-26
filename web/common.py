import json, time
from datetime import datetime, timezone


def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def boot_step(step_name: str, action, boot_log: list):
    t0 = time.time()
    try:
        result = action()
        elapsed = time.time() - t0
        boot_log.append({
            "step": step_name, "status": "ok",
            "elapsed": round(elapsed, 2),
            "output": f"[{ts()}] {step_name} — done in {elapsed:.1f}s",
        })
        return result
    except Exception as e:
        elapsed = time.time() - t0
        boot_log.append({
            "step": step_name, "status": "error",
            "elapsed": round(elapsed, 2),
            "output": f"[{ts()}] {step_name} — FAILED ({e})",
        })
        return None


def load_json(data_dir, name: str) -> dict:
    with open(data_dir / name, encoding="utf-8") as f:
        return dict(json.load(f))


def _usable_key(value: str | None) -> str | None:
    """Return the key when it is a real credential, else None.

    A placeholder ("your_api_key_here" style) or empty value selects
    nothing - a template key must never reach the network as if live.
    """
    text = (value or "").strip()
    if not text or text.lower().startswith("your_"):
        return None
    return text


def get_data_provider(bsd_api_key: str, football_data_org_key: str, bsd_league_id: int):
    """Single provider-selection factory for both competitions.

    Precedence:
      1. DATA_PROVIDER=bsd + BSD key            -> BSDDataProvider
      2. DATA_PROVIDER=football-data + FDO key  -> FootballDataOrgProvider
      3. no env var -> auto-detect (BSD first, then FDO)
      4. no usable key at all -> None (caller skips live fetch)

    Empty or "your_..." placeholder keys never select a provider.
    """
    import os

    from football_core.data_providers.bsd_provider import BSDDataProvider
    from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider

    bsd_key = _usable_key(bsd_api_key)
    fdo_key = _usable_key(football_data_org_key)
    mode = os.getenv("DATA_PROVIDER", "").lower()

    if mode == "bsd" and bsd_key:
        return BSDDataProvider(bsd_key, league_id=bsd_league_id)
    if mode == "football-data" and fdo_key:
        return FootballDataOrgProvider(fdo_key)

    if bsd_key:
        return BSDDataProvider(bsd_key, league_id=bsd_league_id)
    if fdo_key:
        return FootballDataOrgProvider(fdo_key)
    return None
