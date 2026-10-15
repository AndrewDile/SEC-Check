"""Test harness: real HTTP servers on free ports, plus two-way contract checks.

Every test request goes through the Web App over HTTP, exactly as the browser
would. After each call the harness checks:
  - the Web App response against the Web App contract (contracts/webapp_api.json)
  - every request the Web App sent to the (mock) Core API against the Core
    contract (contracts/core_api.json); the mock also rejects invalid requests.
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

WEB_DEV = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DEV))

from mock_core.server import EXTENSION_METHODS, MockCore  # noqa: E402
from secheck_web.app import WebApp  # noqa: E402
from secheck_web.config import Settings  # noqa: E402
from secheck_web.validation import Spec  # noqa: E402
from secheck_web.web import make_server, serve_in_thread  # noqa: E402

TEAMS = ["LEGAL", "CYBER1", "CYBER2"]
USERS = {"alice": ["CYBER1"], "bob": ["CYBER2"], "carol": ["LEGAL"], "dana": ["LEGAL", "CYBER1"],
         "core-gateway": ["LEGAL", "CYBER1", "CYBER2"]}  # service user the mock Core API forwards as


def make_settings(**overrides: Any) -> Settings:
    values = dict(teams=TEAMS, users=USERS, decision_teams=[], log_requests=False, start_mock_core=False)
    values.update(overrides)
    return Settings(**values)


class Stack:
    """Mock Core API + Web App, each on its own free localhost port.

    forwarding=True puts the mock in gateway mode: Core API calls from test
    clients are forwarded to the Web App (see mock_core/gateway.py).
    """

    def __init__(self, forwarding: bool = False, **settings_overrides: Any):
        self.settings = make_settings(**settings_overrides)
        self.mock = MockCore(teams=self.settings.teams, contract=self.settings.core_contract)
        self.core_server = make_server(self.mock, "127.0.0.1", 0)
        serve_in_thread(self.core_server)
        self.settings.core_api_url = f"http://127.0.0.1:{self.core_server.server_address[1]}"
        self.app = WebApp(self.settings)
        self.web_server = make_server(self.app, "127.0.0.1", 0)
        serve_in_thread(self.web_server)
        self.url = f"http://127.0.0.1:{self.web_server.server_address[1]}"
        if forwarding:
            self.mock.webapp_url = self.url
        self.core_spec = Spec.load(self.settings.core_contract)

    def close(self) -> None:
        for server in (self.web_server, self.core_server):
            server.shutdown()
            server.server_close()


def http(method: str, url: str, body: Any = None, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as resp:
            raw, status = resp.read(), resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    try:
        return status, json.loads(raw.decode()) if raw else None
    except ValueError:
        return status, raw.decode(errors="replace")


class WebAppTestCase(unittest.TestCase):
    stack_settings: Dict[str, Any] = {}
    forwarding = False
    user: Optional[str] = "dana"

    @classmethod
    def setUpClass(cls) -> None:
        cls.stack = Stack(forwarding=cls.forwarding, **cls.stack_settings)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()

    def setUp(self) -> None:
        self.stack.mock.wipe()
        self.stack.mock.request_log.clear()
        self.stack.mock.forward_log.clear()

    def tearDown(self) -> None:
        self.assert_core_requests_follow_contract()

    # ---------------------------------------------------------------- calls
    def call(self, method: str, path: str, body: Any = None, user: Any = "default", check: bool = True) -> Tuple[int, Any]:
        who = self.user if user == "default" else user
        headers = {"X-User": who} if who else {}
        status, data = http(method, f"{self.stack.url}/webapp/v1{path}", body, headers)
        if check:
            self.assert_matches_webapp_contract(method, f"/webapp/v1{path.split('?')[0]}", status, data)
        return status, data

    def ok(self, method: str, path: str, body: Any = None, **kw: Any) -> Any:
        status, data = self.call(method, path, body, **kw)
        self.assertEqual(status, 200, f"{method} {path} -> {status}: {data}")
        return data

    def err(self, method: str, path: str, body: Any, status: int, error: str, **kw: Any) -> Any:
        got_status, data = self.call(method, path, body, **kw)
        self.assertEqual((got_status, data.get("Error")), (status, error), f"{method} {path}: {data}")
        return data

    def core(self, path: str, body: Any, check: bool = True) -> Tuple[int, Any]:
        """Call the Core API directly, as an external API test client would (no origin header)."""
        status, data = http("POST", f"{self.stack.settings.core_api_url}{path}", body)
        if check:
            self.assert_matches_core_contract(path, body, status, data)
        return status, data

    def core_ok(self, path: str, body: Any) -> Any:
        status, data = self.core(path, body)
        self.assertEqual(status, 200, f"Core {path} {body} -> {status}: {data}")
        return data

    def core_err(self, path: str, body: Any, error: str) -> Any:
        status, data = self.core(path, body)
        self.assertEqual((status, data.get("Error")), (400, error), f"Core {path}: {data}")
        self.assertEqual(set(data), {"Error", "Message"}, "Core errors use the Core envelope only")
        return data

    def forwarded(self) -> list:
        """Web App requests the mock Core API generated, as "METHOD /path" (query string dropped)."""
        return [e["web"].split("?")[0] for e in self.stack.mock.forward_log]

    # ---------------------------------------------------------------- fixtures
    def new_incident(self, **fields: Any) -> Dict[str, Any]:
        body = {"Description": "Test incident"}
        body.update(fields)
        return self.ok("POST", "/incidents", body)

    # ---------------------------------------------------------------- contract checks
    def assert_matches_webapp_contract(self, method: str, path: str, status: int, data: Any) -> None:
        app = self.stack.app
        route, _, _ = app.router.match(method, path)
        if route is None or not route.meta.get("spec"):
            return  # extension route: not in the contract yet
        responses = route.meta["op"].get("responses", {})
        spec_resp = responses.get(str(status))
        if spec_resp is None:
            # Statuses beyond those listed must still use the error envelope.
            if status >= 400:
                self.assertIsInstance(data, dict)
                self.assertIn("Error", data)
                self.assertIn("Message", data)
            return
        spec_resp = app.spec.resolve(spec_resp)
        schema = ((spec_resp.get("content") or {}).get("application/json") or {}).get("schema")
        if schema:
            errors = app.spec.validate(data, schema)
            self.assertEqual(errors, [], f"{method} {path} response does not match the Web App contract")

    def assert_matches_core_contract(self, path: str, body: Any, status: int, data: Any) -> None:
        """Core API responses must match the Core contract (200s; errors use {Error, Message})."""
        if status != 200:
            self.assertIn("Error", data)
            self.assertIn("Message", data)
            return
        if isinstance(body, dict) and body.get("Method", body.get("method")) in EXTENSION_METHODS:
            return
        spec = self.stack.core_spec
        op = spec.doc["paths"].get(path, {}).get("post")
        if not op:
            return
        resp = spec.resolve(op["responses"]["200"])
        schema = resp["content"]["application/json"]["schema"]
        self.assertEqual(spec.validate(data, schema), [], f"Core {path} response does not match the Core contract")

    def assert_core_requests_follow_contract(self) -> None:
        spec = self.stack.core_spec
        for entry in self.stack.mock.request_log:
            if entry.get("origin") != "webapp":
                continue  # only check what the Web App sent; tests may send bad requests on purpose
            body = entry["body"]
            if body.get("Method", body.get("method")) in EXTENSION_METHODS:
                continue
            path = "/dependencies" if entry["path"] == "/dependancies" else entry["path"]
            op = spec.doc["paths"][path]["post"]
            errors = spec.validate(body, spec.request_schema(op))
            self.assertEqual(errors, [], f"Web App sent {path} {body} which breaks the Core contract")
