"""The Web App: spec-driven routing, auth, validation and error handling.

Routes come from contracts/webapp_api.json. For every spec operation the app:
  1. checks the signed-in user (unless the route is marked public),
  2. validates path parameters, query parameters and the JSON body against the
     spec (any failure -> 400 INVALID_DATA),
  3. calls the handler registered under the operation's operationId.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from .config import Settings
from .core_client import CoreClient
from .errors import WebAppError, invalid
from .handlers import EXTENSIONS, OPERATIONS, Context, Request, User
from .validation import Spec, coerce_query
from .web import Response, Router, json_response, parse_cookies, redirect, static_file

SESSION_COOKIE = "secheck_session"  # matches securitySchemes.sessionCookie in the spec


class WebApp:
    def __init__(
        self,
        settings: Settings,
        core: Optional[CoreClient] = None,
        context: Optional[Context] = None,
    ):
        self.settings = settings
        self.log_requests = settings.log_requests
        self.spec = Spec.load(settings.webapp_contract)
        self.base = self.spec.base_path() or "/webapp/v1"
        self.core = core or CoreClient(
            settings.core_api_url, settings.core_timeout_seconds, settings.core_use_system_proxy
        )
        self.ctx = context or Context(settings=settings, core=self.core)
        self.router = Router()
        self.missing_handlers: List[str] = []
        self.unused_handlers: List[str] = []
        self._build_routes()

    # ------------------------------------------------------------------ routing
    def _build_routes(self) -> None:
        used = set()
        for path, method, op, item in self.spec.operations():
            op_id = op.get("operationId") or f"{method.upper()} {path}"
            handler = OPERATIONS.get(op_id)
            if handler is None:
                self.missing_handlers.append(op_id)
                handler = _not_implemented(op_id)
            else:
                used.add(op_id)
            self.router.add(
                method, self.base + path, handler, op=op, path_item=item, auth=True, spec=True
            )
        for ext in EXTENSIONS:
            self.router.add(
                ext["method"], self.base + ext["path"], ext["handler"], auth=ext["auth"], spec=False
            )
        self.unused_handlers = sorted(set(OPERATIONS) - used)

    def describe_routes(self) -> List[str]:
        lines = []
        for r in self.router.routes:
            tag = "" if r.meta.get("spec") else "  [extension]"
            lines.append(f"{r.method:6} {r.template}{tag}")
        return lines

    # ------------------------------------------------------------------ entry point
    def handle(self, method: str, target: str, headers: Any, body: bytes) -> Response:
        url = urlsplit(target)
        path = url.path
        if method == "GET" and path in ("", "/"):
            return redirect("/app/")
        if method in ("GET", "HEAD") and (path == "/app" or path.startswith("/app/")):
            if path == "/app":
                return redirect("/app/")
            found = static_file(self.settings.static_dir, path[len("/app/") :] or "index.html")
            return found or json_response(
                404, {"Error": "NOT_FOUND", "Message": f"No file at {path}."}
            )
        if method == "GET" and path == "/openapi.json":
            return json_response(200, self.spec.doc)
        try:
            route, params, path_exists = self.router.match(method, path)
            if route is None:
                if path_exists:
                    raise WebAppError("METHOD_NOT_ALLOWED", f"{method} is not supported on {path}.")
                raise WebAppError("NOT_FOUND", f"No endpoint at {path}.")
            req = Request(method=method, path=path, path_params=params, headers=headers)
            if route.meta.get("auth", True):
                req.user = self._authenticate(headers)
            req.json = self._parse_body(body)
            if route.meta.get("spec"):
                self._validate(route.meta["op"], route.meta["path_item"], req, url.query)
            else:
                req.query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            result = route.handler(self.ctx, req)
            status, payload = result if isinstance(result, tuple) else (200, result)
            return json_response(status, payload)
        except WebAppError as exc:
            return json_response(exc.status, exc.to_body())
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return json_response(
                500,
                {
                    "Error": "INTERNAL_ERROR",
                    "Message": "Unexpected server error; see the server log.",
                },
            )

    # ------------------------------------------------------------------ helpers
    def _authenticate(self, headers: Any) -> User:
        """Development auth: X-User header or secheck_session cookie (auth is TBD, gap G-6)."""
        name = (headers.get("X-User") if headers else None) or parse_cookies(
            headers.get("Cookie") if headers else None
        ).get(SESSION_COOKIE)
        if not name:
            raise WebAppError("UNAUTHORIZED", "Sign in to continue.")
        if name not in self.settings.users:
            raise WebAppError("UNAUTHORIZED", f"Unknown user {name}.")
        return User(name=name, teams=list(self.settings.users[name]))

    @staticmethod
    def _parse_body(body: bytes) -> Any:
        if not body or not body.strip():
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise invalid("Request body is not valid JSON.")

    def _validate(
        self, op: Dict[str, Any], path_item: Dict[str, Any], req: Request, raw_query: str
    ) -> None:
        errors: List[str] = []
        query = parse_qs(raw_query, keep_blank_values=False)
        for param in self.spec.parameters(op, path_item):
            name, where = param["name"], param["in"]
            schema = self.spec.resolve(param.get("schema") or {})
            if where == "path":
                errors += self.spec.validate(req.path_params.get(name), schema, name)
            elif where == "query":
                if name in query:
                    value = coerce_query(query[name][-1], schema)
                    errors += self.spec.validate(value, schema, name)
                    req.query[name] = value
                elif param.get("required"):
                    errors.append(f"{name} is required")
                elif "default" in schema:
                    req.query[name] = schema["default"]
        schema = self.spec.request_schema(op)
        if schema is not None:
            if req.json is None:
                if self.spec.request_body_required(op):
                    errors.append("A JSON request body is required")
            else:
                errors += self.spec.validate(req.json, schema)
        if errors:
            raise invalid("; ".join(errors[:5]) + ".")


def _not_implemented(op_id: str):
    def handler(ctx: Context, req: Request):
        raise WebAppError(
            "NOT_IMPLEMENTED", f"Operation {op_id} is in the spec but has no handler yet."
        )

    return handler
