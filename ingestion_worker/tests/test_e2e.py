"""End to end: a dependency added through the Core API, through the real worker and notifier
containers, to incidents in the database and delivered notices, including email that reaches a mail
server (Mailpit) and posts that reach a fake Slack and Teams. WIPES the real data.

Runs only when E2E_SYSTEM_URL, E2E_MAILPIT_URL and E2E_WEBHOOKS_URL are set, against docker-compose.e2e.yml, which points the worker at
mock_feeds.py and polls only hourly. So anything seen here within seconds came from the catch-up.
"""

import json
import os
import time
import unittest
import urllib.request
from datetime import UTC, datetime, timedelta

SYSTEM = os.environ.get("E2E_SYSTEM_URL")
MAILPIT = os.environ.get("E2E_MAILPIT_URL")
WEBHOOKS = os.environ.get("E2E_WEBHOOKS_URL")
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
    return post("/logs", {"Incident_ID": incident_id, "Timestamp": timestamp})["Audit_Entries"]


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


def call(url: str, method: str = "GET"):
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body) if method == "GET" else None


def mailpit(path: str, method: str = "GET"):
    return call(f"{MAILPIT}/api/v1{path}", method)


@unittest.skipUnless(SYSTEM, "E2E_SYSTEM_URL is not set")
class DependencyCatchUp(unittest.TestCase):
    def setUp(self):
        post("/reset", {"method": "RESET"})
        # A reset leaves no teams; with one, each notice has a recipient (the team's log notice)
        post("/teams", {"Team_Name": "LEGAL", "Method": "NEW"})

    def test_product_only_name_finds_a_recent_incident_right_away(self):
        add_dependency("Quillgate Server")
        incident = wait_for_incident("CVE-E2E-RECENT")
        self.assertEqual(incident["Dependency"], "Quillgate Server")
        results = delivered(incident["Incident_ID"], 1)[0]["Details"]["results"]
        self.assertTrue(results, "the notice reached no one")
        for result in results:
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


@unittest.skipUnless(SYSTEM and MAILPIT, "E2E_SYSTEM_URL or E2E_MAILPIT_URL is not set")
class EmailNotice(unittest.TestCase):
    def test_an_incident_is_emailed_to_the_teams_contact(self):
        post("/reset", {"method": "RESET"})
        mailpit("/messages", "DELETE")
        post("/teams", {"Team_Name": "LEGAL", "Method": "NEW"})
        contact = {"Contact_Channel": "email", "Contact": "legal@example.com"}
        post("/teams", {"Team_Name": "LEGAL", "Method": "ADD_CONTACT", **contact})

        add_dependency("Quillgate Server")
        incident_id = wait_for_incident("CVE-E2E-RECENT")["Incident_ID"]
        results = delivered(incident_id, 1)[0]["Details"]["results"]
        self.assertEqual([r["status"] for r in results], ["delivered"], results)

        # Reported as delivered only after the mail server took it, so it's already there
        messages = mailpit("/messages")["messages"]
        self.assertEqual(len(messages), 1)
        email = mailpit(f"/message/{messages[0]['ID']}")
        self.assertEqual([to["Address"] for to in email["To"]], ["legal@example.com"])
        self.assertEqual(email["From"]["Address"], "alerts@example.com")
        self.assertIn("CVE-E2E-RECENT", email["Subject"])
        self.assertIn("Quillgate Server", email["Text"])
        self.assertIn(f"/app/#/incidents/{incident_id}", email["Text"])


@unittest.skipUnless(SYSTEM and WEBHOOKS, "E2E_SYSTEM_URL or E2E_WEBHOOKS_URL is not set")
class WebhookNotice(unittest.TestCase):
    """Slack and Teams, at their own host names, which lead to mock_webhooks.py."""

    def notice(self, channel: str, url: str) -> tuple[str, dict]:
        """Report an incident to a team with this contact: the incident's id, and what was posted."""
        post("/reset", {"method": "RESET"})
        call(WEBHOOKS, "DELETE")
        post("/teams", {"Team_Name": "LEGAL", "Method": "NEW"})
        contact = {"Contact_Channel": channel, "Contact": url}
        post("/teams", {"Team_Name": "LEGAL", "Method": "ADD_CONTACT", **contact})

        add_dependency("Quillgate Server")
        incident_id = wait_for_incident("CVE-E2E-RECENT")["Incident_ID"]
        results = delivered(incident_id, 1)[0]["Details"]["results"]
        self.assertEqual([r["status"] for r in results], ["delivered"], results)
        posts = call(WEBHOOKS)
        self.assertEqual([f"https://{p['host']}{p['path']}" for p in posts], [url])
        return incident_id, posts[0]["body"]

    def test_an_incident_is_posted_to_slack(self):
        incident_id, body = self.notice("slack", "https://hooks.slack.com/services/T0/B0/e2e")
        header, section, actions = body["blocks"]
        self.assertIn("CVE-E2E-RECENT", header["text"]["text"])
        self.assertIn("Quillgate Server", section["text"]["text"])
        self.assertTrue(
            actions["elements"][0]["url"].endswith(f"/app/#/incidents/{incident_id}"), actions
        )

    def test_an_incident_is_posted_to_teams(self):
        # The query string holds a real webhook's signature, so it has to arrive unchanged
        url = "https://e2e.environment.api.powerplatform.com/workflows/abc?api-version=1&sig=e2e-_x"
        incident_id, body = self.notice("ms_teams", url)
        card = body["attachments"][0]["content"]
        texts = [block["text"] for block in card["body"]]
        self.assertIn("CVE-E2E-RECENT", texts[0])
        self.assertTrue(any("Quillgate Server" in text for text in texts), texts)
        self.assertTrue(
            card["actions"][0]["url"].endswith(f"/app/#/incidents/{incident_id}"), card["actions"]
        )
