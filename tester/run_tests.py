"""Ask a deployed tester to run the suite against a system, and print the results.

    python run_tests.py http://localhost:3001
    python run_tests.py https://our-system.example.edu --tester https://our-tester.example.edu
    python run_tests.py http://localhost:3001 --failures-only --json report.json

The first argument is the system to test (its base URL). The tester is found at
--tester, else the TESTER_URL environment variable, else http://localhost:8100.
The script only calls the tester's POST /test/setup, POST /test/run and
GET /test/report; it needs nothing but Python 3.9+.

Exit code: 0 all passed, 1 some test didn't pass, 2 setup or the run failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

DEFAULT_TESTER = "http://localhost:8100"
LABELS = {"pass": "PASS", "fail": "FAIL", "error": "ERROR", "skip": "SKIP"}


def http(method: str, url: str, body: Any = None, timeout: float = 600) -> Tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {
                "message": raw.decode("utf-8", "replace")[:300] or "HTTP %d" % e.code,
                "source": "unknown",
            }


def run(target: str, tester: str) -> Tuple[int, Dict[str, Any], Optional[Dict[str, Any]]]:
    """Returns (status of /test/run or setup, its body, the stored report or None)."""
    try:
        status, body = http("POST", tester + "/test/setup", {"target_url": target})
        if status != 201:
            return status, body, None
        sid = body["session_id"]
        print("Session %s: tester %s is testing %s ..." % (sid, tester, target), flush=True)
        status, body = http("POST", tester + "/test/run", {"session_id": sid})
        report_status, report = http(
            "GET", tester + "/test/report?" + urllib.parse.urlencode({"session_id": sid})
        )
    except (urllib.error.URLError, OSError) as exc:
        return (
            0,
            {
                "message": "Could not reach the tester at %s (%s)." % (tester, exc),
                "source": "communication",
            },
            None,
        )
    return status, body, report if report_status == 200 else None


def print_report(report: Dict[str, Any], failures_only: bool) -> Dict[str, int]:
    counts = {k: 0 for k in LABELS}
    for r in report["results"]:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        if failures_only and r["outcome"] == "pass":
            continue
        label = LABELS.get(r["outcome"], r["outcome"].upper())
        if r["outcome"] == "error":
            label += "/" + r.get("source", "unknown")
        print("%-20s %-6s %s" % (label, r["test_id"], r["message"]))
    print()
    print(
        "Results: "
        + ", ".join("%d %s" % (n, k) for k, n in counts.items())
        + " (of %d)" % len(report["results"])
    )
    for key in ("system", "component", "code"):
        m = report["coverage"][key]
        if m["covered"] is None:
            print("Coverage %-11s null, %s" % (key + ":", m["basis"]))
        else:
            print("Coverage %-11s %d/%d   %s" % (key + ":", m["covered"], m["total"], m["basis"]))
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the SEC-Check tester suite against a system through a deployed tester."
    )
    parser.add_argument("target_url", help="the system's base URL, e.g. http://localhost:3001")
    parser.add_argument(
        "--tester",
        metavar="URL",
        default=os.environ.get("TESTER_URL", DEFAULT_TESTER),
        help="the tester's base URL (default: $TESTER_URL or %s)" % DEFAULT_TESTER,
    )
    parser.add_argument(
        "--failures-only", action="store_true", help="list only tests that didn't pass"
    )
    parser.add_argument("--json", metavar="FILE", help="also save the full report as JSON")
    args = parser.parse_args(argv)

    status, body, report = run(args.target_url, args.tester.rstrip("/"))
    if report is None:
        body = body if isinstance(body, dict) else {"message": str(body)}
        print(
            "Could not run the suite (%s): %s [source: %s]"
            % (status or "no response", body.get("message", body), body.get("source", "unknown")),
            file=sys.stderr,
        )
        return 2
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    counts = print_report(report, args.failures_only)
    if args.json:
        print("Full report saved to %s" % args.json)
    if status != 200:
        print("Run ended early: %s" % body.get("message", body), file=sys.stderr)
        return 2
    return 0 if counts["pass"] == len(report["results"]) else 1


if __name__ == "__main__":
    sys.exit(main())
