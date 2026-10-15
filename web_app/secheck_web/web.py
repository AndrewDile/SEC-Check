"""Minimal HTTP plumbing on the Python standard library.

No third-party packages are needed, so the app runs anywhere Python 3.9+ is
installed. Both the Web App and the mock Core API use this module.
"""
from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

Response = Tuple[int, Dict[str, str], bytes]


def json_response(status: int, payload: Any, extra_headers: Optional[Dict[str, str]] = None) -> Response:
    body = json.dumps(payload, indent=2).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
    headers.update(extra_headers or {})
    return status, headers, body


def redirect(location: str) -> Response:
    return 302, {"Location": location}, b""


def static_file(root: Path, rel_path: str) -> Optional[Response]:
    """Serve a file under root, refusing paths that escape it."""
    root = root.resolve()
    target = (root / rel_path.lstrip("/")).resolve()
    if target.is_dir():
        target = target / "index.html"
    if root not in target.parents and target != root:
        return None
    if not target.is_file():
        return None
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
        ctype += "; charset=utf-8"
    return 200, {"Content-Type": ctype, "Cache-Control": "no-cache"}, target.read_bytes()


class Route:
    def __init__(self, method: str, template: str, handler: Callable, meta: Dict[str, Any]):
        self.method = method.upper()
        self.template = template
        self.handler = handler
        self.meta = meta
        pattern, names = "^", []
        pos = 0
        for m in re.finditer(r"{([^}/]+)}", template):
            pattern += re.escape(template[pos:m.start()]) + "([^/]+)"
            names.append(m.group(1))
            pos = m.end()
        pattern += re.escape(template[pos:]) + "/?$"
        self.regex = re.compile(pattern)
        self.param_names = names


class Router:
    def __init__(self) -> None:
        self.routes: List[Route] = []

    def add(self, method: str, template: str, handler: Callable, **meta: Any) -> None:
        self.routes.append(Route(method, template, handler, meta))

    def match(self, method: str, path: str) -> Tuple[Optional[Route], Dict[str, str], bool]:
        """Return (route, path_params, path_exists)."""
        path_exists = False
        for route in self.routes:
            m = route.regex.match(path)
            if not m:
                continue
            path_exists = True
            if route.method == method.upper():
                params = {n: unquote(v) for n, v in zip(route.param_names, m.groups())}
                return route, params, True
        return None, {}, path_exists


def make_server(app: Any, host: str, port: int, name: str = "server") -> ThreadingHTTPServer:
    """Create a threaded HTTP server that forwards every request to app.handle()."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "SEC-Check"
        sys_version = ""

        def _dispatch(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            try:
                status, headers, payload = app.handle(self.command, self.path, self.headers, body)
            except Exception as exc:  # last-resort guard; app.handle should not raise
                status, headers, payload = json_response(500, {"Error": "INTERNAL_ERROR", "Message": str(exc)})
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _dispatch

        def log_message(self, fmt: str, *args: Any) -> None:
            if getattr(app, "log_requests", False):
                sys.stderr.write(f"[{name}] {self.address_string()} {fmt % args}\n")

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def parse_cookies(header: Optional[str]) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            cookies[key.strip()] = unquote(value.strip())
    return cookies
