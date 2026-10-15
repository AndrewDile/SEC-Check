"""Teams (Web App API 4.16) plus session, health and dev-only helpers."""
from __future__ import annotations

from typing import Any, Dict

from ..errors import WebAppError
from . import Context, Request, can_decide, extension, operation


@operation("listTeams")
def list_teams(ctx: Context, req: Request) -> Dict[str, Any]:
    return {"Teams": list(ctx.settings.teams)}


@extension("GET", "/session", note="Who is signed in, their teams, and whether they may record decisions")
def session(ctx: Context, req: Request) -> Dict[str, Any]:
    return {"User": req.user.name, "Teams": req.user.teams, "Can_Decide": can_decide(ctx, req.user)}


@extension("GET", "/dev/users", auth=False, note="Development sign-in list; only when auth_mode is 'dev'")
def dev_users(ctx: Context, req: Request) -> Dict[str, Any]:
    if ctx.settings.auth_mode != "dev":
        raise WebAppError("NOT_FOUND", "Not available.")
    hidden = {ctx.settings.mock_core_gateway_user}  # service account, not a person
    return {"Users": [{"User": name, "Teams": teams} for name, teams in ctx.settings.users.items() if name not in hidden]}


@extension("GET", "/health", auth=False, note="Liveness plus whether the Core API answers")
def health(ctx: Context, req: Request) -> Dict[str, Any]:
    try:
        ctx.core.dp_match(None, "__healthcheck__")
        core_ok, detail = True, "reachable"
    except WebAppError as exc:
        core_ok, detail = exc.error in ("DP_DNE", "INVALID_DATA"), f"{exc.error}: {exc.message}"
    return {"Status": "OK", "Core_API_URL": ctx.core.base_url, "Core_API_Reachable": core_ok, "Core_API_Detail": detail}
