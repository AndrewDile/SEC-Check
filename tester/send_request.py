"""Send one HTTP request with a JSON body from a file, and print the response.

    python send_request.py http://<server-ip>:3001/incidents requests/incident_new.json
    python send_request.py http://<server-ip>:3001/health                 (no file: GET)
    python send_request.py http://<server-ip>:8100/test/report?session_id=x
    python send_request.py URL FILE --method PUT --header "X-Session-ID: run-1"

With a file the request is a POST (the Core API's style) unless --method says
otherwise; without one it's a GET. Needs nothing but Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Send a JSON file as an HTTP request and print the response.")
    parser.add_argument("url", help="full URL including the path, e.g. http://1.2.3.4:3001/incidents")
    parser.add_argument("json_file", nargs="?", help="file with the JSON body (omit for a GET without a body)")
    parser.add_argument("--method", help="HTTP method (default: POST with a file, GET without)")
    parser.add_argument("--header", action="append", default=[], metavar="'Name: value'", help="extra header (repeatable)")
    parser.add_argument("--timeout", type=float, default=15, help="seconds to wait (default 15)")
    parser.add_argument("--headers", action="store_true", help="also print the response headers")
    args = parser.parse_args(argv)

    data = None
    headers = {"Accept": "application/json"}
    if args.json_file:
        try:
            with open(args.json_file, encoding="utf-8") as f:
                body = json.load(f)          # checks the file is valid JSON before sending
        except (OSError, ValueError) as exc:
            print("Can't use %s: %s" % (args.json_file, exc), file=sys.stderr)
            return 2
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    for h in args.header:
        name, sep, value = h.partition(":")
        if not sep:
            print("--header must look like 'Name: value', got %r" % h, file=sys.stderr)
            return 2
        headers[name.strip()] = value.strip()
    method = (args.method or ("POST" if data is not None else "GET")).upper()

    print("> %s %s" % (method, args.url))
    if data is not None:
        print(json.dumps(body, indent=2))
    print()

    start = time.monotonic()
    req = urllib.request.Request(args.url, data=data, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=args.timeout)
    except urllib.error.HTTPError as exc:
        resp = exc                       # 4xx/5xx still carry a response body
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        print("No response: %s" % reason, file=sys.stderr)
        return 2
    with resp:
        raw = resp.read()
        status, reason, resp_headers = resp.status, resp.reason, resp.headers
    print("< %s %s  (%.0f ms)" % (status, reason, (time.monotonic() - start) * 1000))
    if args.headers:
        for k, v in resp_headers.items():
            print("< %s: %s" % (k, v))
    text = raw.decode("utf-8", "replace")
    try:
        print(json.dumps(json.loads(text), indent=2))
    except ValueError:
        print(text if text else "(empty body)")
    return 0 if status < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
