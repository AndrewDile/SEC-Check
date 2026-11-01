"""In-memory reference system for running the tester locally. Not deployed.

Implements the Core API (spec_docs/API Spec.txt) plus the system side of the
tester interface (/test/setup, /test/report). Where the spec leaves a choice,
it behaves like the pod's real Core API (api/src/coreapi.ts): for example a
second team can't claim a ticket another team holds, and an EDIT keeps the
fields it doesn't send. State is kept per session (X-Session-ID header).

    python dev/mock_system.py --port 8200 [--bug wrong-status|no-validation|crash-logs|unordered-logs|setup-fails]

Bugs, for seeing how the tester reports a faulty system:
  wrong-status    success Status strings are wrong ("OK")
  no-validation   future timestamps and over-long descriptions are accepted
  crash-logs      /logs answers 500
  unordered-logs  /logs lists tickets newest first
  setup-fails     /test/setup answers 500
  claim-steal        any team can claim a ticket another team already holds
  edit-drops-fields  a ticket EDIT resets severity, urgency and teams it didn't send
  log-latest-only    /logs lists only the latest version of each ticket
  ignore-session     one shared state for every session (X-Session-ID ignored); not a bug
  strict-setup       /test/setup rejects a non-empty setup object (like another pod's system); not a bug
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

BUGS = (
    "none",
    "wrong-status",
    "no-validation",
    "crash-logs",
    "unordered-logs",
    "setup-fails",
    "claim-steal",
    "edit-drops-fields",
    "log-latest-only",
    "ignore-session",
    "strict-setup",
)
MATERIALITY = ["MATERIAL", "IMMATERIAL", "UNDECIDED"]
SEVERITY = ["HIGH", "MEDIUM", "LOW", "UNDECIDED", "RESOLVED"]
URGENCY = ["URGENT", "NOT_URGENT", "UNDECIDED", "RESOLVED"]
DEFAULT_TEAMS = ["LEGAL", "CYBER1", "CYBER2"]
DEFAULT_SESSION = "default"


class CoreError(Exception):
    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error, self.message = error, message


def invalid(message: str):
    raise CoreError("INVALID_DATA", message)


class SessionState:
    def __init__(self, teams: List[str]):
        self.teams = list(teams)
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.tickets: Dict[str, Dict[str, Any]] = {}  # "<id>_<n>" -> ticket
        self.counters: Dict[str, int] = {}
        self.log: Dict[str, List[str]] = {}  # incident -> strong IDs in action order
        self.dependencies: List[str] = []


class MockSystem:
    def __init__(self, bug: str = "none"):
        if bug not in BUGS:
            raise ValueError("unknown bug %r" % bug)
        self.bug = bug
        self.lock = threading.Lock()
        self.sessions: Dict[str, SessionState] = {DEFAULT_SESSION: SessionState(DEFAULT_TEAMS)}

    # ------------------------------------------------------------------ http entry
    def handle(self, method: str, raw_path: str, headers, body: bytes) -> Tuple[int, Any]:
        parts = urlsplit(raw_path)
        path = parts.path.rstrip("/") or "/"
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (ValueError, UnicodeDecodeError):
            return 400, {"Error": "INVALID_DATA", "Message": "Request body is not valid JSON."}
        try:
            with self.lock:
                if path == "/test/setup" and method == "POST":
                    return self.test_setup(payload)
                if path == "/test/report" and method == "GET":
                    return self.test_report(parse_qs(parts.query).get("session_id", [""])[0])
                route = {
                    "/incidents": self.incidents,
                    "/tickets": self.tickets,
                    "/notifier": self.notifier,
                    "/logs": self.logs,
                    "/dependencies": self.dependencies,
                    "/dependancies": self.dependencies,
                    "/reset": self.reset,
                }.get(path)
                if route is None or method != "POST":
                    return 404, {
                        "Error": "INVALID_DATA",
                        "Message": "No route %s %s." % (method, path),
                    }
                if not isinstance(payload, dict):
                    invalid("Request body must be a JSON object.")
                sid = headers.get("X-Session-ID") or payload.get("session_id") or DEFAULT_SESSION
                if self.bug == "ignore-session":
                    sid = DEFAULT_SESSION
                state = self.sessions.setdefault(sid, SessionState(DEFAULT_TEAMS))
                return 200, route(state, payload)
        except CoreError as exc:
            return 400, {"Error": exc.error, "Message": exc.message}
        except Exception as exc:  # noqa: BLE001
            return 500, {"message": "Internal error: %s" % exc, "source": "system"}

    def status(self, value: str) -> str:
        return "OK" if self.bug == "wrong-status" else value

    # ------------------------------------------------------------------ tester interface
    def test_setup(self, payload: Any) -> Tuple[int, Any]:
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("session_id"), str)
            or not payload["session_id"]
        ):
            return 400, {"message": "session_id is required.", "source": "system"}
        if self.bug == "setup-fails":
            return 500, {
                "message": "Could not initialize the session database.",
                "source": "system",
            }
        if self.bug == "strict-setup" and payload.get("setup") != {}:
            return 400, {"message": "setup must be {}", "source": "system"}
        sid = payload["session_id"]
        if sid in self.sessions and self.bug != "ignore-session":
            return 409, {"message": "Session %s already exists." % sid, "source": "system"}
        setup = payload.get("setup") if isinstance(payload.get("setup"), dict) else {}
        teams = setup.get("teams") if isinstance(setup.get("teams"), list) else DEFAULT_TEAMS
        if self.bug != "ignore-session":
            self.sessions[sid] = SessionState(teams)
        return 201, {"session_id": sid}

    def test_report(self, sid: str) -> Tuple[int, Any]:
        if not sid:
            return 400, {"message": "session_id is required.", "source": "system"}
        if sid not in self.sessions and self.bug != "ignore-session":
            return 404, {"message": "Unknown session %s." % sid, "source": "system"}
        return 200, {
            "session_id": sid,
            "coverage": {
                "code": {
                    "covered": None,
                    "total": None,
                    "basis": "The mock system does not measure code coverage.",
                }
            },
        }

    # ------------------------------------------------------------------ validation
    def timestamp(self, value: Any) -> str:
        if not isinstance(value, str):
            invalid("Timestamp must be an RFC 3339 date-time.")
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            invalid("Timestamp must be an RFC 3339 date-time.")
        if ts.tzinfo is None:
            invalid("Timestamp must include a time zone.")
        if self.bug != "no-validation" and ts > datetime.now(timezone.utc) + timedelta(seconds=5):
            invalid("Timestamp cannot be set in the future.")
        return value

    def description(self, value: Any) -> str:
        if not isinstance(value, str):
            invalid("Description is required.")
        if self.bug != "no-validation" and len(value) > 5000:
            invalid("Description must be at most 5000 characters.")
        return value

    @staticmethod
    def one_of(body: Dict[str, Any], key: str, allowed: List[str]) -> Optional[str]:
        if key not in body:
            return None
        if body[key] not in allowed:
            invalid("%s must be one of %s." % (key, ", ".join(allowed)))
        return body[key]

    @staticmethod
    def teams(state: SessionState, value: Any, key: str) -> Optional[List[str]]:
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            invalid("%s must be a list of team names." % key)
        unknown = [t for t in value if t not in state.teams]
        if unknown:
            invalid("Unknown team name: %s." % ", ".join(unknown))
        return list(value)

    @staticmethod
    def incident_of(state: SessionState, incident_id: Any) -> Dict[str, Any]:
        rec = state.incidents.get(str(incident_id))
        if rec is None:
            raise CoreError("UUID_DNE", "The specified Incident_ID does not exist.")
        return rec

    @staticmethod
    def ticket_of(
        state: SessionState, number: Any, incident_id: Optional[str] = None
    ) -> Dict[str, Any]:
        text = str(number) if number is not None else ""
        if incident_id is not None and text.isdigit():
            text = "%s_%s" % (incident_id, text)
        head, _, tail = text.rpartition("_")
        if not head or not tail.isdigit():
            invalid("Ticket number must be <Incident_ID>_<number>.")
        if incident_id is not None and head != str(incident_id):
            invalid("Ticket number does not belong to Incident_ID.")
        ticket = state.tickets.get(text)
        if ticket is None:
            raise CoreError("UUID_DNE", "The specified ticket does not exist.")
        return ticket

    # ------------------------------------------------------------------ /incidents
    def incident_view(self, rec: Dict[str, Any], status: str) -> Dict[str, Any]:
        out = {
            "Incident_ID": rec["Incident_ID"],
            "Status": self.status(status),
            "Description": rec["Description"],
            "Materiality": rec["Materiality"],
            "Severity": rec["Severity"],
            "Urgency": rec["Urgency"],
            "Timestamp": rec["Timestamp"],
        }
        if rec.get("Dependency"):
            out["Dependency"] = rec["Dependency"]
        return out

    def incidents(self, state: SessionState, b: Dict[str, Any]) -> Dict[str, Any]:
        iid = b.get("Incident_ID")
        if not isinstance(iid, str) or not iid or "_" in iid:
            invalid("Incident_ID is invalid.")
        ts = self.timestamp(b.get("Timestamp"))
        method = b.get("Method")
        fields = {
            "Materiality": self.one_of(b, "Materiality", MATERIALITY),
            "Severity": self.one_of(b, "Severity", SEVERITY),
            "Urgency": self.one_of(b, "Urgency", URGENCY),
        }
        dependency = b.get("Dependency", b.get("Dependency_Name"))
        if method == "NEW":
            desc = self.description(b.get("Description"))
            if iid in state.incidents:
                raise CoreError(
                    "UUID_EXISTS", "The provided Incident_ID already exists in the system."
                )
            rec = {
                "Incident_ID": iid,
                "Description": desc,
                "Timestamp": ts,
                "Dependency": dependency or None,
            }
            rec.update({k: v or "UNDECIDED" for k, v in fields.items()})
            state.incidents[iid] = rec
            state.log[iid] = []
            return self.incident_view(rec, "Created")
        if method == "EDIT":
            desc = self.description(b.get("Description"))
            rec = self.incident_of(state, iid)
            rec["Description"] = desc
            rec.update({k: v for k, v in fields.items() if v is not None})
            if dependency is not None:
                rec["Dependency"] = dependency or None
            return self.incident_view(rec, "Edited")
        if method == "GET":
            return self.incident_view(self.incident_of(state, iid), "Data Fetched")
        invalid("Method must be one of NEW, EDIT, GET.")

    # ------------------------------------------------------------------ /tickets
    def ticket_view(
        self, state: SessionState, ticket: Dict[str, Any], status: str
    ) -> Dict[str, Any]:
        inc = state.incidents[ticket["Incident_ID"]]
        v = ticket["versions"][-1]
        out = {
            "Incident_ID": inc["Incident_ID"],
            "Ticket_ID": v["Ticket_ID"],
            "Ticket_number": ticket["number"],
            "Status": self.status(status),
            "UUID_Description": inc["Description"],
            "Ticket_Description": v["Description"],
            "Materiality_type": inc["Materiality"],
            "uuid_severity": inc["Severity"],
            "uuid_urgency": inc["Urgency"],
            "ticket_severity": v["Severity"],
            "ticket_urgency": v["Urgency"],
            "Team_List": list(v["Teams"]),
            "Ticket_Claim": "CLAIMED" if ticket["claimed_by"] else "UNCLAIMED",
            "Timestamp": v["Timestamp"],
        }
        if ticket["claimed_by"]:
            out["Claimed_By"] = ticket["claimed_by"]
        return out

    def tickets(self, state: SessionState, b: Dict[str, Any]) -> Dict[str, Any]:
        iid = str(b.get("Incident_ID", ""))
        ts = self.timestamp(b.get("Timestamp"))
        severity = self.one_of(b, "Ticket_severity", SEVERITY)
        urgency = self.one_of(b, "Ticket_urgency", URGENCY)
        teams = self.teams(state, b.get("Team_list"), "Team_list")
        method = b.get("Method")
        if method not in ("NEW", "EDIT", "GET"):
            invalid("Method must be one of NEW, EDIT, GET.")
        self.incident_of(state, iid)
        if method == "NEW":
            desc = self.description(b.get("Description"))
            n = state.counters.get(iid, 0) + 1
            state.counters[iid] = n
            number = "%s_%d" % (iid, n)
            version = {
                "Ticket_ID": number + "_1",
                "Description": desc,
                "Timestamp": ts,
                "Severity": severity or "UNDECIDED",
                "Urgency": urgency or "UNDECIDED",
                "Teams": teams or [],
            }
            ticket = {
                "Incident_ID": iid,
                "number": number,
                "versions": [version],
                "claimed_by": None,
                "notified": [],
            }
            state.tickets[number] = ticket
            state.log[iid].append(version["Ticket_ID"])
            return self.ticket_view(state, ticket, "Logged")
        ticket = self.ticket_of(state, b.get("Ticket_number"), iid)
        if method == "EDIT":
            desc = self.description(b.get("Description"))
            prev = ticket["versions"][-1]
            if self.bug == "edit-drops-fields":
                prev = {"Severity": "UNDECIDED", "Urgency": "UNDECIDED", "Teams": []}
            version = {
                "Ticket_ID": "%s_%d" % (ticket["number"], len(ticket["versions"]) + 1),
                "Description": desc,
                "Timestamp": ts,
                "Severity": severity or prev["Severity"],
                "Urgency": urgency or prev["Urgency"],
                "Teams": teams if teams is not None else prev["Teams"],
            }
            ticket["versions"].append(version)
            state.log[iid].append(version["Ticket_ID"])
            return self.ticket_view(state, ticket, "Edited")
        return self.ticket_view(state, ticket, "Displayed")

    # ------------------------------------------------------------------ /notifier
    def notifier(self, state: SessionState, b: Dict[str, Any]) -> Dict[str, Any]:
        teams = b.get("Team_Names")
        if not isinstance(teams, list) or not teams:
            invalid("Team_Names invalid data type")
        self.teams(state, teams, "Team_Names")
        method = b.get("Method")
        if method not in ("CLAIM", "NOTIFY"):
            invalid("Method must be one of CLAIM, NOTIFY.")
        ticket = self.ticket_of(state, b.get("Ticket_Number"))
        if method == "CLAIM":
            if len(teams) != 1:
                invalid("CLAIM takes exactly one team.")
            if (
                ticket["claimed_by"]
                and ticket["claimed_by"] != teams[0]
                and self.bug != "claim-steal"
            ):
                invalid("Ticket is already claimed by %s." % ticket["claimed_by"])
            ticket["claimed_by"] = teams[0]
            status = "Claimed ticket"
        else:
            ticket["notified"].extend(teams)
            status = "Notified team"
        iid = ticket["Incident_ID"]
        return {
            "UUID": int(iid) if iid.isdigit() else iid,
            "Ticket_Number": ticket["number"],
            "Status": self.status(status),
        }

    # ------------------------------------------------------------------ /logs
    def logs(self, state: SessionState, b: Dict[str, Any]) -> Dict[str, Any]:
        if self.bug == "crash-logs":
            raise RuntimeError("log query failed")
        self.timestamp(b.get("Timestamp"))
        rec = self.incident_of(state, b.get("Incident_ID"))
        entries = list(state.log[rec["Incident_ID"]])
        if self.bug == "unordered-logs":
            entries.reverse()
        if self.bug == "log-latest-only":
            latest = {}
            for entry in entries:
                latest[entry.rpartition("_")[0]] = entry
            entries = [e for e in entries if latest[e.rpartition("_")[0]] == e]
        return {
            "Incident_ID": rec["Incident_ID"],
            "Description": rec["Description"],
            "Materiality_type": rec["Materiality"],
            "Severity": rec["Severity"],
            "Urgency": rec["Urgency"],
            "Ticket_ID_List": entries,
            "Status": self.status("Log Retrieved"),
        }

    # ------------------------------------------------------------------ /dependencies
    def dependencies(self, state: SessionState, b: Dict[str, Any]) -> Dict[str, Any]:
        name, method = b.get("dp_name"), b.get("method")
        if not isinstance(name, str) or not name.strip():
            invalid("dp_name must be a non-empty string.")
        if method == "NEW":
            if name in state.dependencies:
                raise CoreError("DP_EXISTS", "The dependency name already exists in the system.")
            state.dependencies.append(name)
            return {"dp_name": name, "status": self.status("Added")}
        if method == "MATCH":
            return {
                "dp_name": name,
                "status": self.status("Exists" if name in state.dependencies else "Does not Exist"),
            }
        if method == "REMOVE":
            if name not in state.dependencies:
                raise CoreError("DP_DNE", "The dependency name does not exist in the system.")
            state.dependencies.remove(name)
            return {"dp_name": name, "status": self.status("Removed")}
        invalid("method must be one of NEW, MATCH, REMOVE.")

    # ------------------------------------------------------------------ /reset
    def reset(self, state: SessionState, b: Dict[str, Any]) -> Dict[str, Any]:
        if b.get("method") != "RESET":
            invalid("method must be RESET.")
        state.__init__(state.teams)
        return {"status": self.status("DB Wiped")}


def make_handler(system: MockSystem):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b""
            status, out = system.handle(method, self.path, self.headers, body)
            data = json.dumps(out).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def log_message(self, fmt, *args):
            if getattr(system, "verbose", False):
                super().log_message(fmt, *args)

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def shutdown(self):
        super().shutdown()
        self.server_close()


def start(port: int = 0, bug: str = "none", host: str = "127.0.0.1"):
    """Start in a background thread. Returns (httpd, base_url); stop with httpd.shutdown()."""
    httpd = _Server((host, port), make_handler(MockSystem(bug)))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://%s:%d" % (host, httpd.server_address[1])


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="In-memory SEC-Check reference system for the tester."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--bug", choices=BUGS, default="none")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)
    system = MockSystem(args.bug)
    system.verbose = args.verbose
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(system))
    print(
        "Mock SEC-Check system on http://%s:%d (bug: %s)" % (args.host, args.port, args.bug),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
