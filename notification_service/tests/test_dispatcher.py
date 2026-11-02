"""How a notification reads, for a new incident and for newly matched dependencies."""

import unittest

from notification_service.dispatcher import render
from notification_service.models import Incident, MatchedDependency, NotificationRequest


def request(matches: list[tuple[str, str]], added: list[str] | None = None) -> NotificationRequest:
    incident = Incident(
        id="100",
        created_at="2026-10-01T00:00:00Z",
        company_id="default",
        source="cisa_kev",
        external_id="CVE-1",
        title="CVE-1: A bug",
        summary="A summary.",
        source_url="https://example.com/",
        published_at="2026-10-01T00:00:00Z",
        detected_at="2026-10-01T00:00:00Z",
        priority_hint="high",
        matched_dependencies=[
            MatchedDependency(
                dependency_id=name, vendor="Acme", product=name, confidence=level, reason="test"
            )
            for name, level in matches
        ],
    )
    return NotificationRequest(
        notification_id="100",
        incident=incident,
        claim_url="https://example.com/claim",
        recipients=[],
        added_dependency_ids=added or [],
    )


class Render(unittest.TestCase):
    def test_new_incident(self):
        message = render(request([("Widget", "high")]))
        self.assertEqual(message.subject, "[HIGH] Possible cybersecurity incident: CVE-1: A bug")
        self.assertTrue(message.body.startswith("CVE-1: A bug"))
        self.assertNotIn("already reported", message.body)

    def test_low_confidence_is_shown(self):
        self.assertIn("low confidence", render(request([("Widget", "low")])).body)

    def test_update_names_what_was_added_and_lists_everything(self):
        message = render(request([("Widget", "high"), ("Gadget", "low")], added=["Gadget"]))
        self.assertTrue(message.subject.startswith("Update: [HIGH]"))
        self.assertTrue(
            message.body.startswith(
                "This incident was already reported. It may now also affect: Gadget"
            )
        )
        self.assertIn("Acme Widget", message.body)
        self.assertIn("Acme Gadget", message.body)
