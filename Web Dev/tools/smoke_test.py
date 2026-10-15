"""End-to-end check against running servers (mock or real Core API).

    python tools/smoke_test.py
    python tools/smoke_test.py --webapp http://localhost:8000 --core http://localhost:8001

Drives one full workflow through the Web App, then reads the results straight
from the Core API to confirm they really landed there:
  dependency -> intake -> ticket + notify -> claim -> material decision -> 8-K view
Steps that rely on proposed Core operations (list incidents / queue) are
reported as SKIP if the Core API does not support them yet.

Uses a unique dependency name and incident id each run, so it can be pointed at
a shared Core API; it does not call /reset.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from typing import Any, Optional, Tuple

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method: str, url: str, body: Any = None, user: Optional[str] = None) -> Tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if user:
        headers["X-User"] = user
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers)
    try:
        with OPENER.open(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--webapp", default="http://localhost:8000")
    p.add_argument("--core", default=None, help="Core API URL (default: ask the Web App /health)")
    p.add_argument("--user", default="dana", help="a configured user who is in at least one team")
    args = p.parse_args()
    api = args.webapp.rstrip("/") + "/webapp/v1"
    failures = 0

    def step(name: str, ok: bool, detail: Any = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if not ok else ""))

    print(f"Web App: {args.webapp}")
    status, health = call("GET", f"{api}/health")
    if status != 200:
        print(f"  FAIL  Web App not reachable (HTTP {status})")
        return 1
    core = (args.core or health["Core_API_URL"]).rstrip("/")
    print(f"Core API: {core}\n")
    step("Core API reachable from Web App", health["Core_API_Reachable"], health.get("Core_API_Detail"))

    _, session = call("GET", f"{api}/session", user=args.user)
    team = (session or {}).get("Teams", [None])[0]
    step("signed in as a team member", bool(team), session)
    if not team:
        return 1

    run = random.randint(10**5, 10**6 - 1)
    dep = f"smoke-dep-{run}"
    iid = f"9{run}{random.randint(10**5, 10**6 - 1)}"

    s, r = call("POST", f"{api}/dependencies", {"dp_name": dep}, args.user)
    step("add dependency", s == 200 and r.get("status") == "Added", r)
    s, r = call("POST", f"{api}/incidents", {"Incident_ID": iid, "Description": f"Smoke test incident {run}", "Dependency_Name": dep, "Severity": "LOW"}, args.user)
    step("manual intake", s == 200 and r.get("Status") == "Created", r)
    s, r = call("POST", f"{api}/incidents/{iid}/tickets", {"Description": "Smoke test ticket", "Team_list": [team]}, args.user)
    step("create ticket and notify", s == 200 and r.get("Notified_Teams") == [team], r)
    number = f"{iid}_2"
    s, r = call("GET", f"{api}/queue?team={team}", user=args.user)
    if s == 200:
        step("ticket appears in team queue", any(t.get("Ticket_number") == number for t in r.get("Tickets", [])), r)
    else:
        print(f"  SKIP  team queue ({(r or {}).get('Message', s)})")
    s, r = call("POST", f"{api}/tickets/{number}/claim", {"Team_Name": team}, args.user)
    step("claim ticket", s == 200 and r.get("Status") == "Claimed ticket", r)
    s, r = call("PUT", f"{api}/incidents/{iid}/decision", {"Materiality": "MATERIAL", "Rationale": "Smoke test decision"}, args.user)
    step("record material decision", s == 200 and r.get("Materiality") == "MATERIAL", r)
    s, r = call("GET", f"{api}/incidents/{iid}/form-8k", user=args.user)
    step("8-K view", s == 200 and r.get("Item_1_05", {}).get("Material_Impact") == "Smoke test decision", r)
    s, r = call("POST", f"{api}/incidents", {"Incident_ID": iid, "Description": "dup"}, args.user)
    step("duplicate intake rejected with UUID_EXISTS", s == 400 and (r or {}).get("Error") == "UUID_EXISTS", r)

    print("\nChecking the Core API directly:")
    s, r = call("POST", f"{core}/incidents", {"Incident_ID": iid, "Method": "GET", "Timestamp": "2020-01-01T00:00:00Z", "Description": ""})
    step("incident stored as MATERIAL", s == 200 and r.get("Materiality") == "MATERIAL", r)
    s, r = call("POST", f"{core}/logs", {"Incident_ID": iid, "Timestamp": "2020-01-01T00:00:00Z"})
    ids = ",".join(r.get("Ticket_ID_List", [])) if s == 200 else ""
    step("log has intake, ticket and decision", s == 200 and all(f"{iid}_{n}_1" in ids for n in (1, 2, 3)), r)

    call("DELETE", f"{api}/dependencies/{dep}", user=args.user)  # tidy up
    print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
