"""Tester settings. Every value can be overridden with an environment variable.

Most of these exist because the pod hasn't settled a detail of the Core API
yet (see "Where the spec is ambiguous" in README.md). Changing a setting is
meant to be enough to follow a pod decision, without touching the tests.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

DEFAULT_TEAMS = ["LEGAL", "CYBER1", "CYBER2"]


@dataclass
class Settings:
    host: str = "0.0.0.0"
    port: int = 8100
    base_path: str = ""                 # route prefix, e.g. "/tester"
    request_timeout: float = 10.0       # one Core API call (seconds)
    setup_timeout: float = 60.0         # the target's /test/setup
    run_budget: float = 240.0           # the whole suite; after this the run aborts
    report_retries: int = 3             # retries while the target's /test/report answers 409
    report_retry_delay: float = 1.0
    max_comm_errors: int = 3            # consecutive no-response tests before the rest are skipped
    session_header: str = "X-Session-ID"   # "" sends no header
    session_in_body: bool = False       # also add "session_id" to every Core API body
    id_style: str = "digits"            # Incident_ID style: "digits" (12-digit string) or "uuid"
    dependencies_path: str = "/dependencies"
    teams: List[str] = field(default_factory=lambda: list(DEFAULT_TEAMS))
    extra_setup: Dict[str, Any] = field(default_factory=dict)   # merged into the "setup" object

    ENV = {
        "TESTER_HOST": ("host", str),
        "TESTER_PORT": ("port", int),
        "TESTER_BASE_PATH": ("base_path", str),
        "TESTER_REQUEST_TIMEOUT_S": ("request_timeout", float),
        "TESTER_SETUP_TIMEOUT_S": ("setup_timeout", float),
        "TESTER_RUN_BUDGET_S": ("run_budget", float),
        "TESTER_REPORT_RETRIES": ("report_retries", int),
        "TESTER_MAX_COMM_ERRORS": ("max_comm_errors", int),
        "TESTER_SESSION_HEADER": ("session_header", str),
        "TESTER_SESSION_IN_BODY": ("session_in_body", "bool"),
        "TESTER_ID_STYLE": ("id_style", str),
        "TESTER_DEPENDENCIES_PATH": ("dependencies_path", str),
        "TESTER_TEAMS": ("teams", "list"),
        "TESTER_EXTRA_SETUP_JSON": ("extra_setup", "json"),
    }

    @classmethod
    def from_env(cls, environ=None) -> "Settings":
        environ = os.environ if environ is None else environ
        settings = cls()
        for var, (name, kind) in cls.ENV.items():
            raw = environ.get(var)
            if raw is None or raw == "" and kind not in (str,):
                continue
            try:
                setattr(settings, name, _convert(raw, kind))
            except (ValueError, TypeError) as exc:
                raise SystemExit("Bad value for %s: %r (%s)" % (var, raw, exc))
        settings.normalize()
        return settings

    def normalize(self) -> None:
        self.base_path = "/" + self.base_path.strip("/") if self.base_path.strip("/") else ""
        if self.id_style not in ("digits", "uuid"):
            raise SystemExit("TESTER_ID_STYLE must be 'digits' or 'uuid'")
        if not self.dependencies_path.startswith("/"):
            self.dependencies_path = "/" + self.dependencies_path


def _convert(raw: str, kind: Any) -> Any:
    if kind == "bool":
        if raw.strip().lower() in ("1", "true", "yes", "on"):
            return True
        if raw.strip().lower() in ("0", "false", "no", "off", ""):
            return False
        raise ValueError("expected true/false")
    if kind == "list":
        raw = raw.strip()
        if raw.startswith("["):
            value = json.loads(raw)
            if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
                raise ValueError("expected a JSON list of strings")
            return value
        return [t.strip() for t in raw.split(",") if t.strip()]
    if kind == "json":
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value
    return kind(raw)
