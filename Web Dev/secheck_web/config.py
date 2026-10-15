"""Settings: config/settings.json, overridable by environment variables."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

WEB_DEV_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_FILE = WEB_DEV_DIR / "config" / "settings.json"

# Environment variable -> settings key. Values are parsed as JSON when possible
# (so "false", "8000" and '["A","B"]' work), otherwise used as plain strings.
ENV_OVERRIDES = {
    "SECHECK_HOST": "host",
    "SECHECK_PORT": "port",
    "CORE_API_URL": "core_api_url",
    "CORE_TIMEOUT_SECONDS": "core_timeout_seconds",
    "SECHECK_START_MOCK_CORE": "start_mock_core",
    "SECHECK_MOCK_CORE_PORT": "mock_core_port",
    "SECHECK_MOCK_CORE_FORWARDING": "mock_core_forwarding",
    "SECHECK_TEAMS": "teams",
    "SECHECK_AUTH_MODE": "auth_mode",
}


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    core_api_url: str = "http://127.0.0.1:8001"
    core_timeout_seconds: float = 10.0
    core_use_system_proxy: bool = False
    start_mock_core: bool = True
    mock_core_port: int = 8001
    mock_core_forwarding: bool = True
    mock_core_gateway_user: str = "core-gateway"
    teams: List[str] = field(default_factory=lambda: ["LEGAL", "CYBER1", "CYBER2"])
    users: Dict[str, List[str]] = field(default_factory=dict)
    decision_teams: List[str] = field(default_factory=list)
    auth_mode: str = "dev"
    log_requests: bool = True
    webapp_contract: Path = WEB_DEV_DIR / "contracts" / "webapp_api.json"
    core_contract: Path = WEB_DEV_DIR / "contracts" / "core_api.json"
    static_dir: Path = WEB_DEV_DIR / "secheck_web" / "static"


def load_settings(path: Optional[Path] = None, **overrides) -> Settings:
    path = Path(path or os.environ.get("SECHECK_SETTINGS") or DEFAULT_SETTINGS_FILE)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = {k: v for k, v in data.items() if not k.startswith("_")}  # "_comment" keys
    for env, key in ENV_OVERRIDES.items():
        if env in os.environ:
            raw = os.environ[env]
            try:
                data[key] = json.loads(raw)
            except ValueError:
                data[key] = raw
    data.update({k: v for k, v in overrides.items() if v is not None})
    for key in ("webapp_contract", "core_contract", "static_dir"):
        if key in data:
            p = Path(data[key])
            data[key] = p if p.is_absolute() else WEB_DEV_DIR / p
    known = Settings.__dataclass_fields__.keys()
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(f"Unknown setting(s) in {path.name}: {', '.join(sorted(unknown))}")
    settings = Settings(**data)
    settings.port = int(settings.port)
    settings.mock_core_port = int(settings.mock_core_port)
    settings.core_timeout_seconds = float(settings.core_timeout_seconds)
    settings.core_api_url = settings.core_api_url.rstrip("/")
    return settings
