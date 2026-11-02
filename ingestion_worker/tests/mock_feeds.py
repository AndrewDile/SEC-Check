"""Stand-ins for the KEV and EDGAR feeds, for the end-to-end tests: python -m this module.

Dates are relative to now, so that the entries stay on the same side of the lookback window.
"""

import json
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8003


def _entry(cve: str, product: str, days_ago: int) -> dict:
    added = datetime.now(UTC).date() - timedelta(days=days_ago)
    return {
        "cveID": cve,
        "vendorProject": "Zephyrine",
        "product": product,
        "vulnerabilityName": f"Zephyrine {product} vulnerability",
        "dateAdded": added.isoformat(),
        "shortDescription": "A test vulnerability.",
        "requiredAction": "Patch it.",
        "dueDate": added.isoformat(),
        "knownRansomwareCampaignUse": "Unknown",
        "notes": "",
        "cwes": [],
    }


def kev() -> dict:
    return {
        "vulnerabilities": [
            _entry("CVE-E2E-RECENT", "Quillgate Server", 2),
            _entry("CVE-E2E-OLD", "Quillgate Server", 400),
            _entry("CVE-E2E-OLD-OTHER", "Harborlight", 400),
        ]
    }


EDGAR = {"hits": {"total": {"value": 0}, "hits": []}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = kev() if self.path.startswith("/kev") else EDGAR
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
