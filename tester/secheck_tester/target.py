"""The ONLY module that knows the target system's URLs and paths.

If the pod renames a path (for example /dependancies vs /dependencies), it is
changed here or through a setting, never in the tests.
"""
from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import Settings

SETUP_PATH = "/test/setup"
REPORT_PATH = "/test/report"


@dataclass
class Reply:
    """One HTTP exchange with the target. status is None when nothing came back."""
    path: str
    status: Optional[int]
    body: Any = None
    error: str = ""          # why there was no response (timeout, refused, ...)
    budget_hit: bool = False  # the call was cut short by the run time limit

    @property
    def answered(self) -> bool:
        return self.status is not None


def validate_target_url(url: Any) -> str:
    """Return the normalized base URL, or raise ValueError with the reason."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("target_url must be a non-empty string.")
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError("target_url must start with http:// or https://.")
    if not parts.hostname:
        raise ValueError("target_url must include a host.")
    if parts.username is not None or parts.password is not None:
        raise ValueError("target_url must not contain credentials.")
    if parts.query or parts.fragment:
        raise ValueError("target_url must not contain a query or fragment.")
    try:
        parts.port  # noqa: B018  (raises ValueError for a bad port)
    except ValueError:
        raise ValueError("target_url has an invalid port.")
    path = parts.path.rstrip("/")
    if path.split("/")[-1] == "test":
        raise ValueError("target_url is the system's base URL; leave off the /test suffix.")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class Target:
    def __init__(self, base_url: str, settings: Settings, session_id: str, deadline: Optional[float] = None):
        self.base_url = base_url
        self.settings = settings
        self.session_id = session_id
        self.deadline = deadline   # time.monotonic() value; None = no limit
        self.paths = {
            "incidents": "/incidents",
            "tickets": "/tickets",
            "notifier": "/notifier",
            "logs": "/logs",
            "dependencies": settings.dependencies_path,
        }

    # ------------------------------------------------------------------ test interface
    def setup(self) -> Reply:
        # setup is always empty: test data is created through the Core API calls themselves
        return self._send("POST", SETUP_PATH, {"session_id": self.session_id, "setup": {}},
                          self.settings.setup_timeout, use_deadline=False)

    def report(self, timeout: Optional[float] = None) -> Reply:
        query = "?" + urllib.parse.urlencode({"session_id": self.session_id})
        return self._send("GET", REPORT_PATH + query, None, timeout or self.settings.request_timeout,
                          use_deadline=False)

    # ------------------------------------------------------------------ Core API
    def core(self, name: str, body: Dict[str, Any]) -> Reply:
        """POST one Core API call. name is a key of self.paths."""
        body = dict(body)
        if self.settings.session_in_body:
            body.setdefault("session_id", self.session_id)
        return self._send("POST", self.paths[name], body, self.settings.request_timeout, use_deadline=True)

    # ------------------------------------------------------------------ transport
    def remaining(self) -> Optional[float]:
        return None if self.deadline is None else self.deadline - time.monotonic()

    def _send(self, method: str, path: str, body: Any, timeout: float, use_deadline: bool) -> Reply:
        budget_limited = False
        if use_deadline and self.deadline is not None:
            left = self.remaining()
            if left <= 0:
                return Reply(path, None, error="run time limit reached", budget_hit=True)
            if left < timeout:
                timeout, budget_limited = left, True
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.settings.session_header:
            headers[self.settings.session_header] = self.session_id
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Reply(path, resp.status, _decode(resp.read()))
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except Exception:  # noqa: BLE001
                raw = b""
            return Reply(path, exc.code, _decode(raw))
        except (socket.timeout, TimeoutError):
            return Reply(path, None, error="no response within %.1f s" % timeout, budget_hit=budget_limited)
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return Reply(path, None, error="no response within %.1f s" % timeout, budget_hit=budget_limited)
            return Reply(path, None, error="could not connect (%s)" % reason)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            return Reply(path, None, error="connection failed (%s)" % exc)


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"_raw": raw[:500].decode("utf-8", "replace")}
