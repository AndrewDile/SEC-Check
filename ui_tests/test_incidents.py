"""Reporting, finding and editing incidents."""

import unittest

from playwright.sync_api import expect
from ui_base import UITestCase, now


class ReportIncident(UITestCase):
    def test_report_an_incident_with_all_fields(self):
        iid = self.report_incident(
            "Ransomware encrypted the billing database.",
            materiality="MATERIAL",
            severity="HIGH",
            urgency="URGENT",
        )
        # The detail page shows what was entered...
        expect(self.tid("incident-materiality")).to_have_text("Material")
        expect(self.tid("incident-severity")).to_have_text("High")
        expect(self.tid("incident-urgency")).to_have_text("Urgent")
        expect(self.tid("incident-description")).to_have_text(
            "Ransomware encrypted the billing database."
        )
        # ...the intake was logged as the first ticket...
        expect(self.ticket_item(iid + "_1")).to_contain_text("INTAKE")
        # ...and the Core API stored it.
        stored = self.core.incident(iid)
        self.assertEqual(
            (stored["Materiality"], stored["Severity"], stored["Urgency"]),
            ("MATERIAL", "HIGH", "URGENT"),
        )
        self.assertEqual(stored["Description"], "Ransomware encrypted the billing database.")

    def test_chosen_incident_id_is_used(self):
        iid = self.report_incident("Phishing email reported.", incident_id="555000111222")
        self.assertEqual(iid, "555000111222")
        self.assertEqual(
            self.core.incident("555000111222")["Description"], "Phishing email reported."
        )

    def test_incident_ids_like_the_core_api_accepts(self):
        """Any 1-64 characters, not just digits: letters, '_', '-' and spaces."""
        iid = self.report_incident("Vendor breach reported.", incident_id="INC_2026-11 a")
        self.assertEqual(iid, "INC_2026-11 a")
        self.log_ticket("Ask the vendor for logs.", teams=["CYBER1"])
        number = iid + "_2"  # _1 is the intake audit ticket
        expect(self.ticket_item(number)).to_contain_text("Ask the vendor for logs.")
        item = self.ticket_item(number)
        item.get_by_test_id("claim-team").select_option("CYBER1")
        item.get_by_test_id("claim-submit").click()
        self.expect_notice("for CYBER1")
        self.assertEqual(self.core.ticket(iid, number).get("Claimed_By"), "CYBER1")
        # Opening it by ID works too
        self.go("#/incidents")
        self.tid("open-id").fill(iid)
        self.tid("open-id").press("Enter")
        expect(self.tid("incident-id")).to_have_text(iid)

    def test_incident_created_through_the_core_api_opens(self):
        """An ID another system gave the Core API, like 'incident_859866259523'."""
        iid = "incident_859866259523"
        self.core.ok(
            "/incidents",
            {
                "Incident_ID": iid,
                "Method": "NEW",
                "Timestamp": now(),
                "Description": "Created by another system.",
            },
        )
        self.go("#/incidents")
        self.tid("incident-link").filter(has_text=iid).click()
        expect(self.tid("incident-id")).to_have_text(iid)
        expect(self.tid("incident-description")).to_have_text("Created by another system.")

    def test_description_is_required(self):
        self.tid("new-incident").click()
        self.tid("intake-submit").click()
        # The browser blocks the empty form: still on the list, nothing stored.
        expect(self.tid("intake-form")).to_be_visible()
        self.assertEqual(self.page.evaluate("location.hash"), "")
        self.assertEqual(self.core.incidents(), [])

    def test_cancel_hides_the_form(self):
        self.tid("new-incident").click()
        expect(self.tid("intake-form")).to_be_visible()
        self.tid("intake-cancel").click()
        expect(self.tid("intake-form")).to_be_hidden()

    def test_long_description_is_shortened_with_show_more(self):
        text = "Very long description. " * 120
        self.report_incident(text)
        description = self.tid("incident-description")
        toggle = self.page.get_by_role("button", name="Show more").first
        expect(toggle).to_be_visible()
        box_before = description.bounding_box()
        toggle.click()
        expect(self.page.get_by_role("button", name="Show less").first).to_be_visible()
        self.assertGreater(description.bounding_box()["height"], box_before["height"])


class FindIncident(UITestCase):
    def test_incident_appears_in_the_list_and_opens(self):
        iid = self.report_incident("Laptop stolen from a car.")
        self.tid("back-to-incidents").click()
        row = self.tid("incident-row").filter(has_text="Laptop stolen from a car.")
        expect(row).to_have_count(1)
        expect(row).to_contain_text(iid)
        row.click()
        expect(self.tid("incident-id")).to_have_text(iid)

    def test_list_shows_incidents_created_through_the_core_api(self):
        self.core.ok(
            "/incidents",
            {
                "Incident_ID": "111222333444",
                "Method": "NEW",
                "Timestamp": "2026-10-01T12:00:00Z",
                "Description": "Reported by the ingestion worker.",
            },
        )
        self.page.reload()
        expect(
            self.tid("incident-row").filter(has_text="Reported by the ingestion worker.")
        ).to_have_count(1)

    def test_open_by_id(self):
        iid = self.report_incident("Open me by ID.")
        self.go("#/incidents")
        self.tid("open-id").fill(iid)
        self.tid("open-submit").click()
        expect(self.tid("incident-description")).to_have_text("Open me by ID.")

    def test_unknown_id_shows_an_error(self):
        self.tid("open-id").fill("999999999999")
        self.tid("open-submit").click()
        self.expect_notice("UUID_DNE", kind="error")


class EditIncident(UITestCase):
    def test_edit_description_and_dependency(self):
        self.core.ok("/dependencies", {"dp_name": "okta sso", "method": "NEW"})
        iid = self.report_incident("First description.")
        self.tid("edit-toggle").click()
        self.tid("edit-description").fill("Corrected description.")
        self.tid("edit-dependency").fill("okta sso")
        self.tid("edit-submit").click()
        self.expect_notice("Details saved")
        expect(self.tid("incident-description")).to_have_text("Corrected description.")
        expect(self.tid("incident-dependency")).to_have_text("okta sso")
        stored = self.core.incident(iid)
        self.assertEqual(stored["Description"], "Corrected description.")
        self.assertEqual(stored.get("Dependency"), "okta sso")

    def test_unregistered_dependency_is_rejected(self):
        iid = self.report_incident("Linked to an unknown vendor.")
        self.tid("edit-toggle").click()
        self.tid("edit-dependency").fill("never-registered")
        self.tid("edit-submit").click()
        self.expect_notice("DP_DNE", kind="error")
        self.assertIsNone(self.core.incident(iid).get("Dependency"))

    def test_saving_without_changes(self):
        self.report_incident("Nothing to change.")
        self.tid("edit-toggle").click()
        self.tid("edit-submit").click()
        self.expect_notice("Nothing changed")


if __name__ == "__main__":
    unittest.main()
