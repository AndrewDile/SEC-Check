"""Teams (Web App API 4.16 plus team management), session, health and dev-only helpers.

Teams and their members are stored by the Core API (/teams, and /users for each user's
teams); ctx.memberships (membership.py) reads and changes the members.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..errors import WebAppError, invalid
from . import Context, Request, can_decide, extension, operation


@operation("listTeams")
def list_teams(ctx: Context, req: Request) -> Dict[str, Any]:
    return {"Teams": ctx.teams()}


def _visible_users(ctx: Context) -> List[str]:
    hidden = set(ctx.settings.hidden_users)  # service accounts, e.g. the Core API gateway user
    return [name for name in ctx.settings.users if name not in hidden]


def _user_teams_or_none(ctx: Context, user: str) -> List[str]:
    """The user's teams, or none if the Core API can't be reached (so sign-in still loads)."""
    try:
        return ctx.user_teams(user)
    except WebAppError:
        return []


def _require_user(ctx: Context, user: str) -> None:
    if user not in _visible_users(ctx):
        raise WebAppError("USER_DNE", f"User {user} does not exist.")


def _team_name(body: Any) -> str:
    name = body.get("Team_Name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise invalid("Team_Name is required.")
    if name != name.strip() or len(name) > 64:
        raise invalid("Team_Name must be 1-64 characters without leading or trailing spaces.")
    return name


@extension("GET", "/team-members", note="Every team with its members, and the users who can join")
def team_members(ctx: Context, req: Request) -> Dict[str, Any]:
    members = ctx.memberships.members()
    visible = _visible_users(ctx)
    return {
        "Teams": [
            {"Team_Name": t, "Members": [u for u in members.get(t, []) if u in visible]}
            for t in ctx.teams()
        ],
        "Users": _visible_users(ctx),
    }


@extension("POST", "/teams", note="Create a team (Core /teams NEW)")
def create_team(ctx: Context, req: Request):
    name = _team_name(req.json)
    out = ctx.core.team_new(None, name)
    return 201, {"Team_Name": out.get("Team_Name", name), "Members": [], "Status": "Created"}


@extension(
    "DELETE", "/teams/{Team_Name}", note="Remove a team and its members (Core /teams REMOVE)"
)
def remove_team(ctx: Context, req: Request) -> Dict[str, Any]:
    name = req.path_params["Team_Name"]
    ctx.core.team_remove(None, name)
    return {"Team_Name": name, "Status": "Removed"}


@extension("POST", "/teams/{Team_Name}/members", note="Add a user to a team (ADD_USER)")
def add_member(ctx: Context, req: Request) -> Dict[str, Any]:
    team = req.path_params["Team_Name"]
    user = req.json.get("User") if isinstance(req.json, dict) else None
    if not isinstance(user, str) or not user:
        raise invalid("User is required.")
    _require_user(ctx, user)
    if user in ctx.memberships.members_of(team):  # members_of raises TEAM_DNE
        raise invalid(f"{user} is already a member of {team}.")
    ctx.memberships.add(team, user)
    return {
        "Team_Name": team,
        "User": user,
        "Members": ctx.memberships.members_of(team),
        "Status": "User added",
    }


@extension(
    "DELETE", "/teams/{Team_Name}/members/{User}", note="Remove a user from a team (REMOVE_USER)"
)
def remove_member(ctx: Context, req: Request) -> Dict[str, Any]:
    team, user = req.path_params["Team_Name"], req.path_params["User"]
    _require_user(ctx, user)
    if user not in ctx.memberships.members_of(team):  # members_of raises TEAM_DNE
        raise invalid(f"{user} is not a member of {team}.")
    ctx.memberships.remove(team, user)
    return {
        "Team_Name": team,
        "User": user,
        "Members": ctx.memberships.members_of(team),
        "Status": "User removed",
    }


@extension(
    "GET", "/session", note="Who is signed in, their teams, and whether they may record decisions"
)
def session(ctx: Context, req: Request) -> Dict[str, Any]:
    return {"User": req.user.name, "Teams": req.user.teams, "Can_Decide": can_decide(ctx, req.user)}


@extension(
    "GET", "/dev/users", auth=False, note="Development sign-in list; only when auth_mode is 'dev'"
)
def dev_users(ctx: Context, req: Request) -> Dict[str, Any]:
    if ctx.settings.auth_mode != "dev":
        raise WebAppError("NOT_FOUND", "Not available.")
    return {
        "Users": [
            {"User": name, "Teams": _user_teams_or_none(ctx, name)} for name in _visible_users(ctx)
        ]
    }


@extension("GET", "/health", auth=False, note="Liveness plus whether the Core API answers")
def health(ctx: Context, req: Request) -> Dict[str, Any]:
    try:
        ctx.core.dp_match(None, "__healthcheck__")
        core_ok, detail = True, "reachable"
    except WebAppError as exc:
        # Any Core API error reply (even NOT_IMPLEMENTED from an unfinished Core API) means it answered.
        core_ok = exc.error not in ("UPSTREAM_UNAVAILABLE", "TIMEOUT")
        detail = f"{exc.error}: {exc.message}"
    return {
        "Status": "OK",
        "Core_API_URL": ctx.core.base_url,
        "Core_API_Reachable": core_ok,
        "Core_API_Detail": detail,
    }
