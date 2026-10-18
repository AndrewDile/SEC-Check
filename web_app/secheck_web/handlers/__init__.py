"""Operation handlers, registered by the operationId used in contracts/webapp_api.json.

The router is built from the contract: each spec operation is wired to the
handler registered under its operationId. Adding an operation to the spec
without a handler makes it answer 501 NOT_IMPLEMENTED and is reported at
startup and by the tests, so spec changes cannot silently go unhandled.

Handler signature:  fn(ctx: Context, req: Request) -> dict | (status, dict)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..config import Settings
from ..core_client import CoreClient
from ..errors import WebAppError, invalid
from ..validation import utc_now

OPERATIONS: Dict[str, Callable] = {}
EXTENSIONS: List[Dict[str, Any]] = []  # routes that are not in the spec yet


def operation(operation_id: str) -> Callable:
    def register(fn: Callable) -> Callable:
        if operation_id in OPERATIONS:
            raise RuntimeError(f"Duplicate handler for operationId {operation_id}")
        OPERATIONS[operation_id] = fn
        return fn

    return register


def extension(method: str, path: str, *, auth: bool = True, note: str = "") -> Callable:
    """Register a route the Web App spec does not define yet (documented in README)."""

    def register(fn: Callable) -> Callable:
        EXTENSIONS.append(
            {"method": method, "path": path, "handler": fn, "auth": auth, "note": note}
        )
        return fn

    return register


@dataclass
class User:
    name: str
    teams: List[str]


@dataclass
class Request:
    method: str
    path: str
    path_params: Dict[str, str] = field(default_factory=dict)
    query: Dict[str, Any] = field(default_factory=dict)
    json: Any = None
    headers: Any = None
    user: Optional[User] = None


def random_incident_id() -> str:
    """12-digit numeric id, matching the Core examples (gap G-1)."""
    return str(random.SystemRandom().randint(10**11, 10**12 - 1))


@dataclass
class Context:
    settings: Settings
    core: CoreClient
    now: Callable[[], str] = utc_now
    new_incident_id: Callable[[], str] = random_incident_id


# ---------------------------------------------------------------- shared checks
def require_known_teams(ctx: Context, names: List[str], field_name: str) -> None:
    unknown = [t for t in names if t not in ctx.settings.teams]
    if unknown:
        raise invalid(f"{field_name} contains unknown team: {', '.join(unknown)}.")


def require_ticket_of_incident(incident_id: str, ticket_number: str) -> None:
    if not ticket_number.startswith(f"{incident_id}_"):
        raise invalid(
            f"Ticket_number {ticket_number} does not belong to Incident_ID {incident_id}."
        )


def can_decide(ctx: Context, user: User) -> bool:
    allowed = ctx.settings.decision_teams
    return not allowed or bool(set(user.teams) & set(allowed))


def require_can_decide(ctx: Context, user: User) -> None:
    if not can_decide(ctx, user):
        raise WebAppError(
            "FORBIDDEN",
            f"Only members of {', '.join(ctx.settings.decision_teams)} can record decisions.",
        )


# Import modules so their handlers register themselves.
from . import dependencies, incidents, teams, tickets  # noqa: E402,F401
