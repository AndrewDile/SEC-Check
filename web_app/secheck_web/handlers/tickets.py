"""Tickets, claim, notify and team queue (Web App API 4.6-4.12)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .. import audit
from ..core_client import weak_ticket_id
from ..errors import WebAppError, invalid, tracked
from . import (
    Context,
    Request,
    extension,
    operation,
    require_known_teams,
    require_ticket_of_incident,
)


@operation("listIncidentTickets")
def list_incident_tickets(ctx: Context, req: Request) -> Dict[str, Any]:
    incident_id = req.path_params["Incident_ID"]
    log = ctx.core.logs(None, incident_id)
    out: Dict[str, Any] = {"Incident_ID": incident_id, "Ticket_ID_List": log["Ticket_ID_List"]}
    if req.query.get("expand"):
        numbers: List[str] = []
        for tid in log["Ticket_ID_List"]:
            weak = weak_ticket_id(tid)
            if weak not in numbers:
                numbers.append(weak)
        out["Tickets"] = [
            ctx.core.ticket_get(None, incident_id=incident_id, ticket_number=n) for n in numbers
        ]
    return out


@operation("createTicket")
def create_ticket(ctx: Context, req: Request) -> Dict[str, Any]:
    incident_id = req.path_params["Incident_ID"]
    body = req.json
    teams = body.get("Team_list") or []
    require_known_teams(ctx, teams, "Team_list")
    steps: List[str] = []
    with tracked(steps):
        ticket = ctx.core.ticket_new(
            steps,
            incident_id=incident_id,
            description=body["Description"],
            severity=body.get("Ticket_severity"),
            urgency=body.get("Ticket_urgency"),
            team_list=teams,
        )
        notified: List[str] = []
        if body.get("Notify", True) and teams:
            ctx.core.notify(
                steps, team_names=teams, ticket_number=weak_ticket_id(ticket["Ticket_ID"])
            )
            notified = list(teams)
    out = dict(ticket)
    out["Notified_Teams"] = notified
    return out


@operation("getTicket")
def get_ticket(ctx: Context, req: Request) -> Dict[str, Any]:
    incident_id = req.path_params["Incident_ID"]
    number = req.path_params["Ticket_number"]
    require_ticket_of_incident(incident_id, number)
    return ctx.core.ticket_get(None, incident_id=incident_id, ticket_number=number)


@operation("editTicket")
def edit_ticket(ctx: Context, req: Request) -> Dict[str, Any]:
    incident_id = req.path_params["Incident_ID"]
    number = req.path_params["Ticket_number"]
    require_ticket_of_incident(incident_id, number)
    body = req.json
    if "Team_list" in body:
        require_known_teams(ctx, body["Team_list"], "Team_list")
    return ctx.core.ticket_edit(
        None,
        incident_id=incident_id,
        ticket_number=number,
        description=body["Description"],
        severity=body.get("Ticket_severity"),
        urgency=body.get("Ticket_urgency"),
        team_list=body.get("Team_list"),
    )


@operation("claimTicket")
def claim_ticket(ctx: Context, req: Request) -> Dict[str, Any]:
    team = req.json["Team_Name"]
    require_known_teams(ctx, [team], "Team_Name")
    if team not in req.user.teams:
        raise WebAppError("FORBIDDEN", f"You are not a member of team {team}.")
    return ctx.core.claim(None, team_name=team, ticket_number=req.path_params["Ticket_number"])


@operation("notifyTeams")
def notify_teams(ctx: Context, req: Request) -> Dict[str, Any]:
    teams = req.json["Team_Names"]
    require_known_teams(ctx, teams, "Team_Names")
    return ctx.core.notify(None, team_names=teams, ticket_number=req.path_params["Ticket_number"])


@operation("getQueue")
def get_queue(ctx: Context, req: Request) -> Dict[str, Any]:
    team = req.query.get("team")
    if not team:
        raise invalid("team is required.")
    require_known_teams(ctx, [team], "team")
    claim = req.query.get("claim") or "UNCLAIMED"
    return {
        "Team": team,
        "Claim": claim,
        "Tickets": ctx.core.ticket_list(None, team=team, claim=claim),
    }


# ---------------------------------------------------------------- full log with details
ENTRY_FIELDS = ("Timestamp", "Ticket_Description", "ticket_severity", "ticket_urgency", "Team_List")


def _entry_type(description: Optional[str]) -> str:
    text = description or ""
    for prefix in audit.PREFIXES:
        if text.startswith(prefix + ":") or text.startswith(prefix + " by "):
            return prefix
    return "TICKET"


@extension(
    "GET",
    "/incidents/{Incident_ID}/log/entries",
    note="PROPOSED: every log entry (ticket version) with its details; uses Core GET by version id (gap G-7)",
)
def log_entries(ctx: Context, req: Request) -> Dict[str, Any]:
    """Every entry in the incident log, oldest first, with what that version recorded.

    For each Ticket_type_strong id in /logs, the Web App asks the Core API for that
    exact version. A Core API that only supports GET by Ticket_type_weak (the current
    spec, gap G-7) answers with the latest version instead; then entries that are the
    latest version are still shown in full and older ones get Details_Available: false.
    """
    incident_id = req.path_params["Incident_ID"]
    if not re.fullmatch(r"[0-9]+", incident_id):
        raise invalid("Incident_ID has an invalid format.")
    log = ctx.core.logs(None, incident_id)
    latest: Dict[str, Dict[str, Any]] = {}
    entries: List[Dict[str, Any]] = []
    for ticket_id in log["Ticket_ID_List"]:
        number = weak_ticket_id(ticket_id)
        version = ticket_id.rsplit("_", 1)[-1]
        entry: Dict[str, Any] = {
            "Ticket_ID": ticket_id,
            "Ticket_number": number,
            "Version": int(version) if version.isdigit() else None,
        }
        data: Optional[Dict[str, Any]] = None
        try:
            data = ctx.core.ticket_get_version(None, incident_id=incident_id, ticket_id=ticket_id)
        except WebAppError as exc:
            if exc.error not in ("INVALID_DATA", "UUID_DNE"):
                raise
        if data is None or data.get("Ticket_ID") != ticket_id:
            if number not in latest:
                latest[number] = ctx.core.ticket_get(
                    None, incident_id=incident_id, ticket_number=number
                )
            data = latest[number] if latest[number].get("Ticket_ID") == ticket_id else None
        if data is None:
            entry["Details_Available"] = False
        else:
            entry["Details_Available"] = True
            entry.update({k: data[k] for k in ENTRY_FIELDS if data.get(k) is not None})
            entry["Entry_Type"] = _entry_type(data.get("Ticket_Description"))
        entries.append(entry)
    return {"Incident_ID": incident_id, "Entries": entries, "Status": "Log Entries Retrieved"}
