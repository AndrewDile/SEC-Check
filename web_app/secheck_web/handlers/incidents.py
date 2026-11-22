"""Incident intake, info, edit, decision, log and 8-K view (Web App API 4.1-4.5, 4.13, 4.14)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from .. import audit
from ..core_client import weak_ticket_id
from ..errors import WebAppError, invalid, tracked
from ..validation import format_utc, parse_datetime
from . import Context, Request, operation, require_can_decide

DECISION_FIELDS = ("Materiality", "Severity", "Urgency")
FUTURE_TOLERANCE = timedelta(seconds=5)  # allow small clock skew between browser and server


def ensure_dependency_exists(ctx: Context, name: str, steps: List[str]) -> None:
    result = ctx.core.dp_match(steps, name)
    if not ctx.core.dp_exists(result):
        raise WebAppError(
            "DP_DNE", "The dependency name does not exist in the system.", core_path="/dependencies"
        )


def discovery_timestamp(ctx: Context, value: Any) -> str:
    if value in (None, ""):
        return ctx.now()
    parsed = parse_datetime(value)
    if parsed is None:
        raise invalid("Timestamp must be an RFC 3339 date-time, e.g. 2026-09-25T20:00:00Z.")
    if parsed > datetime.now(timezone.utc) + FUTURE_TOLERANCE:
        raise invalid("Timestamp cannot be set in the future.")
    return format_utc(parsed)


@operation("createIncident")
def create_incident(ctx: Context, req: Request) -> Dict[str, Any]:
    body = req.json
    steps: List[str] = []
    with tracked(steps):
        dependency = body.get("Dependency_Name") or None
        if dependency:
            ensure_dependency_exists(ctx, dependency, steps)
        timestamp = discovery_timestamp(ctx, body.get("Timestamp"))
        generated = "Incident_ID" not in body
        for attempt in range(5):
            incident_id = body.get("Incident_ID") or ctx.new_incident_id()
            try:
                created = ctx.core.incident_new(
                    steps,
                    incident_id=incident_id,
                    description=body["Description"],
                    timestamp=timestamp,
                    dependency=dependency,
                    materiality=body.get("Materiality", "UNDECIDED"),
                    severity=body.get("Severity", "UNDECIDED"),
                    urgency=body.get("Urgency", "UNDECIDED"),
                )
                break
            except WebAppError as exc:
                if generated and exc.error == "UUID_EXISTS" and attempt < 4:
                    continue  # generated id collided; try another
                raise
        intake = ctx.core.ticket_new(
            steps, incident_id=incident_id, description=audit.intake_text(req.user.name)
        )
    out = dict(created)
    if dependency:
        out.setdefault("Dependency_Name", dependency)
    out["Intake_Ticket_ID"] = intake.get("Ticket_ID")
    return out


@operation("listIncidents")
def list_incidents(ctx: Context, req: Request) -> Dict[str, Any]:
    items = ctx.core.incident_list(None)
    for key in DECISION_FIELDS:
        wanted = req.query.get(key)
        if wanted:
            items = [i for i in items if i.get(key) == wanted]
    page = req.query.get("page", 1)
    size = req.query.get("page_size", 25)
    start = (page - 1) * size
    return {
        "Incidents": items[start : start + size],
        "page": page,
        "page_size": size,
        "total": len(items),
    }


@operation("getIncident")
def get_incident(ctx: Context, req: Request) -> Dict[str, Any]:
    return ctx.core.incident_get(None, req.path_params["Incident_ID"])


@operation("editIncident")
def edit_incident(ctx: Context, req: Request) -> Dict[str, Any]:
    incident_id = req.path_params["Incident_ID"]
    body = req.json
    steps: List[str] = []
    with tracked(steps):
        current = ctx.core.incident_get(steps, incident_id)
        if "Dependency_Name" in body:
            dependency = body["Dependency_Name"] or ""  # "" clears the dependency
            if dependency:
                ensure_dependency_exists(ctx, dependency, steps)
        else:
            dependency = current.get("Dependency_Name")
        edited = ctx.core.incident_edit(
            steps,
            incident_id=incident_id,
            description=body.get("Description", current.get("Description", "")),
            dependency=dependency,
        )
        ticket = ctx.core.ticket_new(
            steps,
            incident_id=incident_id,
            description=audit.edit_text(sorted(body.keys()), req.user.name),
        )
    out = dict(edited)
    out["Audit_Ticket_ID"] = ticket.get("Ticket_ID")
    return out


@operation("recordDecision")
def record_decision(ctx: Context, req: Request) -> Dict[str, Any]:
    incident_id = req.path_params["Incident_ID"]
    body = req.json
    if not any(k in body for k in DECISION_FIELDS):
        raise invalid("At least one of Materiality, Severity or Urgency is required.")
    require_can_decide(ctx, req.user)
    steps: List[str] = []
    with tracked(steps):
        current = ctx.core.incident_get(steps, incident_id)
        new = {k: body.get(k, current.get(k, "UNDECIDED")) for k in DECISION_FIELDS}
        edited = ctx.core.incident_edit(
            steps,
            incident_id=incident_id,
            description=current.get("Description", ""),
            materiality=new["Materiality"],
            severity=new["Severity"],
            urgency=new["Urgency"],
            note=body["Rationale"],
        )
        determined_at = ctx.now()
        ticket = ctx.core.ticket_new(
            steps,
            incident_id=incident_id,
            description=audit.decision_text(
                req.user.name,
                new["Materiality"],
                new["Severity"],
                new["Urgency"],
                body["Rationale"],
            ),
            severity=new["Severity"],
            urgency=new["Urgency"],
            timestamp=determined_at,
        )
        notified: List[str] = []
        if body.get("Materiality") == "MATERIAL" and current.get("Materiality") != "MATERIAL":
            teams = ctx.core.team_list(steps)  # every team is told about a material incident
            if teams:
                ctx.core.notify(
                    steps,
                    team_names=teams,
                    ticket_number=weak_ticket_id(ticket["Ticket_ID"]),
                )
            notified = list(teams)
    return {
        "Incident_ID": incident_id,
        "Status": "Decision Recorded",
        **new,
        "Decision_Ticket_ID": ticket.get("Ticket_ID"),
        "Determined_At": determined_at,
        "Notified_Teams": notified,
        "Filing_Deadline": edited.get("Filing_Deadline"),
    }


@operation("getIncidentLog")
def get_incident_log(ctx: Context, req: Request) -> Dict[str, Any]:
    return ctx.core.logs(None, req.path_params["Incident_ID"])


@operation("getForm8kView")
def get_form_8k_view(ctx: Context, req: Request) -> Dict[str, Any]:
    return ctx.core.form_8k(None, req.path_params["Incident_ID"])
