"""Contract tests for Render Blueprint (render.yaml) and Python runtime version (.python-version).

Validates compliance with locked decisions D-01, D-02, D-03, D-04, DEPLOY-01,
and STRIDE threat mitigation T-08-03.
"""

from __future__ import annotations

import pathlib
from typing import Any
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RENDER_YAML_PATH = REPO_ROOT / "render.yaml"
PYTHON_VERSION_PATH = REPO_ROOT / ".python-version"


def test_python_version_file_pinned() -> None:
    """Validate that .python-version exists and specifies exact Python runtime 3.11.8."""
    assert PYTHON_VERSION_PATH.is_file(), f"Missing .python-version at {PYTHON_VERSION_PATH}"
    content = PYTHON_VERSION_PATH.read_text(encoding="utf-8").strip()
    assert content == "3.11.8", f"Expected .python-version to be '3.11.8', got '{content}'"


def _load_render_blueprint() -> dict[str, Any]:
    """Load and parse render.yaml safely."""
    assert RENDER_YAML_PATH.is_file(), f"Missing render.yaml at {RENDER_YAML_PATH}"
    data = yaml.safe_load(RENDER_YAML_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "render.yaml must parse to a top-level mapping"
    assert "services" in data, "render.yaml must declare a 'services' list"
    assert isinstance(data["services"], list) and len(data["services"]) > 0, (
        "render.yaml 'services' must be a non-empty list"
    )
    return data


def test_render_blueprint_service_metadata() -> None:
    """Validate top-level web service configuration in render.yaml (D-01, D-03)."""
    data = _load_render_blueprint()
    svc = data["services"][0]

    assert svc.get("type") == "web", f"Expected type 'web', got {svc.get('type')!r}"
    assert svc.get("name") == "football-api", f"Expected name 'football-api', got {svc.get('name')!r}"
    assert svc.get("runtime") == "python", (
        f"Expected runtime 'python' (native Python, D-01), got {svc.get('runtime')!r}"
    )
    assert svc.get("plan") == "free", f"Expected plan 'free', got {svc.get('plan')!r}"
    assert svc.get("region") == "frankfurt", (
        f"Expected region 'frankfurt' (co-located with Neon EU Central 1, D-03), got {svc.get('region')!r}"
    )
    assert svc.get("branch") == "main", f"Expected branch 'main', got {svc.get('branch')!r}"
    assert svc.get("autoDeployTrigger") == "commit", (
        f"Expected autoDeployTrigger 'commit', got {svc.get('autoDeployTrigger')!r}"
    )


def test_render_blueprint_build_and_start_commands() -> None:
    """Validate buildCommand, startCommand, and healthCheckPath in render.yaml (D-02)."""
    data = _load_render_blueprint()
    svc = data["services"][0]

    assert svc.get("buildCommand") == "pip install -r requirements.txt", (
        f"Expected buildCommand 'pip install -r requirements.txt', got {svc.get('buildCommand')!r}"
    )
    assert svc.get("startCommand") == "uvicorn web.server:asgi_app --host 0.0.0.0 --port $PORT", (
        f"Expected startCommand 'uvicorn web.server:asgi_app --host 0.0.0.0 --port $PORT', "
        f"got {svc.get('startCommand')!r}"
    )
    assert svc.get("healthCheckPath") == "/health", (
        f"Expected healthCheckPath '/health', got {svc.get('healthCheckPath')!r}"
    )


def test_render_blueprint_environment_variables() -> None:
    """Validate environment variables, runtime version, and un-synced secrets (D-04, T-08-03)."""
    data = _load_render_blueprint()
    svc = data["services"][0]

    env_vars = svc.get("envVars", [])
    assert isinstance(env_vars, list), "envVars must be a list"

    env_map: dict[str, dict[str, Any]] = {
        item["key"]: item for item in env_vars if isinstance(item, dict) and "key" in item
    }

    # Python version environment variable
    assert "PYTHON_VERSION" in env_map, "envVars missing PYTHON_VERSION"
    assert str(env_map["PYTHON_VERSION"].get("value")) == "3.11.8", (
        f"Expected PYTHON_VERSION value '3.11.8', got {env_map['PYTHON_VERSION'].get('value')!r}"
    )

    # Secret environment variables with sync: false (T-08-03)
    required_secrets = (
        "DATABASE_URL",
        "FOOTBALL_DATA_ORG_KEY",
        "THE_ODDS_API_KEY",
        "ADMIN_KEY",
    )
    for secret_key in required_secrets:
        assert secret_key in env_map, f"Missing secret environment variable '{secret_key}' in render.yaml"
        secret_entry = env_map[secret_key]
        assert secret_entry.get("sync") is False, (
            f"Secret '{secret_key}' must have 'sync: false' in render.yaml (got {secret_entry.get('sync')!r})"
        )
        assert "value" not in secret_entry, (
            f"Secret '{secret_key}' must not commit a plaintext value in render.yaml"
        )

    # CORS Allowed origins
    assert "ALLOWED_ORIGINS" in env_map, "envVars missing ALLOWED_ORIGINS"
    assert "value" in env_map["ALLOWED_ORIGINS"], "ALLOWED_ORIGINS must specify default value"
