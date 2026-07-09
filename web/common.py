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
