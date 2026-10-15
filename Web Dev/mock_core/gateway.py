"""Core API -> Web App gateway for the mock Core API.

In system testing, API test clients call the Core API, and the Core API drives
the Web App through the Web App API (spec_docs/Web App API.txt). This module
does that translation:

    test client --Core API call--> mock Core --Web App API request--> Web App
                                                                       |
               (Web App stores data by calling the Core API back, marked
                X-SECheck-Origin: webapp, which the mock handles locally)
                                                                       |
    test client <--Core API response-- mock Core <--Web App response---+

Each Core operation maps to the Web App endpoint(s) listed in section 2 of the
Web App API spec, and the Web App response is converted back to the Core
response format (e.g. Dependency_Name -> Dependency, Web-App-only fields dropped).
Errors keep the Core envelope {Error, Message}.

The mock signs in to the Web App as a service user (settings:
mock_core_gateway_user), so audit tickets show who acted: "... by core-gateway".
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlencode

WEBAPP_BASE_PATH = "/webapp/v1"
DEFAULT_RATIONALE = "Recorded through the Core API (no rationale supplied)."
DECISION_FIELDS = ("Materiality", "Severity", "Urgency")
INCIDENT_FIELDS = ("Incident_ID", "Description", "Materiality", "Severity", "Urgency", "Timestamp")


class CoreError(Exception):
    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error, self.message = error, message


def _seg(value: Any) -> str:
    return quote(str(value), safe="")


class WebAppGateway:
    def __init__(self, webapp_url: str, user: str, timeout: float = 10.0,
                 on_forward: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.webapp_url = webapp_url.rstrip("/")
        self.user = user
        self.timeout = timeout
        self.on_forward = on_forward
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._core_call = ""

    # ------------------------------------------------------------------ dispatch
    def handle(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        method = body.get("Method", body.get("method"))
        self._core_call = f"{path} {method}"
        if path == "/incidents":
            return self._incidents(method, body)
        if path == "/tickets":
            return self._tickets(method, body)
        if path == "/notifier":
            return self._notifier(method, body)
        if path == "/logs":
            return self._logs(body)
        if path in ("/dependencies", "/dependancies"):
            return self._dependencies(method, body)
        raise CoreError("INVALID_DATA", f"The gateway does not handle {path}.")

    # ------------------------------------------------------------------ transport
    def _web(self, method: str, path: str, body: Any = None, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        full_path = WEBAPP_BASE_PATH + path + (f"?{urlencode(query)}" if query else "")
        request = urllib.request.Request(
            self.webapp_url + full_path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json", "X-User": self.user},
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except (socket.timeout, TimeoutError):
            self._record(method, full_path, body, None)
            raise CoreError("TIMEOUT", "The Web App did not respond in time.")
        except (urllib.error.URLError, OSError) as exc:
            self._record(method, full_path, body, None)
            reason = getattr(exc, "reason", exc)
            raise CoreError("UPSTREAM_UNAVAILABLE", f"Cannot reach the Web App at {self.webapp_url} ({reason}).")
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            data = None
        self._record(method, full_path, body, status)
        if status == 200 and isinstance(data, dict):
            return data
        if isinstance(data, dict) and "Error" in data:
            raise CoreError(str(data["Error"]), str(data.get("Message", "")))
        raise CoreError("UPSTREAM_UNAVAILABLE", f"The Web App returned HTTP {status} without an error body.")

    def _record(self, method: str, path: str, body: Any, status: Optional[int]) -> None:
        if self.on_forward:
            self.on_forward({"core": self._core_call, "web": f"{method} {path}", "body": body, "status": status})

    # ------------------------------------------------------------------ conversions
    @staticmethod
    def _incident_out(data: Dict[str, Any], status: Optional[str]) -> Dict[str, Any]:
        out = {k: data[k] for k in INCIDENT_FIELDS if k in data}
        if data.get("Dependency_Name"):
            out["Dependency"] = data["Dependency_Name"]
        if status:
            out["Status"] = status
        return out

    @staticmethod
    def _without(data: Dict[str, Any], *keys: str, status: Optional[str] = None) -> Dict[str, Any]:
        out = {k: v for k, v in data.items() if k not in keys}
        if status:
            out["Status"] = status
        return out

    @staticmethod
    def _notifier_out(data: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(data)
        uuid = str(out.get("UUID", ""))
        out["UUID"] = int(uuid) if uuid.isdigit() else uuid  # Core spec says integer
        return out

    @staticmethod
    def _require(body: Dict[str, Any], field: str, when: str) -> Any:
        if not body.get(field):
            raise CoreError("INVALID_DATA", f"{field} is required when {when}.")
        return body[field]

    # ------------------------------------------------------------------ /incidents
    def _incidents(self, method: str, b: Dict[str, Any]) -> Dict[str, Any]:
        if method == "LIST":
            items: List[Dict[str, Any]] = []
            page = 1
            while True:
                data = self._web("GET", "/incidents", query={"page": page, "page_size": 100})
                items += data.get("Incidents", [])
                if len(items) >= data.get("total", 0) or not data.get("Incidents"):
                    break
                page += 1
            return {"Incidents": [self._incident_out(i, None) for i in items], "Status": "Listed"}

        incident_id = str(b.get("Incident_ID", ""))
        if method == "NEW":
            web_body = {"Incident_ID": incident_id, "Description": b["Description"], "Timestamp": b["Timestamp"]}
            for key in DECISION_FIELDS:
                if key in b:
                    web_body[key] = b[key]
            dependency = b.get("Dependency") or b.get("Dependency_Name")
            if dependency:
                web_body["Dependency_Name"] = dependency
            return self._incident_out(self._web("POST", "/incidents", web_body), "Created")

        if method == "GET":
            return self._incident_out(self._web("GET", f"/incidents/{_seg(incident_id)}"), "Data Fetched")

        # EDIT: detail changes -> PATCH, decision changes -> PUT .../decision (needs a Rationale)
        current = self._web("GET", f"/incidents/{_seg(incident_id)}")
        details: Dict[str, Any] = {}
        if "Description" in b and b["Description"] != current.get("Description"):
            details["Description"] = b["Description"]
        for key in ("Dependency", "Dependency_Name"):
            if key in b and (b[key] or "") != (current.get("Dependency_Name") or ""):
                details["Dependency_Name"] = b[key] or ""
        decision = {k: b[k] for k in DECISION_FIELDS if k in b and b[k] != current.get(k)}
        if details:
            self._web("PATCH", f"/incidents/{_seg(incident_id)}", details)
        if decision:
            decision["Rationale"] = b.get("Rationale") or DEFAULT_RATIONALE
            self._web("PUT", f"/incidents/{_seg(incident_id)}/decision", decision)
        final = self._web("GET", f"/incidents/{_seg(incident_id)}") if (details or decision) else current
        return self._incident_out(final, "Edited")

    # ------------------------------------------------------------------ /tickets
    def _tickets(self, method: str, b: Dict[str, Any]) -> Dict[str, Any]:
        if method == "LIST":
            team = self._require(b, "Team", "Method is LIST")
            query = {"team": team}
            if b.get("Ticket_Claim"):
                query["claim"] = b["Ticket_Claim"]
            data = self._web("GET", "/queue", query=query)
            return {"Tickets": data.get("Tickets", []), "Status": "Listed"}

        incident_id = _seg(b.get("Incident_ID", ""))
        if method == "NEW":
            web_body = {"Description": self._require(b, "Description", "Method is NEW"), "Notify": False}
            for core_key in ("Ticket_severity", "Ticket_urgency", "Team_list"):
                if core_key in b:
                    web_body[core_key] = b[core_key]
            data = self._web("POST", f"/incidents/{incident_id}/tickets", web_body)
            return self._without(data, "Notified_Teams", status="Logged")

        raw_number = str(self._require(b, "Ticket_number", f"Method is {method}"))
        number = _seg(raw_number)
        if method == "GET" and raw_number.count("_") >= 2:
            return self._ticket_version(incident_id, raw_number)
        if method == "GET":
            return self._without(self._web("GET", f"/incidents/{incident_id}/tickets/{number}"), status="Displayed")

        web_body = {"Description": self._require(b, "Description", "Method is EDIT")}
        for core_key in ("Ticket_severity", "Ticket_urgency", "Team_list"):
            if core_key in b:
                web_body[core_key] = b[core_key]
        return self._without(self._web("PATCH", f"/incidents/{incident_id}/tickets/{number}", web_body), status="Edited")

    def _ticket_version(self, incident_id: str, ticket_id: str) -> Dict[str, Any]:
        """GET by Ticket_type_strong: the Web App serves single versions through its log entries."""
        data = self._web("GET", f"/incidents/{incident_id}/log/entries")
        for entry in data.get("Entries", []):
            if entry.get("Ticket_ID") == ticket_id and entry.get("Details_Available"):
                out = {k: v for k, v in entry.items() if k not in ("Ticket_number", "Version", "Details_Available", "Entry_Type")}
                return {"Incident_ID": data.get("Incident_ID"), **out, "Status": "Displayed"}
        raise CoreError("UUID_DNE", "The specified ticket version does not exist.")

    # ------------------------------------------------------------------ /notifier
    def _notifier(self, method: str, b: Dict[str, Any]) -> Dict[str, Any]:
        teams = b.get("Team_Names")
        if not isinstance(teams, list) or not teams:
            raise CoreError("INVALID_DATA", "Team_Names invalid data type")
        number = _seg(b.get("Ticket_Number", ""))
        if method == "CLAIM":
            if len(teams) != 1:
                raise CoreError("INVALID_DATA", "Only one team can claim a ticket.")
            return self._notifier_out(self._web("POST", f"/tickets/{number}/claim", {"Team_Name": teams[0]}))
        return self._notifier_out(self._web("POST", f"/tickets/{number}/notify", {"Team_Names": teams}))

    # ------------------------------------------------------------------ /logs
    def _logs(self, b: Dict[str, Any]) -> Dict[str, Any]:
        return self._web("GET", f"/incidents/{_seg(b.get('Incident_ID', ''))}/log")

    # ------------------------------------------------------------------ /dependencies
    def _dependencies(self, method: str, b: Dict[str, Any]) -> Dict[str, Any]:
        if method == "LIST":
            return {"Dependencies": self._web("GET", "/dependencies").get("Dependencies", []), "status": "Listed"}
        name = b.get("dp_name")
        if not isinstance(name, str) or not name.strip():
            raise CoreError("INVALID_DATA", "dp_name must be a non-empty string.")
        if method == "NEW":
            return self._web("POST", "/dependencies", {"dp_name": name})
        if method == "MATCH":
            return self._web("GET", f"/dependencies/{_seg(name)}")
        return self._web("DELETE", f"/dependencies/{_seg(name)}")
