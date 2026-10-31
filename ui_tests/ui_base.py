"""Shared setup for the browser tests: settings, a Core API client, and the base test class.

Every test starts from an empty database (it calls the Core API's /reset), opens a
fresh browser context, and signs in as `user`. When a test fails, a Playwright
trace and a screenshot are saved under ui_tests/artifacts/.

Settings (environment variables):
  WEB_URL            Web App base URL               default http://localhost:8000
  CORE_URL           Core API base URL              default http://localhost:3001
  HEADED=1           show the browser window
  SLOWMO=300         pause this many ms between browser actions (with HEADED, to watch)
  BROWSER            chromium | firefox | webkit    default chromium
  UI_TIMEOUT_MS      how long to wait for elements  default 10000
  UI_ALLOW_REMOTE=1  allow URLs other than localhost (the tests WIPE the database)
"""
from __future__ import annotations

import json
import os
import re
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from playwright.sync_api import Page, expect, sync_playwright

WEB_URL = os.environ.get("WEB_URL", "http://localhost:8000").rstrip("/")
CORE_URL = os.environ.get("CORE_URL", "http://localhost:3001").rstrip("/")
HEADED = os.environ.get("HEADED", "") not in ("", "0", "false")
SLOWMO = float(os.environ.get("SLOWMO", "0") or 0)
BROWSER = os.environ.get("BROWSER", "chromium")
TIMEOUT_MS = float(os.environ.get("UI_TIMEOUT_MS", "10000"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

expect.set_options(timeout=TIMEOUT_MS)


class Core:
    """Minimal Core API client, used to reset the database and to check what the UI stored."""

    def __init__(self, base_url: str = CORE_URL):
        self.base_url = base_url

    def post(self, path: str, body: Dict[str, Any]) -> Tuple[int, Any]:
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def ok(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        status, data = self.post(path, body)
        if status != 200:
            raise AssertionError("Core API %s answered %s: %s" % (path, status, data))
        return data

    def reset(self) -> None:
        self.ok("/reset", {"method": "RESET"})

    # Reads used to check that the UI really stored something
    def incident(self, incident_id: str) -> Dict[str, Any]:
        return self.ok("/incidents", {"Incident_ID": incident_id, "Method": "GET", "Timestamp": now(), "Description": ""})

    def incidents(self):
        return self.ok("/incidents", {"Method": "LIST", "Timestamp": now()})["Incidents"]

    def ticket(self, incident_id: str, number: str) -> Dict[str, Any]:
        return self.ok("/tickets", {"Incident_ID": incident_id, "Method": "GET", "Timestamp": now(), "Ticket_number": number})

    def log(self, incident_id: str):
        return self.ok("/logs", {"Incident_ID": incident_id, "Timestamp": now()})["Ticket_ID_List"]

    def dependency_exists(self, name: str) -> bool:
        return self.ok("/dependencies", {"dp_name": name, "method": "MATCH"})["status"] == "Exists"


def now() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_targets() -> None:
    for name, url in (("WEB_URL", WEB_URL), ("CORE_URL", CORE_URL)):
        host = urllib.parse.urlsplit(url).hostname
        if host not in LOCAL_HOSTS and os.environ.get("UI_ALLOW_REMOTE") != "1":
            raise unittest.SkipTest("%s=%s is not local and these tests wipe the database; set UI_ALLOW_REMOTE=1 "
                                    "if that's really what you want." % (name, url))
    try:
        with urllib.request.urlopen(WEB_URL + "/webapp/v1/health", timeout=10) as r:
            health = json.loads(r.read())
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("The Web App isn't reachable at %s (%s). Start the stack first: docker compose up -d --build"
                           % (WEB_URL, exc))
    if not health.get("Core_API_Reachable"):
        raise RuntimeError("The Web App can't reach its Core API: %s" % health.get("Core_API_Detail"))


class UITestCase(unittest.TestCase):
    """Base class: one browser per test class, a fresh context and empty database per test."""

    user: Optional[str] = "alice"     # signed in before each test; None = stay signed out
    core = Core()

    @classmethod
    def setUpClass(cls):
        _check_targets()
        cls._pw = sync_playwright().start()
        cls._browser = getattr(cls._pw, BROWSER).launch(headless=not HEADED, slow_mo=SLOWMO)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def setUp(self):
        self.core.reset()
        self.context = self._browser.new_context(base_url=WEB_URL)
        self.context.set_default_timeout(TIMEOUT_MS)
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page: Page = self.context.new_page()
        self._artifacts = []
        if self.user:
            self.sign_in(self.user)

    def tearDown(self):
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", self.id())
        ARTIFACTS.mkdir(exist_ok=True)
        shot, trace = ARTIFACTS / (name + ".png"), ARTIFACTS / (name + ".zip")
        try:
            self.page.screenshot(path=str(shot), full_page=True)
            self._artifacts.append(shot)
        except Exception:  # noqa: BLE001  (the page may already be gone)
            pass
        self.context.tracing.stop(path=str(trace))
        self._artifacts.append(trace)
        self.context.close()

    def run(self, result=None):
        result = result or self.defaultTestResult()
        problems = len(result.failures) + len(result.errors)
        super().run(result)
        if len(result.failures) + len(result.errors) == problems:   # passed: keep nothing
            for path in getattr(self, "_artifacts", []):
                path.unlink(missing_ok=True)
        return result

    # ------------------------------------------------------------------ UI helpers
    def tid(self, test_id: str, root=None):
        return (root or self.page).get_by_test_id(test_id)

    def sign_in(self, user: str) -> None:
        # Let the app finish starting up (it may be signing in the user remembered from
        # last time), then switch user and wait until the new user's teams have loaded.
        self.page.goto("/app/", wait_until="networkidle")
        select = self.tid("user-select")
        if select.input_value() != user:
            with self.page.expect_response(lambda r: r.url.endswith("/webapp/v1/teams")):
                select.select_option(user)
        expect(self.tid("signin-prompt")).to_have_count(0)

    def go(self, hash_path: str) -> None:
        """Navigate inside the single-page app, e.g. go('#/dependencies')."""
        self.page.goto("/app/" + hash_path)

    def expect_notice(self, text: str, kind: str = "ok") -> None:
        notice = self.tid("notice")
        expect(notice).to_be_visible()
        expect(notice).to_have_class(re.compile(r"\b%s\b" % kind))
        expect(notice).to_contain_text(text)

    def report_incident(self, description: str, materiality: str = "UNDECIDED", severity: str = "UNDECIDED",
                        urgency: str = "UNDECIDED", dependency: Optional[str] = None,
                        incident_id: Optional[str] = None) -> str:
        """Fill in and submit the intake form; return the new incident's ID."""
        self.go("#/incidents")
        self.tid("new-incident").click()
        form = self.tid("intake-form")
        self.tid("intake-description", form).fill(description)
        if dependency:
            self.tid("intake-dependency", form).select_option(dependency)
        if incident_id:
            self.tid("intake-id", form).fill(incident_id)
        self.tid("intake-materiality", form).select_option(materiality)
        self.tid("intake-severity", form).select_option(severity)
        self.tid("intake-urgency", form).select_option(urgency)
        self.tid("intake-submit", form).click()
        self.page.wait_for_url(re.compile(r"#/incidents/[^/]+$"))
        self.expect_notice("created")
        incident = self.tid("incident-id").inner_text().strip()
        self.assertTrue(incident, "the detail page shows no incident ID")
        return incident

    def log_ticket(self, description: str, severity: str = "", urgency: str = "", teams=(), notify: bool = True):
        """On an incident's page, submit the "Log a ticket" form."""
        form = self.tid("ticket-form")
        self.tid("ticket-description", form).fill(description)
        if severity:
            self.tid("ticket-severity", form).select_option(severity)
        if urgency:
            self.tid("ticket-urgency", form).select_option(urgency)
        for team in teams:
            self.tid("team-" + team, form).check()
        if not notify:
            self.tid("ticket-notify", form).uncheck()
        self.tid("ticket-submit", form).click()
        self.expect_notice("logged")

    def ticket_item(self, number: str):
        """The ticket in the incident page's ticket list with this weak number (e.g. '123_2')."""
        return self.page.locator('[data-testid="ticket"][data-ticket-number="%s"]' % number)
