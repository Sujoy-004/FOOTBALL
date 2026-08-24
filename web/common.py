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


def load_json_list(data_dir, name: str) -> list:
    with open(data_dir / name, encoding="utf-8") as f:
        return list(json.load(f))


def get_data_provider(bsd_api_key: str, football_data_org_key: str, bsd_league_id: int):
    """Single provider-selection factory for both competitions.

    Precedence:
      1. DATA_PROVIDER=bsd + BSD key            -> BSDDataProvider
      2. DATA_PROVIDER=football-data + FDO key  -> FootballDataOrgProvider
      3. no env var -> auto-detect (BSD first, then FDO)
      4. no key at all -> None (caller skips live fetch)
    """
    import os

    from football_core.data_providers.bsd_provider import BSDDataProvider
    from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider

    mode = os.getenv("DATA_PROVIDER", "").lower()

    if mode == "bsd" and bsd_api_key:
        return BSDDataProvider(bsd_api_key, league_id=bsd_league_id)
    if mode == "football-data" and football_data_org_key:
        return FootballDataOrgProvider(football_data_org_key)

    if bsd_api_key:
        return BSDDataProvider(bsd_api_key, league_id=bsd_league_id)
    if football_data_org_key:
        return FootballDataOrgProvider(football_data_org_key)
    return None
