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


def _present(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop unknown (None) values: the Web App spec types these fields as non-nullable strings."""
    return {k: v for k, v in d.items() if v is not None}


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
        ctx.core.incident_edit(
            steps,
            incident_id=incident_id,
            description=current.get("Description", ""),
            materiality=new["Materiality"],
            severity=new["Severity"],
            urgency=new["Urgency"],
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
            ctx.core.notify(
                steps,
                team_names=ctx.settings.teams,
                ticket_number=weak_ticket_id(ticket["Ticket_ID"]),
            )
            notified = list(ctx.settings.teams)
    return {
        "Incident_ID": incident_id,
        "Status": "Decision Recorded",
        **new,
        "Decision_Ticket_ID": ticket.get("Ticket_ID"),
        "Determined_At": determined_at,
        "Notified_Teams": notified,
        "Filing_Deadline": None,  # not exposed by the Core API yet (gap G-8)
    }


@operation("getIncidentLog")
def get_incident_log(ctx: Context, req: Request) -> Dict[str, Any]:
    return ctx.core.logs(None, req.path_params["Incident_ID"])


@operation("getForm8kView")
def get_form_8k_view(ctx: Context, req: Request) -> Dict[str, Any]:
    incident_id = req.path_params["Incident_ID"]
    incident = ctx.core.incident_get(None, incident_id)
    if incident.get("Materiality") != "MATERIAL":
        raise invalid("Form 8-K view is only available for incidents marked MATERIAL.")
    log = ctx.core.logs(None, incident_id)
    ticket_ids = log["Ticket_ID_List"]
    numbers: List[str] = []
    for tid in ticket_ids:
        weak = weak_ticket_id(tid)
        if weak not in numbers:
            numbers.append(weak)
    tickets = [ctx.core.ticket_get(None, incident_id=incident_id, ticket_number=n) for n in numbers]

    # Ticket timestamps are not in the Core spec response (mock adds them); order by them when present.
    tickets_by_time = sorted(tickets, key=lambda t: t.get("Timestamp") or "")
    content = [t for t in tickets if not audit.is_audit(t.get("Ticket_Description"))]
    decisions = [(t, audit.parse_decision(t.get("Ticket_Description"))) for t in tickets_by_time]
    decisions = [(t, d) for t, d in decisions if d]
    material = [(t, d) for t, d in decisions if d["Materiality"] == "MATERIAL"]
    determined_at = material[-1][0].get("Timestamp") if material else None

    teams: List[str] = []
    for t in tickets:
        for team in t.get("Team_List") or []:
            if team not in teams:
                teams.append(team)

    nature = "\n\n".join(
        [incident.get("Description", "")] + [t.get("Ticket_Description", "") for t in content]
    ).strip()
    return {
        "Incident_ID": incident_id,
        "Status": "8-K View Assembled",
        "Item_1_05": {
            "Nature": nature,
            "Scope": _present(
                {
                    "Severity": incident.get("Severity"),
                    "Dependency_Name": incident.get("Dependency_Name"),
                    "Teams_Involved": teams,
                }
            ),
            "Timing": _present(
                {
                    "Discovered_At": incident.get("Timestamp"),
                    "Determined_At": determined_at,
                    "Events": [
                        _present(
                            {
                                "Ticket_ID": t.get("Ticket_ID"),
                                "Timestamp": t.get("Timestamp"),
                                "Summary": (t.get("Ticket_Description") or "")[:300],
                            }
                        )
                        for t in tickets_by_time
                    ],
                }
            ),
            "Material_Impact": "\n\n".join(d["Rationale"] for _, d in material),
        },
        "Filing": {
            **_present({"Determined_At": determined_at}),
            "Filing_Deadline": None,
        },  # deadline: gap G-8
        "Source_Tickets": ticket_ids,
    }
