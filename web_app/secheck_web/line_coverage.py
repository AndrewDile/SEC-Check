"""Line coverage of this service, for the Core API's /test/report. Standard library only.

Counts the lines inside functions (module and class bodies only run at import) that requests run.
This module answers the Core API's /coverage itself, in front of the service's code (handler() for
http.server, Middleware for ASGI), so measuring adds no lines. Health checks and background work
are kept out with quiet(). Each line is recorded once, then switched off until the next snapshot.

Edit web_app/secheck_web/line_coverage.py only: the worker's and notifier's copies are generated
from it (architecture/model.yaml, ./verify.sh --fix).
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import functools
import hmac
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import CodeType
from urllib.parse import parse_qs, urlsplit

NEWLOCALS = 0x2  # inspect.CO_NEWLOCALS: set on functions, not on module or class bodies
ROOT = Path(__file__).resolve().parent
PATHS = ("/coverage", "/coverage/snapshot")
_mon = getattr(sys, "monitoring", None)  # Python 3.12+; without it coverage is off
ENABLED = _mon is not None and os.environ.get("CODE_COVERAGE") != "off"
TOKEN = os.environ.get("INBOUND_TOKEN", "")  # the Core API's; empty turns /coverage off

_tool = 1  # sys.monitoring.COVERAGE_ID
_lock = threading.Lock()
_generation = 0
_started = 0.0  # when start() began counting, Unix time
_last: dict[tuple[str, int], int] = {}  # (file, line) -> generation it last ran in
_ours: dict[str, str | None] = {}  # co_filename -> path relative to ROOT, or None
# A ContextVar, not a thread local, so it follows an ASGI request into its handler's thread
_quiet = contextvars.ContextVar("line_coverage_quiet", default=False)


def _relative(filename: str) -> str | None:
    if filename not in _ours:
        path = Path(filename).resolve()
        ok = path.is_relative_to(ROOT) and "tests" not in path.relative_to(ROOT).parts
        _ours[filename] = path.relative_to(ROOT).as_posix() if ok else None
    return _ours[filename]


def _line(code: CodeType, line: int) -> object:
    name = code.co_flags & NEWLOCALS and _relative(code.co_filename)
    if name and _quiet.get():
        return None  # left on, so a counted request still records the line
    if name:
        _last[(name, line)] = _generation
    return _mon.DISABLE


def start() -> None:
    global _started
    if ENABLED and _mon.get_tool(_tool) is None:  # not if another tool (coverage.py) has it
        _started = time.time()
        _mon.use_tool_id(_tool, "line_coverage")
        _mon.register_callback(_tool, _mon.events.LINE, _line)
        _mon.set_events(_tool, _mon.events.LINE)
        atexit.register(_mon.set_events, _tool, 0)  # before shutdown clears this module's globals


def quiet() -> None:
    """Stop counting what the current thread or task runs, e.g. a background loop."""
    _quiet.set(True)


@contextlib.contextmanager
def counted():
    """Count what runs inside, in a quiet thread: work a request asked for."""
    token = _quiet.set(False)
    try:
        yield
    finally:
        _quiet.reset(token)


# Lines that ran since a snapshot have its generation or later; overlapping sessions share them
def snapshot() -> int:
    global _generation
    with _lock:
        _generation += 1
        if ENABLED:
            _mon.restart_events()
        return _generation


def _functions(code: CodeType):
    for const in code.co_consts:
        if isinstance(const, CodeType):
            if const.co_flags & NEWLOCALS:
                yield const
            yield from _functions(const)


@functools.cache
def _lines() -> frozenset[tuple[str, int]]:
    lines = set()
    for path in ROOT.rglob("*.py"):
        name = _relative(str(path))
        if name is None or path.name == "line_coverage.py":
            continue
        for fn in _functions(compile(path.read_text(encoding="utf-8"), str(path), "exec")):
            # The def line runs in the enclosing code, never in the function itself
            lines |= {(name, n) for _, _, n in fn.co_lines() if n and n != fn.co_firstlineno}
    return frozenset(lines)


def lines(since: int) -> dict[str, object]:
    total = _lines()
    covered = sum(1 for key, gen in list(_last.items()) if gen >= since and key in total)
    return {"covered": covered, "total": len(total), "enabled": ENABLED, "started": _started}


def respond(method: str, path: str, query: str, authorization: str) -> tuple[int, dict]:
    """POST /coverage/snapshot and GET /coverage?since=N, for the Core API only."""
    if not TOKEN or not hmac.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode()):
        return 401, {"Error": "UNAUTHORIZED", "Message": "Bad token."}
    if method == "POST" and path == "/coverage/snapshot":
        return 200, {"since": snapshot()}
    if method == "GET" and path == "/coverage":
        since = parse_qs(query).get("since", [""])[-1]
        if not since.isdigit():
            return 400, {"Error": "INVALID_DATA", "Message": "since must be a whole number."}
        if int(since) > _generation:  # a restart reset the generations, so its lines are gone
            return 409, {"Error": "RESTARTED", "Message": "Restarted since that snapshot."}
        return 200, lines(int(since))
    return 405, {"Error": "METHOD_NOT_ALLOWED", "Message": f"{method} {path}."}


def handler(cls: type, ignore: tuple[str, ...] = ()) -> type:
    """cls, an http.server request handler, with /coverage answered here and ignore's paths not counted."""

    class Handler(cls):
        def parse_request(self) -> bool:
            if not super().parse_request():
                return False
            url = urlsplit(self.path)
            mine = url.path in PATHS
            _quiet.set(mine or url.path in ignore)
            if not mine:
                return True
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, body = respond(
                self.command, url.path, url.query, self.headers.get("Authorization") or ""
            )
            data = json.dumps(body).encode()
            self.send_response_only(status)  # not send_response, which logs through cls
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return False  # answered: http.server doesn't dispatch it

    return Handler


class Middleware:
    """ASGI middleware with /coverage answered here and ignore's paths not counted."""

    def __init__(self, app, ignore: tuple[str, ...] = ()):
        self.app, self.ignore = app, ignore

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or path not in PATHS:
            token = _quiet.set(path in self.ignore)
            try:
                return await self.app(scope, receive, send)
            finally:
                _quiet.reset(token)
        auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        status, body = respond(scope["method"], path, scope["query_string"].decode("latin-1"), auth)
        data = json.dumps(body).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(data)).encode()),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": data})
