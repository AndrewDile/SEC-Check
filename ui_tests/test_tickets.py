"""Logging, updating, notifying and claiming tickets on an incident's page."""

import unittest

from playwright.sync_api import expect
from ui_base import UITestCase


class Tickets(UITestCase):
    def setUp(self):
        super().setUp()
        self.iid = self.report_incident("Credential stuffing against the customer portal.")
        self.number = self.iid + "_2"  # _1 is the intake entry

    def test_log_a_ticket(self):
        self.log_ticket(
            "Lock the affected accounts.",
            severity="HIGH",
            urgency="URGENT",
            teams=["CYBER1", "LEGAL"],
        )
        self.expect_notice("notified")
        item = self.ticket_item(self.number)
        expect(item.get_by_test_id("ticket-body")).to_have_text("Lock the affected accounts.")
        expect(item.get_by_test_id("ticket-severity-tag")).to_have_text("Severity: High")
        expect(item.get_by_test_id("ticket-urgency-tag")).to_have_text("Urgency: Urgent")
        expect(item.get_by_test_id("ticket-claim")).to_have_text("Unclaimed")
        stored = self.core.ticket(self.iid, self.number)
        self.assertEqual(stored["Ticket_Description"], "Lock the affected accounts.")
        self.assertEqual((stored["ticket_severity"], stored["ticket_urgency"]), ("HIGH", "URGENT"))
        self.assertEqual(sorted(stored["Team_List"]), ["CYBER1", "LEGAL"])

    def test_ticket_details_are_required(self):
        self.tid("ticket-submit").click()
        expect(self.tid("ticket-form")).to_be_visible()
        self.assertEqual(len(self.core.log(self.iid)), 1)  # only the intake entry

    def test_update_a_ticket_adds_a_version(self):
        self.log_ticket("First assessment.", severity="LOW", teams=["CYBER1"])
        item = self.ticket_item(self.number)
        item.get_by_test_id("update-toggle").click()
        item.get_by_test_id("update-description").fill("Revised assessment: wider than thought.")
        item.get_by_test_id("update-severity").select_option("HIGH")
        item.get_by_test_id("update-submit").click()
        self.expect_notice("new version %s_2" % self.number)
        item = self.ticket_item(self.number)
        expect(item.get_by_test_id("ticket-body")).to_have_text(
            "Revised assessment: wider than thought."
        )
        expect(item.get_by_test_id("ticket-severity-tag")).to_have_text("Severity: High")
        stored = self.core.ticket(self.iid, self.number)
        self.assertEqual(stored["Ticket_ID"], self.number + "_2")
        self.assertEqual(stored["Team_List"], ["CYBER1"])  # kept from version 1

    def test_full_log_lists_every_version(self):
        self.log_ticket("Version one.")
        item = self.ticket_item(self.number)
        item.get_by_test_id("update-toggle").click()
        item.get_by_test_id("update-description").fill("Version two.")
        item.get_by_test_id("update-submit").click()
        self.expect_notice("new version")
        self.tid("full-log-toggle").click()
        entries = self.tid("log-entry")
        expect(entries).to_have_count(3)
        expect(entries.nth(0)).to_have_attribute("data-ticket-id", self.iid + "_1_1")
        expect(entries.nth(1)).to_have_attribute("data-ticket-id", self.number + "_1")
        expect(entries.nth(2)).to_have_attribute("data-ticket-id", self.number + "_2")
        expect(entries.nth(1)).to_contain_text("Version one.")
        expect(entries.nth(2)).to_contain_text("Version two.")
        self.assertEqual(
            self.core.log(self.iid), [self.iid + "_1_1", self.number + "_1", self.number + "_2"]
        )

    def test_notify_teams_about_a_ticket(self):
        self.log_ticket("Needs legal review.", notify=False)
        item = self.ticket_item(self.number)
        item.get_by_test_id("notify-toggle").click()
        item.get_by_test_id("notify-form").get_by_test_id("team-LEGAL").check()
        item.get_by_test_id("notify-submit").click()
        self.expect_notice("Notified LEGAL about %s" % self.number)

    def test_claim_a_ticket(self):
        self.log_ticket("Contain the portal.", teams=["CYBER1"])
        item = self.ticket_item(self.number)
        expect(item.get_by_test_id("claim-team")).to_have_value("CYBER1")  # alice is in CYBER1
        item.get_by_test_id("claim-submit").click()
        self.expect_notice("for CYBER1")
        item = self.ticket_item(self.number)
        expect(item.get_by_test_id("ticket-claim")).to_have_text("Claimed by CYBER1")
        expect(item.get_by_test_id("claim-form")).to_have_count(0)
        stored = self.core.ticket(self.iid, self.number)
        self.assertEqual((stored["Ticket_Claim"], stored.get("Claimed_By")), ("CLAIMED", "CYBER1"))

    def test_audit_entries_have_no_ticket_actions(self):
        intake = self.ticket_item(self.iid + "_1")
        expect(intake).to_contain_text("INTAKE")
        expect(intake.get_by_test_id("claim-form")).to_have_count(0)
        expect(intake.get_by_test_id("update-form")).to_have_count(0)


if __name__ == "__main__":
    unittest.main()
