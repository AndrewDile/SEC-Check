"""Recording materiality decisions and the Form 8-K view."""
import unittest

from playwright.sync_api import expect

from ui_base import UITestCase


class Decisions(UITestCase):
    def setUp(self):
        super().setUp()
        self.iid = self.report_incident("Customer records exposed through a misconfigured bucket.")

    def record(self, materiality, rationale, severity=None, urgency=None):
        form = self.tid("decision-form")
        self.tid("decision-materiality", form).select_option(materiality)
        if severity:
            self.tid("decision-severity", form).select_option(severity)
        if urgency:
            self.tid("decision-urgency", form).select_option(urgency)
        self.tid("decision-rationale", form).fill(rationale)
        self.tid("decision-submit", form).click()

    def test_8k_view_needs_a_material_decision(self):
        expect(self.tid("incident-materiality")).to_have_text("Materiality undecided")
        expect(self.tid("open-8k")).to_be_disabled()

    def test_record_material_decision(self):
        self.record("MATERIAL", "Records of 40,000 customers exposed.", severity="HIGH", urgency="URGENT")
        self.expect_notice("Decision recorded")
        expect(self.tid("incident-materiality")).to_have_text("Material")
        expect(self.tid("incident-severity")).to_have_text("High")
        expect(self.tid("open-8k")).to_be_enabled()
        # The decision is kept as an audit entry in the ticket list and the Core API.
        expect(self.tid("ticket").filter(has_text="DECISION by alice")).to_have_count(1)
        stored = self.core.incident(self.iid)
        self.assertEqual((stored["Materiality"], stored["Severity"], stored["Urgency"]), ("MATERIAL", "HIGH", "URGENT"))

    def test_record_immaterial_decision(self):
        self.record("IMMATERIAL", "No customer data involved.", severity="LOW")
        self.expect_notice("Decision recorded")
        expect(self.tid("incident-materiality")).to_have_text("Immaterial")
        expect(self.tid("open-8k")).to_be_disabled()
        self.assertEqual(self.core.incident(self.iid)["Materiality"], "IMMATERIAL")

    def test_rationale_is_required(self):
        form = self.tid("decision-form")
        self.tid("decision-materiality", form).select_option("MATERIAL")
        self.tid("decision-submit", form).click()
        expect(self.tid("incident-materiality")).to_have_text("Materiality undecided")
        self.assertEqual(self.core.incident(self.iid)["Materiality"], "UNDECIDED")

    def test_8k_view_shows_the_decision(self):
        self.log_ticket("Bucket locked down and access logs pulled.", teams=["CYBER1"])
        self.record("MATERIAL", "Records of 40,000 customers exposed.", severity="HIGH")
        self.expect_notice("Decision recorded")
        self.tid("open-8k").click()
        view = self.tid("form-8k")
        expect(view).to_be_visible()
        expect(self.tid("8k-nature", view)).to_contain_text("misconfigured bucket")
        expect(self.tid("8k-scope", view)).to_contain_text("High")
        expect(self.tid("8k-scope", view)).to_contain_text("CYBER1")
        expect(self.tid("8k-impact", view)).to_contain_text("Records of 40,000 customers exposed.")
        expect(self.tid("8k-timing", view)).to_contain_text(self.iid + "_2")


if __name__ == "__main__":
    unittest.main()
