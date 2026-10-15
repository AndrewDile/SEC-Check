"""Mock Core API.

Implements API Spec.txt / Data Schema & Examples.txt in memory so the Web App
can run and be tested before the real Core API exists. Every request is
validated against contracts/core_api.json, so if the Web App sends something
the Core spec does not allow, the mock rejects it the way the real API should.

Behaviour beyond the spec (all listed in initial_implementation.md):
  - Method "LIST" on /incidents, /tickets and /dependencies (gap G-5).
  - Ticket_number is required for /tickets EDIT (gap G-4); EDIT returns "Edited".
  - Responses include "Timestamp" for incidents and tickets, and tickets include
    "Ticket_Claim" and "Claimed_By" (gaps G-3, G-12) so the UI can show them.
  - Accepts "Dependency" or "Dependency_Name" on /incidents (gap G-3).
  - /tickets GET also accepts a version id (Ticket_type_strong, e.g. 123_2_1) and
    returns that exact version (the fix proposed for gap G-7). Set
    version_lookup=False to behave like a Core API without it.

Two kinds of caller (see mock_core/gateway.py):
  - The Web App marks its calls with the header X-SECheck-Origin: webapp. Those
    are always handled here, in memory (this is where data is "stored").
  - Anyone else (API test clients) is treated as an external caller. When a
    Web App URL is configured (gateway mode, the default under run.py), their
    Core API calls are validated against the Core contract, then forwarded to
    the Web App as Web App API requests, and the answer is converted back to
    the Core format. Without a Web App URL, they are handled here directly.
  /reset is always handled here.

Run on its own:  python -m mock_core  [--port 8001] [--webapp-url http://127.0.0.1:8000]
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from secheck_web.core_client import ORIGIN_HEADER, ORIGIN_WEBAPP
from secheck_web.validation import Spec, parse_datetime, utc_now
from secheck_web.web import Response, json_response

from .gateway import CoreError, WebAppGateway

DEFAULT_CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "core_api.json"
EXTENSION_METHODS = {"LIST"}
LOCAL_ONLY_PATHS = {"/reset"}
WEAK_ID = re.compile(r"^[0-9A-Za-z-]+_[0-9]+$")
STRONG_ID = re.compile(r"^([0-9A-Za-z-]+_[0-9]+)_([0-9]+)$")
FUTURE_TOLERANCE = timedelta(seconds=5)


class MockCore:
    def __init__(
        self,
        teams: Optional[List[str]] = None,
        contract: Path = DEFAULT_CONTRACT,
        log_requests: bool = False,
        webapp_url: Optional[str] = None,
        gateway_user: str = "core-gateway",
        gateway_timeout: float = 10.0,
        version_lookup: bool = True,
    ):
        self.spec = Spec.load(contract)
        self.teams = list(teams or ["LEGAL", "CYBER1", "CYBER2"])
        self.log_requests = log_requests
        self.gateway_user = gateway_user
        self.gateway_timeout = gateway_timeout
        self.version_lookup = version_lookup  # /tickets GET by Ticket_type_strong (gap G-7)
        self.webapp_url = webapp_url  # set -> gateway mode for external callers
        self.lock = threading.RLock()
        self.request_log: List[Dict[str, Any]] = []  # every request received: path, body, origin
        self.forward_log: List[Dict[str, Any]] = []  # every Web App request the gateway generated
        self.routes = {
            "/incidents": self._incidents,
            "/tickets": self._tickets,
            "/notifier": self._notifier,
            "/logs": self._logs,
            "/dependencies": self._dependencies,
            "/dependancies": self._dependencies,  # spelling used in the operations list (gap G-2)
            "/reset": self._reset,
        }
        self.wipe()

    def wipe(self) -> None:
        with self.lock:
            self.incidents: Dict[str, Dict[str, Any]] = {}
            self.tickets: Dict[str, Dict[str, Any]] = {}       # weak id -> ticket
            self.ticket_counter: Dict[str, int] = {}
            self.log: Dict[str, List[str]] = {}                # incident id -> strong ids in order
            self.dependencies: List[str] = []

    # ------------------------------------------------------------------ http entry
    def handle(self, method: str, target: str, headers: Any, body: bytes) -> Response:
        path = urlsplit(target).path.rstrip("/") or "/"
        if method == "GET" and path == "/openapi.json":
            return json_response(200, self.spec.doc)
        if method != "POST":
            return json_response(405, {"Error": "INVALID_DATA", "Message": "The Core API only accepts POST."})
        handler = self.routes.get(path)
        if handler is None:
            return json_response(404, {"Error": "INVALID_DATA", "Message": f"Unknown Core API path {path}."})
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (ValueError, UnicodeDecodeError):
            return json_response(400, {"Error": "INVALID_DATA", "Message": "Request body is not valid JSON."})
        if not isinstance(payload, dict):
            return json_response(400, {"Error": "INVALID_DATA", "Message": "Request body must be a JSON object."})
        origin = (headers.get(ORIGIN_HEADER) if headers else None) or "external"
        forward = bool(self.webapp_url) and origin != ORIGIN_WEBAPP and path not in LOCAL_ONLY_PATHS
        with self.lock:
            self.request_log.append({"path": path, "body": payload, "origin": origin, "forwarded": forward})
        try:
            self._validate_contract(path, payload)
            if forward:
                # Outside the lock: the Web App will call back into this mock while we wait.
                status, out = 200, self._gateway().handle(path, payload)
            else:
                with self.lock:
                    status, out = 200, handler(payload)
        except CoreError as exc:
            status, out = 400, {"Error": exc.error, "Message": exc.message}
        return json_response(status, out)

    def _gateway(self) -> WebAppGateway:
        def record(entry: Dict[str, Any]) -> None:
            with self.lock:
                self.forward_log.append(entry)
        return WebAppGateway(self.webapp_url, self.gateway_user, self.gateway_timeout, on_forward=record)

    def _validate_contract(self, path: str, payload: Dict[str, Any]) -> None:
        method = payload.get("Method", payload.get("method"))
        if method in EXTENSION_METHODS:
            return  # proposed operations are not in the contract yet
        spec_path = "/dependencies" if path == "/dependancies" else path
        item = self.spec.doc.get("paths", {}).get(spec_path, {})
        op = item.get("post")
        if not op:
            return
        schema = self.spec.request_schema(op)
        errors = self.spec.validate(payload, schema) if schema else []
        if errors:
            raise CoreError("INVALID_DATA", "; ".join(errors[:5]) + ".")
        if "Timestamp" in payload:
            ts = parse_datetime(payload["Timestamp"])
            if ts and ts > datetime.now(timezone.utc) + FUTURE_TOLERANCE:
                raise CoreError("INVALID_DATA", "Timestamp cannot be set in the future.")

    # ------------------------------------------------------------------ helpers
    def _incident(self, incident_id: Any) -> Dict[str, Any]:
        rec = self.incidents.get(str(incident_id))
        if rec is None:
            raise CoreError("UUID_DNE", "The specified Incident_ID does not exist.")
        return rec

    def _check_teams(self, teams: Any, field: str) -> List[str]:
        if not isinstance(teams, list) or any(t not in self.teams for t in teams):
            raise CoreError("INVALID_DATA", f"{field} invalid data type")
        return teams

    @staticmethod
    def _incident_view(rec: Dict[str, Any], status: Optional[str] = None) -> Dict[str, Any]:
        out = {k: rec[k] for k in ("Incident_ID", "Description", "Materiality", "Severity", "Urgency", "Timestamp")}
        if rec.get("Dependency"):
            out["Dependency"] = rec["Dependency"]
        if status:
            out["Status"] = status
        return out

    def _ticket_view(self, ticket: Dict[str, Any], status: str, version: Optional[int] = None) -> Dict[str, Any]:
        inc = self.incidents[ticket["Incident_ID"]]
        latest = ticket["versions"][-1 if version is None else version - 1]  # "latest" = the version shown
        return {
            "Incident_ID": ticket["Incident_ID"],
            "Ticket_ID": latest["Ticket_ID"],
            "Status": status,
            "UUID_Description": inc["Description"],
            "Ticket_Description": latest["Ticket_Description"],
            "Materiality_type": inc["Materiality"],
            "uuid_severity": inc["Severity"],
            "uuid_urgency": inc["Urgency"],
            "ticket_severity": latest["ticket_severity"],
            "ticket_urgency": latest["ticket_urgency"],
            "Ticket_Claim": "CLAIMED" if ticket["claimed_by"] else "UNCLAIMED",
            "Claimed_By": ticket["claimed_by"],
            "Team_List": latest["Team_List"],
            "Timestamp": latest["Timestamp"],
        }

    def _ticket(self, incident_id: str, number: Any) -> Dict[str, Any]:
        if not isinstance(number, str) or not WEAK_ID.match(number):
            raise CoreError("INVALID_DATA", "Ticket_number must be in Ticket_type_weak format, e.g. 102356304331_1.")
        ticket = self.tickets.get(number)
        if ticket is None or (incident_id and ticket["Incident_ID"] != str(incident_id)):
            raise CoreError("UUID_DNE", "The specified ticket does not exist.")
        return ticket

    def _ticket_version(self, incident_id: str, ticket_id: str) -> Dict[str, Any]:
        """GET by Ticket_type_strong: one specific version (gap G-7 proposal)."""
        match = STRONG_ID.match(ticket_id)
        ticket = self._ticket(incident_id, match.group(1))
        version = int(match.group(2))
        if not 1 <= version <= len(ticket["versions"]):
            raise CoreError("UUID_DNE", "The specified ticket version does not exist.")
        return self._ticket_view(ticket, "Displayed", version)

    # ------------------------------------------------------------------ /incidents
    def _incidents(self, b: Dict[str, Any]) -> Dict[str, Any]:
        method = b.get("Method")
        if method == "LIST":
            return {"Incidents": [self._incident_view(r) for r in self.incidents.values()], "Status": "Listed"}
        incident_id = str(b.get("Incident_ID", ""))
        if method == "NEW":
            if incident_id in self.incidents:
                raise CoreError("UUID_EXISTS", "The provided Incident_ID already exists in the system.")
            rec = {
                "Incident_ID": incident_id,
                "Timestamp": b["Timestamp"],
                "Description": b["Description"],
                "Dependency": b.get("Dependency") or b.get("Dependency_Name") or None,
                "Materiality": b.get("Materiality", "UNDECIDED"),
                "Severity": b.get("Severity", "UNDECIDED"),
                "Urgency": b.get("Urgency", "UNDECIDED"),
            }
            self.incidents[incident_id] = rec
            self.log[incident_id] = []
            return self._incident_view(rec, "Created")
        rec = self._incident(incident_id)
        if method == "EDIT":
            for key in ("Description", "Materiality", "Severity", "Urgency"):
                if key in b:
                    rec[key] = b[key]
            for key in ("Dependency", "Dependency_Name"):
                if key in b:
                    rec["Dependency"] = b[key] or None
            return self._incident_view(rec, "Edited")
        return self._incident_view(rec, "Data Fetched")  # GET

    # ------------------------------------------------------------------ /tickets
    def _tickets(self, b: Dict[str, Any]) -> Dict[str, Any]:
        method = b.get("Method")
        if method == "LIST":
            return {"Tickets": self._queue(b.get("Team"), b.get("Ticket_Claim")), "Status": "Listed"}
        incident_id = str(b.get("Incident_ID", ""))
        self._incident(incident_id)
        if "Team_list" in b:
            self._check_teams(b["Team_list"], "Team_list")
        if method in ("NEW", "EDIT") and not b.get("Description"):
            raise CoreError("INVALID_DATA", "Description is required when Method is NEW or EDIT.")
        if method == "NEW":
            n = self.ticket_counter.get(incident_id, 0) + 1
            self.ticket_counter[incident_id] = n
            weak = f"{incident_id}_{n}"
            version = {
                "Ticket_ID": f"{weak}_1",
                "Timestamp": b["Timestamp"],
                "Ticket_Description": b["Description"],
                "ticket_severity": b.get("Ticket_severity", "UNDECIDED"),
                "ticket_urgency": b.get("Ticket_urgency", "UNDECIDED"),
                "Team_List": list(b.get("Team_list") or []),
            }
            ticket = {"Incident_ID": incident_id, "weak": weak, "versions": [version], "claimed_by": None, "notified": []}
            self.tickets[weak] = ticket
            self.log[incident_id].append(version["Ticket_ID"])
            return self._ticket_view(ticket, "Logged")
        if "Ticket_number" not in b:
            raise CoreError("INVALID_DATA", f"Ticket_number is required when Method is {method}.")
        if method == "GET" and self.version_lookup and isinstance(b["Ticket_number"], str) \
                and STRONG_ID.match(b["Ticket_number"]):
            return self._ticket_version(incident_id, b["Ticket_number"])
        ticket = self._ticket(incident_id, b["Ticket_number"])
        if method == "EDIT":
            prev = ticket["versions"][-1]
            version = dict(prev)
            version.update({
                "Ticket_ID": f"{ticket['weak']}_{len(ticket['versions']) + 1}",
                "Timestamp": b["Timestamp"],
                "Ticket_Description": b["Description"],
            })
            if "Ticket_severity" in b:
                version["ticket_severity"] = b["Ticket_severity"]
            if "Ticket_urgency" in b:
                version["ticket_urgency"] = b["Ticket_urgency"]
            if "Team_list" in b:
                version["Team_List"] = list(b["Team_list"])
            ticket["versions"].append(version)
            self.log[incident_id].append(version["Ticket_ID"])
            return self._ticket_view(ticket, "Edited")
        return self._ticket_view(ticket, "Displayed")  # GET

    def _queue(self, team: Optional[str], claim: Optional[str]) -> List[Dict[str, Any]]:
        items = []
        for ticket in self.tickets.values():
            latest = ticket["versions"][-1]
            notified_teams = [t for t, _ in ticket["notified"]]
            if team and team not in latest["Team_List"] and team not in notified_teams:
                continue
            state = "CLAIMED" if ticket["claimed_by"] else "UNCLAIMED"
            if claim and claim != state:
                continue
            notified_at = [ts for t, ts in ticket["notified"] if not team or t == team]
            items.append({
                "Ticket_number": ticket["weak"],
                "Incident_ID": ticket["Incident_ID"],
                "Ticket_Description": latest["Ticket_Description"],
                "ticket_severity": latest["ticket_severity"],
                "ticket_urgency": latest["ticket_urgency"],
                "Ticket_Claim": state,
                "Claimed_By": ticket["claimed_by"],
                "Notified_At": notified_at[-1] if notified_at else None,
                "Filing_Deadline": None,
            })
        return items

    # ------------------------------------------------------------------ /notifier
    def _notifier(self, b: Dict[str, Any]) -> Dict[str, Any]:
        teams = b.get("Team_Names")
        if not isinstance(teams, list) or not teams:
            raise CoreError("INVALID_DATA", "Team_Names invalid data type")
        self._check_teams(teams, "Team_Names")
        ticket = self._ticket("", b.get("Ticket_Number"))
        if b["Method"] == "CLAIM":
            if len(teams) != 1:
                raise CoreError("INVALID_DATA", "Only one team can claim a ticket.")
            if ticket["claimed_by"]:
                raise CoreError("INVALID_DATA", f"Ticket already claimed by {ticket['claimed_by']}.")
            ticket["claimed_by"] = teams[0]
            status = "Claimed ticket"
        else:
            now = utc_now()
            ticket["notified"].extend((team, now) for team in teams)
            status = "Notified team"
        incident_id = ticket["Incident_ID"]
        return {
            "UUID": int(incident_id) if incident_id.isdigit() else incident_id,  # spec says integer
            "Ticket_Number": ticket["weak"],
            "Status": status,
        }

    # ------------------------------------------------------------------ /logs
    def _logs(self, b: Dict[str, Any]) -> Dict[str, Any]:
        rec = self._incident(b.get("Incident_ID"))
        return {
            "Incident_ID": rec["Incident_ID"],
            "Description": rec["Description"],
            "Materiality_type": rec["Materiality"],
            "Severity": rec["Severity"],
            "Urgency": rec["Urgency"],
            "Ticket_ID_List": list(self.log[rec["Incident_ID"]]),
            "Status": "Log Retrieved",
        }

    # ------------------------------------------------------------------ /dependencies
    def _dependencies(self, b: Dict[str, Any]) -> Dict[str, Any]:
        method, name = b.get("method"), b.get("dp_name")
        if method == "LIST":
            return {"Dependencies": sorted(self.dependencies), "status": "Listed"}
        if not isinstance(name, str) or not name.strip():
            raise CoreError("INVALID_DATA", "dp_name must be a non-empty string.")
        if method == "NEW":
            if name in self.dependencies:
                raise CoreError("DP_EXISTS", "The dependency name already exists in the system.")
            self.dependencies.append(name)
            return {"dp_name": name, "status": "Added"}
        if method == "MATCH":
            return {"dp_name": name, "status": "Exists" if name in self.dependencies else "Does not Exist"}
        if name not in self.dependencies:
            raise CoreError("DP_DNE", "The dependency name does not exist in the system.")
        self.dependencies.remove(name)
        return {"dp_name": name, "status": "Removed"}

    # ------------------------------------------------------------------ /reset
    def _reset(self, b: Dict[str, Any]) -> Dict[str, Any]:
        self.wipe()
        return {"status": "DB Wiped"}
