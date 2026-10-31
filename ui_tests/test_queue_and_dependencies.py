"""The team queue and the dependency registry."""
import unittest

from playwright.sync_api import expect

from ui_base import UITestCase


class TeamQueue(UITestCase):
    def setUp(self):
        super().setUp()
        # alice (CYBER1) reports an incident and assigns a ticket to CYBER2...
        self.iid = self.report_incident("Suspicious logins on the VPN.")
        self.log_ticket("Review VPN logs for the last 30 days.", teams=["CYBER2"])
        self.number = self.iid + "_2"
        # ...and bob (CYBER2) picks it up from his team's queue.
        self.sign_in("bob")
        self.tid("nav-queue").click()

    def row(self):
        return self.page.locator('[data-testid="queue-row"][data-ticket-number="%s"]' % self.number)

    def test_assigned_ticket_is_in_the_team_queue(self):
        expect(self.tid("queue-team")).to_have_value("CYBER2")
        expect(self.row()).to_contain_text("Review VPN logs for the last 30 days.")

    def test_other_teams_queue_is_empty(self):
        self.tid("queue-team").select_option("LEGAL")
        self.tid("queue-submit").click()
        expect(self.tid("queue-empty")).to_be_visible()

    def test_claim_from_the_queue(self):
        self.row().get_by_test_id("queue-claim-button").click()
        self.expect_notice("Claimed %s for CYBER2" % self.number)
        expect(self.row()).to_have_count(0)                 # no longer unclaimed
        self.tid("queue-claim").select_option("CLAIMED")
        self.tid("queue-submit").click()
        expect(self.row()).to_contain_text("Claimed by CYBER2")
        self.assertEqual(self.core.ticket(self.iid, self.number).get("Claimed_By"), "CYBER2")

    def test_queue_links_to_the_incident(self):
        self.row().get_by_role("link").click()
        expect(self.tid("incident-id")).to_have_text(self.iid)


class Dependencies(UITestCase):
    def setUp(self):
        super().setUp()
        self.tid("nav-dependencies").click()

    def add(self, name):
        self.tid("dep-add-name").fill(name)
        self.tid("dep-add-submit").click()

    def row(self, name):
        return self.page.locator('[data-testid="dependency-row"][data-name="%s"]' % name)

    def test_add_a_dependency(self):
        expect(self.tid("dependencies-empty")).to_be_visible()
        self.add("okta sso")
        self.expect_notice("okta sso: Added")
        expect(self.row("okta sso")).to_be_visible()
        self.assertTrue(self.core.dependency_exists("okta sso"))

    def test_duplicate_is_rejected(self):
        self.add("okta sso")
        self.expect_notice("Added")
        self.add("okta sso")
        self.expect_notice("DP_EXISTS", kind="error")
        expect(self.row("okta sso")).to_have_count(1)

    def test_check_a_dependency(self):
        self.add("okta sso")
        self.expect_notice("Added")
        self.tid("dep-check-name").fill("okta sso")
        self.tid("dep-check-submit").click()
        expect(self.tid("dep-check-result")).to_have_text("okta sso: Exists.")
        self.tid("dep-check-name").fill("unknown vendor")
        self.tid("dep-check-submit").click()
        expect(self.tid("dep-check-result")).to_have_text("unknown vendor: Does not Exist.")

    def test_remove_needs_confirmation(self):
        self.add("okta sso")
        self.expect_notice("Added")
        remove = self.row("okta sso").get_by_test_id("dependency-remove")
        remove.click()
        expect(remove).to_have_text("Confirm remove")
        self.assertTrue(self.core.dependency_exists("okta sso"))   # not removed yet
        remove.click()
        self.expect_notice("Removed okta sso")
        expect(self.row("okta sso")).to_have_count(0)
        self.assertFalse(self.core.dependency_exists("okta sso"))

    def test_incident_can_be_linked_to_a_dependency(self):
        self.add("okta sso")
        self.expect_notice("Added")
        iid = self.report_incident("Identity provider outage.", dependency="okta sso")
        expect(self.tid("incident-dependency")).to_have_text("okta sso")
        self.assertEqual(self.core.incident(iid).get("Dependency"), "okta sso")


if __name__ == "__main__":
    unittest.main()
