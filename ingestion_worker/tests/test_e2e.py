"""End to end: a dependency added through the Core API, through the real worker and notifier
containers, to incidents in the database and delivered notices. WIPES the real data.

Runs only when E2E_SYSTEM_URL is set, against docker-compose.e2e.yml, which points the worker at
mock_feeds.py and polls only hourly. So anything seen here within seconds came from the catch-up.
"""

import json
import os
import time
import unittest
import urllib.request
from datetime import UTC, datetime, timedelta

SYSTEM = os.environ.get("E2E_SYSTEM_URL")
TIMEOUT_S = 60


def post(path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{SYSTEM}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def add_dependency(name: str) -> None:
    post("/dependencies", {"dp_name": name, "method": "NEW"})


def incidents() -> dict[str, dict]:
    """Every incident by its CVE, which starts its description."""
    listed = post("/incidents", {"Method": "LIST"})["Incidents"]
    return {i["Description"].split(":")[0]: i for i in listed}


def audit(incident_id: str) -> list[dict]:
    # Slightly in the past, because the API rejects future timestamps
    timestamp = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return post("/logs", {"Incident_ID": incident_id, "Timestamp": timestamp})["Audit_Log"]


def events(incident_id: str, name: str) -> list[dict]:
    return [entry for entry in audit(incident_id) if entry["Event"] == name]


def wait_until(condition, what: str):
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}")


def wait_for_incident(cve: str) -> dict:
    return wait_until(lambda: incidents().get(cve), cve)


def delivered(incident_id: str, count: int) -> list[dict]:
    """Wait for `count` notices to be reported as delivered, and return their result entries."""

    def reported():
        entries = events(incident_id, "NOTIFICATION_RESULTS")
        return entries if len(entries) >= count else None

    return wait_until(reported, f"{count} notification results for {incident_id}")


@unittest.skipUnless(SYSTEM, "E2E_SYSTEM_URL is not set")
class DependencyCatchUp(unittest.TestCase):
    def setUp(self):
        post("/reset", {"method": "RESET"})

    def test_product_only_name_finds_a_recent_incident_right_away(self):
        add_dependency("Quillgate Server")
        incident = wait_for_incident("CVE-E2E-RECENT")
        self.assertEqual(incident["Dependency"], "Quillgate Server")
        for result in delivered(incident["Incident_ID"], 1)[0]["Details"]["results"]:
            self.assertEqual(result["status"], "delivered")
        # Older matches this weak are not backfilled
        self.assertNotIn("CVE-E2E-OLD", incidents())

    def test_vendor_only_name_finds_only_recent_incidents(self):
        add_dependency("Zephyrine")
        wait_for_incident("CVE-E2E-RECENT")
        self.assertEqual(set(incidents()), {"CVE-E2E-RECENT"})

    def test_old_entries_are_backfilled_without_notices(self):
        add_dependency("Zephyrine:Quillgate Server")
        recent = wait_for_incident("CVE-E2E-RECENT")
        old = wait_for_incident("CVE-E2E-OLD")
        self.assertEqual(old["Dependency"], "Zephyrine:Quillgate Server")
        self.assertNotIn("CVE-E2E-OLD-OTHER", incidents())

        delivered(recent["Incident_ID"], 1)  # the notifier has had time to act
        self.assertEqual(events(old["Incident_ID"], "NOTIFICATION_SENT"), [])
        created = events(old["Incident_ID"], "INCIDENT_CREATED")
        self.assertEqual(created[0]["Actor"], "ingestion-worker")

    def test_a_later_dependency_updates_the_incident_and_notifies_again(self):
        add_dependency("Quillgate Server")
        first = wait_for_incident("CVE-E2E-RECENT")
        incident_id = first["Incident_ID"]
        delivered(incident_id, 1)

        add_dependency("Zephyrine:Quillgate Server")
        added = wait_until(
            lambda: events(incident_id, "INCIDENT_MATCHES_ADDED"), "the match to be added"
        )
        self.assertEqual(
            [m["dependency_id"] for m in added[0]["Details"]["matches"]],
            ["Zephyrine:Quillgate Server"],
        )
        delivered(incident_id, 2)
        self.assertEqual(len(events(incident_id, "NOTIFICATION_SENT")), 2)

        # Still one incident, showing the dependency it was first reported for
        current = incidents()["CVE-E2E-RECENT"]
        self.assertEqual(current["Incident_ID"], incident_id)
        self.assertEqual(current["Dependency"], "Quillgate Server")

    def test_removed_dependency_stops_matching(self):
        add_dependency("Zephyrine:Harborlight")
        wait_for_incident("CVE-E2E-OLD-OTHER")
        post("/dependencies", {"dp_name": "Zephyrine:Harborlight", "method": "REMOVE"})
        post("/reset", {"method": "RESET"})
        # A marker dependency: once it has been processed, so has anything queued before it
        add_dependency("Zephyrine:Quillgate Server")
        wait_for_incident("CVE-E2E-OLD")
        self.assertNotIn("CVE-E2E-OLD-OTHER", incidents())
