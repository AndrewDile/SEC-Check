"""HTTP interface of the tester (openapi/tester.yaml):

  POST /test/setup   {"target_url"}   -> 201 {"session_id"}
  POST /test/run     {"session_id"}   -> 200 report | 500 partial run
  GET  /test/report?session_id=...    -> 200 report | 409 not finished
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Tuple

from .config import Settings
from .runner import run_suite
from .sessions import DONE, Session, SessionStore
from .target import Target, validate_target_url

log = logging.getLogger("secheck_tester")
SOURCES = {"tester", "system", "communication", "unknown"}

Result = Tuple[int, Dict[str, Any]]


def error(status: int, message: str, source: str = "tester") -> Result:
    return status, {"message": message, "source": source}


class TesterApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions = SessionStore()

    # ------------------------------------------------------------------ routing
    def handle(self, method: str, raw_path: str, body: bytes) -> Result:
        parts = urllib.parse.urlsplit(raw_path)
        path = parts.path.rstrip("/") or "/"
        base = self.settings.base_path
        if base:
            if path != base and not path.startswith(base + "/"):
                return error(404, "Not found: %s" % path)
            path = path[len(base):] or "/"
        routes = {
            ("POST", "/test/setup"): self.setup,
            ("POST", "/test/run"): self.run,
            ("GET", "/test/report"): self.report,
        }
        handler = routes.get((method, path))
        if handler is None:
            if any(p == path for _, p in routes):
                return error(405, "%s is not allowed on %s." % (method, path))
            return error(404, "Not found: %s" % path)
        if method == "GET":
            return handler(urllib.parse.parse_qs(parts.query))
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (ValueError, UnicodeDecodeError):
            return error(400, "Request body is not valid JSON.")
        if not isinstance(payload, dict):
            return error(400, "Request body must be a JSON object.")
        return handler(payload)

    # ------------------------------------------------------------------ endpoints
    def setup(self, payload: Dict[str, Any]) -> Result:
        try:
            target_url = validate_target_url(payload.get("target_url"))
        except ValueError as exc:
            return error(400, str(exc))
        session_id = self.sessions.new_id()
        reply = Target(target_url, self.settings, session_id).setup()
        if reply.status is None:
            return error(500, "Target %s/test/setup didn't respond: %s." % (target_url, reply.error), "communication")
        body = reply.body if isinstance(reply.body, dict) else {}
        if reply.status != 201:
            message = body.get("message") if isinstance(body.get("message"), str) and body.get("message") else \
                "Target /test/setup answered %s." % reply.status
            source = body.get("source") if body.get("source") in SOURCES else "unknown"
            return reply.status, {"message": message, "source": source}
        if body.get("session_id") != session_id:
            return error(500, "Target /test/setup answered 201 with session_id %r, expected %r."
                         % (body.get("session_id"), session_id), "system")
        self.sessions.add(Session(session_id, target_url))
        log.info("session %s ready for %s", session_id, target_url)
        return 201, {"session_id": session_id}

    def run(self, payload: Dict[str, Any]) -> Result:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return error(400, "session_id must be a non-empty string.")
        session = self.sessions.get(session_id)
        if session is None:
            return error(404, "Unknown session_id %s." % session_id)
        if self.sessions.start_run(session_id) is None:
            return error(409, "Session %s has already been run; set up a new session." % session_id)
        try:
            report, abort_message = run_suite(session_id, session.target_url, self.settings)
        except Exception as exc:  # noqa: BLE001
            log.exception("run %s crashed", session_id)
            report = crashed_report(session_id, session.target_url, "%s: %s" % (type(exc).__name__, exc))
            self.sessions.finish(session_id, report)
            return error(500, "The tester failed while running the suite: %s" % exc)
        self.sessions.finish(session_id, report)
        log.info("session %s finished: %s", session_id, _summary(report))
        if abort_message:
            return error(500, abort_message)
        return 200, report

    def report(self, query: Dict[str, Any]) -> Result:
        values = query.get("session_id") or [""]
        session_id = values[0]
        if not session_id:
            return error(400, "The session_id query parameter is required.")
        session = self.sessions.get(session_id)
        if session is None:
            return error(404, "Unknown session_id %s." % session_id)
        if session.state != DONE:
            return error(409, "Session %s has not finished running; retry later." % session_id)
        return 200, session.report


def crashed_report(session_id: str, target_url: str, reason: str) -> Dict[str, Any]:
    """A valid report for a run the tester itself couldn't finish."""
    from .coverage import measure
    from .suite import SUITE
    unknown = measure(None, None, "Not measured: the tester failed (%s)." % reason)
    return {
        "session_id": session_id,
        "target_url": target_url,
        "results": [{"test_id": t.test_id, "outcome": "error", "message": "Tester failed: " + reason, "source": "tester"}
                    for t in SUITE],
        "coverage": {"code": unknown, "component": unknown, "system": unknown},
    }


def _summary(report: Dict[str, Any]) -> str:
    counts: Dict[str, int] = {}
    for r in report.get("results", []):
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))


def make_handler(app: TesterApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SECheckTester/1.0"
        protocol_version = "HTTP/1.1"

        def _respond(self, status: int, body: Dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b""
            try:
                status, out = app.handle(method, self.path, body)
            except Exception as exc:  # noqa: BLE001
                log.exception("unhandled error")
                status, out = error(500, "Tester internal error: %s" % exc)
            self._respond(status, out)

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def do_PUT(self):  # noqa: N802
            self._dispatch("PUT")

        def do_DELETE(self):  # noqa: N802
            self._dispatch("DELETE")

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

    return Handler
