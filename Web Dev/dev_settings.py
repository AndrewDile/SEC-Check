"""Settings for the test harness: the Web App's settings plus the mock Core API's.

Reads "Web Dev/config/settings.json". The Web App container uses
web_app/config/settings.json instead and knows nothing about the mock.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Dict, Optional

import devpath  # noqa: F401  (puts ../web_app on sys.path)
from secheck_web.config import Settings, load_settings

WEB_DEV = Path(__file__).resolve().parent
DEV_SETTINGS_FILE = WEB_DEV / "config" / "settings.json"


@dataclass
class DevSettings(Settings):
    start_mock_core: bool = True
    mock_core_port: int = 8001
    mock_core_forwarding: bool = True
    mock_core_gateway_user: str = "core-gateway"
    core_contract: Path = WEB_DEV / "contracts" / "core_api.json"

    ENV_OVERRIDES: ClassVar[Dict[str, str]] = {
        **Settings.ENV_OVERRIDES,
        "SECHECK_START_MOCK_CORE": "start_mock_core",
        "SECHECK_MOCK_CORE_PORT": "mock_core_port",
        "SECHECK_MOCK_CORE_FORWARDING": "mock_core_forwarding",
    }


def load_dev_settings(path: Optional[Path] = None, **overrides) -> DevSettings:
    settings = load_settings(path or DEV_SETTINGS_FILE, settings_cls=DevSettings, **overrides)
    settings.mock_core_port = int(settings.mock_core_port)
    return settings
