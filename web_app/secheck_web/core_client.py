"""Adapter for the Core API.

THIS IS THE ONLY MODULE THAT KNOWS CORE API PATHS AND FIELD NAMES.
When API Spec.txt changes, update this file (and run tools/sync_contracts.py so
the mock Core API validates against the new contract). Handlers call the
methods below and work with Web App field names only.

Every call appends "<path> <Method>" to the caller's `steps` list on success,
which feeds Completed_Steps on partial failures (Web App API section 3.4).

Calls marked EXTENSION use Method "LIST", which the Core API does not define
yet (gap G-5). The mock Core API supports them; a real Core API will reject
them until it adds list operations.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .errors import WebAppError, status_for
from .validation import utc_now

# Core API paths (API Spec.txt). Note the operations list spells
# "/dependancies"; the OpenAPI block uses "/dependencies" (gap G-2).
PATH_INCIDENTS = "/incidents"
PATH_TICKETS = "/tickets"
PATH_NOTIFIER = "/notifier"
PATH_LOGS = "/logs"
PATH_DEPENDENCIES = "/dependencies"

# Every call the Web App makes carries this header so a Core API that forwards
# external calls to the Web App (gateway mode) does not forward these back,
# which would loop forever. See "Web Dev/mock_core/gateway.py".
ORIGIN_HEADER = "X-SECheck-Origin"
ORIGIN_WEBAPP = "webapp"


def weak_ticket_id(ticket_id: str) -> str:
    """Ticket_type_strong '<id>_<n>_<v>' -> Ticket_type_weak '<id>_<n>'."""
    parts = str(ticket_id).split("_")
    return "_".join(parts[:2]) if len(parts) >= 3 else str(ticket_id)


def normalize_ticket_id_list(value: Any) -> List[str]:
    """Core example returns ["a, b, c"] (gap G-9); return one id per element."""
    out: List[str] = []
    for item in value or []:
        out.extend(part.strip() for part in str(item).split(",") if part.strip())
    return out


class CoreClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        use_system_proxy: bool = False,
        clock: Callable[[], str] = utc_now,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.clock = clock
        handlers = [] if use_system_proxy else [urllib.request.ProxyHandler({})]
        self._opener = urllib.request.build_opener(*handlers)
        # Optional observers: fn(path, request_body, status, response_body)
        self.observers: List[Callable[[str, Dict[str, Any], int, Any], None]] = []

    # ------------------------------------------------------------------ transport
    def _post(
        self, path: str, body: Dict[str, Any], steps: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                ORIGIN_HEADER: ORIGIN_WEBAPP,
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except (socket.timeout, TimeoutError):
            raise WebAppError("TIMEOUT", "The Core API did not respond in time.", core_path=path)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise WebAppError(
                    "TIMEOUT", "The Core API did not respond in time.", core_path=path
                )
            raise WebAppError(
                "UPSTREAM_UNAVAILABLE",
                f"Cannot reach the Core API at {self.base_url} ({exc.reason}).",
                core_path=path,
            )
        except OSError as exc:
            raise WebAppError(
                "UPSTREAM_UNAVAILABLE", f"Cannot reach the Core API: {exc}", core_path=path
            )

        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            payload = None
        for observer in self.observers:
            observer(path, body, status, payload)
        if payload is None:
            raise WebAppError(
                "UPSTREAM_UNAVAILABLE",
                f"Core API returned a non-JSON response (HTTP {status}).",
                core_path=path,
            )
        if status == 200:
            if steps is not None:
                steps.append(f"{path} {body.get('Method') or body.get('method')}")
            return payload
        if isinstance(payload, dict) and "Error" in payload:
            error = str(payload["Error"])
            raise WebAppError(
                error, str(payload.get("Message", "")), status=status_for(error), core_path=path
            )
        raise WebAppError(
            "UPSTREAM_UNAVAILABLE",
            f"Core API returned HTTP {status} without an error body.",
            core_path=path,
        )

    # ------------------------------------------------------------------ incidents
    @staticmethod
    def _incident_out(data: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(data)
        if "Incident_ID" in out:
            out["Incident_ID"] = str(out["Incident_ID"])
        # Core OpenAPI calls it "Dependency"; Web App uses "Dependency_Name" (gap G-3)
        if "Dependency" in out:
            dep = out.pop("Dependency")
            out.setdefault("Dependency_Name", dep)
        if not out.get("Dependency_Name"):
            out.pop("Dependency_Name", None)
        return out

    def incident_new(
        self,
        steps,
        *,
        incident_id,
        description,
        timestamp=None,
        dependency=None,
        materiality="UNDECIDED",
        severity="UNDECIDED",
        urgency="UNDECIDED",
    ) -> Dict[str, Any]:
        body = {
            "Incident_ID": incident_id,
            "Method": "NEW",
            "Timestamp": timestamp or self.clock(),
            "Description": description,
            "Materiality": materiality,
            "Severity": severity,
            "Urgency": urgency,
        }
        if dependency:
            body["Dependency"] = dependency
        return self._incident_out(self._post(PATH_INCIDENTS, body, steps))

    def incident_get(self, steps, incident_id: str) -> Dict[str, Any]:
        # Core requires Description on every Method, including GET (gap G-10).
        body = {
            "Incident_ID": incident_id,
            "Method": "GET",
            "Timestamp": self.clock(),
            "Description": "",
        }
        return self._incident_out(self._post(PATH_INCIDENTS, body, steps))

    def incident_edit(
        self,
        steps,
        *,
        incident_id,
        description,
        dependency=None,
        materiality=None,
        severity=None,
        urgency=None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "Incident_ID": incident_id,
            "Method": "EDIT",
            "Timestamp": self.clock(),
            "Description": description,
        }
        if dependency is not None:
            body["Dependency"] = dependency
        for key, value in (
            ("Materiality", materiality),
            ("Severity", severity),
            ("Urgency", urgency),
        ):
            if value is not None:
                body[key] = value
        return self._incident_out(self._post(PATH_INCIDENTS, body, steps))

    def incident_list(self, steps) -> List[Dict[str, Any]]:
        """EXTENSION (gap G-5)."""
        data = self._post(PATH_INCIDENTS, {"Method": "LIST", "Timestamp": self.clock()}, steps)
        return [self._incident_out(i) for i in data.get("Incidents", [])]

    # ------------------------------------------------------------------ tickets
    @staticmethod
    def _ticket_out(data: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(data)
        if "Incident_ID" in out:
            out["Incident_ID"] = str(out["Incident_ID"])
        return out

    def ticket_new(
        self,
        steps,
        *,
        incident_id,
        description,
        severity=None,
        urgency=None,
        team_list=None,
        timestamp=None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "Incident_ID": incident_id,
            "Method": "NEW",
            "Timestamp": timestamp or self.clock(),
            "Description": description,
            "Team_list": list(team_list or []),
        }
        if severity:
            body["Ticket_severity"] = severity
        if urgency:
            body["Ticket_urgency"] = urgency
        return self._ticket_out(self._post(PATH_TICKETS, body, steps))

    def ticket_get(self, steps, *, incident_id, ticket_number) -> Dict[str, Any]:
        body = {
            "Incident_ID": incident_id,
            "Method": "GET",
            "Timestamp": self.clock(),
            "Ticket_number": ticket_number,
        }
        return self._ticket_out(self._post(PATH_TICKETS, body, steps))

    def ticket_get_version(self, steps, *, incident_id, ticket_id) -> Dict[str, Any]:
        """One specific version, by Ticket_type_strong (e.g. 123_2_1).

        The Core spec only defines GET by Ticket_type_weak (latest version); asking
        for a version id is the fix proposed for gap G-7. Same request shape: the id
        goes in Ticket_number.
        """
        body = {
            "Incident_ID": incident_id,
            "Method": "GET",
            "Timestamp": self.clock(),
            "Ticket_number": ticket_id,
        }
        return self._ticket_out(self._post(PATH_TICKETS, body, steps))

    def ticket_edit(
        self,
        steps,
        *,
        incident_id,
        ticket_number,
        description,
        severity=None,
        urgency=None,
        team_list=None,
    ) -> Dict[str, Any]:
        # Core EDIT has no way to say which ticket; we send Ticket_number (gap G-4).
        body: Dict[str, Any] = {
            "Incident_ID": incident_id,
            "Method": "EDIT",
            "Timestamp": self.clock(),
            "Ticket_number": ticket_number,
            "Description": description,
        }
        if severity:
            body["Ticket_severity"] = severity
        if urgency:
            body["Ticket_urgency"] = urgency
        if team_list is not None:
            body["Team_list"] = list(team_list)
        return self._ticket_out(self._post(PATH_TICKETS, body, steps))

    def ticket_list(self, steps, *, team=None, claim=None) -> List[Dict[str, Any]]:
        """EXTENSION (gap G-5): tickets visible to a team, filtered by claim state."""
        body: Dict[str, Any] = {"Method": "LIST", "Timestamp": self.clock()}
        if team:
            body["Team"] = team
        if claim:
            body["Ticket_Claim"] = claim
        data = self._post(PATH_TICKETS, body, steps)
        return [self._ticket_out(t) for t in data.get("Tickets", [])]

    # ------------------------------------------------------------------ notifier
    @staticmethod
    def _notifier_out(data: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(data)
        if "UUID" in out:
            out["UUID"] = str(out["UUID"])  # Core example uses an integer (gap G-9)
        return out

    def notify(self, steps, *, team_names: List[str], ticket_number: str) -> Dict[str, Any]:
        body = {"Team_Names": list(team_names), "Method": "NOTIFY", "Ticket_Number": ticket_number}
        return self._notifier_out(self._post(PATH_NOTIFIER, body, steps))

    def claim(self, steps, *, team_name: str, ticket_number: str) -> Dict[str, Any]:
        body = {"Team_Names": [team_name], "Method": "CLAIM", "Ticket_Number": ticket_number}
        return self._notifier_out(self._post(PATH_NOTIFIER, body, steps))

    # ------------------------------------------------------------------ logs
    def logs(self, steps, incident_id: str) -> Dict[str, Any]:
        data = dict(
            self._post(PATH_LOGS, {"Incident_ID": incident_id, "Timestamp": self.clock()}, steps)
        )
        data["Incident_ID"] = str(data.get("Incident_ID", incident_id))
        data["Ticket_ID_List"] = normalize_ticket_id_list(data.get("Ticket_ID_List"))
        return data

    # ------------------------------------------------------------------ dependencies
    def dp_new(self, steps, dp_name: str) -> Dict[str, Any]:
        return self._post(PATH_DEPENDENCIES, {"dp_name": dp_name, "method": "NEW"}, steps)

    def dp_match(self, steps, dp_name: str) -> Dict[str, Any]:
        return self._post(PATH_DEPENDENCIES, {"dp_name": dp_name, "method": "MATCH"}, steps)

    def dp_remove(self, steps, dp_name: str) -> Dict[str, Any]:
        return self._post(PATH_DEPENDENCIES, {"dp_name": dp_name, "method": "REMOVE"}, steps)

    def dp_list(self, steps) -> List[str]:
        """EXTENSION (gap G-5)."""
        data = self._post(PATH_DEPENDENCIES, {"dp_name": "*", "method": "LIST"}, steps)
        return list(data.get("Dependencies", []))

    @staticmethod
    def dp_exists(match_response: Dict[str, Any]) -> bool:
        return str(match_response.get("status", "")).strip().lower() == "exists"
