"""Settings: config/settings.json, overridable by environment variables.

Environment variables are the way to configure the Docker container, e.g.
CORE_API_URL=http://api:3001. Tools that run the Web App with extra settings
(the test harness in "Web Dev") subclass Settings and pass settings_cls.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import ClassVar, Dict, List, Optional, Type, TypeVar

WEB_APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_FILE = WEB_APP_DIR / "config" / "settings.json"


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    core_api_url: str = "http://127.0.0.1:3001"
    core_timeout_seconds: float = 10.0
    core_use_system_proxy: bool = False
    teams: List[str] = field(default_factory=lambda: ["LEGAL", "CYBER1", "CYBER2"])
    users: Dict[str, List[str]] = field(default_factory=dict)
    hidden_users: List[str] = field(default_factory=list)  # service accounts, not shown in the sign-in picker
    decision_teams: List[str] = field(default_factory=list)
    auth_mode: str = "dev"
    log_requests: bool = True
    webapp_contract: Path = WEB_APP_DIR / "contracts" / "webapp_api.json"
    static_dir: Path = WEB_APP_DIR / "secheck_web" / "static"

    # Environment variable -> setting. Values are parsed as JSON when possible
    # (so "false", "8000" and '["A","B"]' work), otherwise used as plain strings.
    ENV_OVERRIDES: ClassVar[Dict[str, str]] = {
        "SECHECK_HOST": "host",
        "SECHECK_PORT": "port",
        "CORE_API_URL": "core_api_url",
        "CORE_TIMEOUT_SECONDS": "core_timeout_seconds",
        "SECHECK_TEAMS": "teams",
        "SECHECK_USERS": "users",
        "SECHECK_DECISION_TEAMS": "decision_teams",
        "SECHECK_AUTH_MODE": "auth_mode",
        "SECHECK_LOG_REQUESTS": "log_requests",
    }


S = TypeVar("S", bound=Settings)


def load_settings(path: Optional[Path] = None, settings_cls: Type[S] = Settings, **overrides) -> S:
    """Load settings from a JSON file, then environment variables, then keyword overrides."""
    path = Path(path or os.environ.get("SECHECK_SETTINGS") or DEFAULT_SETTINGS_FILE)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = {k: v for k, v in data.items() if not k.startswith("_")}  # "_comment" keys
    for env, key in settings_cls.ENV_OVERRIDES.items():
        if env in os.environ:
            raw = os.environ[env]
            try:
                data[key] = json.loads(raw)
            except ValueError:
                data[key] = raw
    data.update({k: v for k, v in overrides.items() if v is not None})

    known = {f.name: f for f in fields(settings_cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(f"Unknown setting(s) in {path.name}: {', '.join(sorted(unknown))}")
    base = path.parent.parent  # relative paths resolve against the folder that holds config/
    for key, value in list(data.items()):
        if isinstance(known[key].default, Path):
            data[key] = Path(value) if Path(value).is_absolute() else base / value

    settings = settings_cls(**data)
    settings.port = int(settings.port)
    settings.core_timeout_seconds = float(settings.core_timeout_seconds)
    settings.core_api_url = settings.core_api_url.rstrip("/")
    return settings
