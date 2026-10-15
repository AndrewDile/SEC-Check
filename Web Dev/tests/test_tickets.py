"""Tickets, notify, claim and team queue."""
import unittest

from tests.helpers import WebAppTestCase


class TicketTests(WebAppTestCase):
    def setUp(self):
        super().setUp()
        self.iid = self.new_incident(Severity="HIGH", Urgency="URGENT")["Incident_ID"]

    def test_create_ticket_and_notify(self):
        out = self.ok("POST", f"/incidents/{self.iid}/tickets", {
            "Description": "Initial triage ticket logged for authentication failure.",
            "Ticket_severity": "HIGH", "Ticket_urgency": "URGENT", "Team_list": ["CYBER1", "LEGAL"],
        })
        self.assertEqual(out["Status"], "Logged")
        self.assertEqual(out["Ticket_ID"], f"{self.iid}_2_1")
        self.assertEqual(out["Notified_Teams"], ["CYBER1", "LEGAL"])
        self.assertEqual(out["uuid_severity"], "HIGH")

    def test_create_ticket_without_notify(self):
        out = self.ok("POST", f"/incidents/{self.iid}/tickets", {"Description": "Quiet", "Team_list": ["CYBER1"], "Notify": False})
        self.assertEqual(out["Notified_Teams"], [])

    def test_unknown_team_rejected(self):
        data = self.err("POST", f"/incidents/{self.iid}/tickets", {"Description": "x", "Team_list": ["MARKETING"]}, 400, "INVALID_DATA")
        self.assertIn("MARKETING", data["Message"])

    def test_ticket_on_unknown_incident(self):
        self.err("POST", "/incidents/000000000001/tickets", {"Description": "x"}, 400, "UUID_DNE")

    def test_list_tickets_expanded(self):
        self.ok("POST", f"/incidents/{self.iid}/tickets", {"Description": "A"})
        out = self.ok("GET", f"/incidents/{self.iid}/tickets?expand=true")
        self.assertEqual(len(out["Tickets"]), 2)
        self.assertNotIn("Tickets", self.ok("GET", f"/incidents/{self.iid}/tickets"))

    def test_ticket_must_belong_to_incident(self):
        other = self.new_incident()["Incident_ID"]
        self.err("GET", f"/incidents/{self.iid}/tickets/{other}_1", None, 400, "INVALID_DATA")

    def test_bad_ticket_number_format(self):
        self.err("GET", f"/incidents/{self.iid}/tickets/abc", None, 400, "INVALID_DATA")

    def test_edit_creates_new_version(self):
        self.ok("POST", f"/incidents/{self.iid}/tickets", {"Description": "v1", "Team_list": ["CYBER1"]})
        out = self.ok("PATCH", f"/incidents/{self.iid}/tickets/{self.iid}_2", {"Description": "v2", "Ticket_severity": "LOW"})
        self.assertEqual((out["Ticket_ID"], out["Ticket_Description"], out["ticket_severity"]), (f"{self.iid}_2_2", "v2", "LOW"))
        self.assertEqual(out["Team_List"], ["CYBER1"])

    def test_edit_requires_description(self):
        self.ok("POST", f"/incidents/{self.iid}/tickets", {"Description": "v1"})
        self.err("PATCH", f"/incidents/{self.iid}/tickets/{self.iid}_2", {"Ticket_severity": "LOW"}, 400, "INVALID_DATA")


class ClaimAndQueueTests(WebAppTestCase):
    def setUp(self):
        super().setUp()
        self.iid = self.new_incident()["Incident_ID"]
        self.ok("POST", f"/incidents/{self.iid}/tickets", {"Description": "Contain", "Team_list": ["CYBER1"]})
        self.number = f"{self.iid}_2"

    def test_claim(self):
        out = self.ok("POST", f"/tickets/{self.number}/claim", {"Team_Name": "CYBER1"}, user="alice")
        self.assertEqual((out["Status"], out["Ticket_Number"], out["UUID"]), ("Claimed ticket", self.number, self.iid))

    def test_claim_by_non_member_forbidden(self):
        self.err("POST", f"/tickets/{self.number}/claim", {"Team_Name": "LEGAL"}, 403, "FORBIDDEN", user="alice")

    def test_second_claim_rejected(self):
        self.ok("POST", f"/tickets/{self.number}/claim", {"Team_Name": "CYBER1"}, user="alice")
        data = self.err("POST", f"/tickets/{self.number}/claim", {"Team_Name": "CYBER2"}, 400, "INVALID_DATA", user="bob")
        self.assertIn("already claimed", data["Message"])

    def test_claim_unknown_ticket(self):
        self.err("POST", f"/tickets/{self.iid}_99/claim", {"Team_Name": "CYBER1"}, 400, "UUID_DNE", user="alice")

    def test_notify_requires_teams(self):
        self.err("POST", f"/tickets/{self.number}/notify", {"Team_Names": []}, 400, "INVALID_DATA")
        out = self.ok("POST", f"/tickets/{self.number}/notify", {"Team_Names": ["CYBER2"]})
        self.assertEqual(out["Status"], "Notified team")

    def test_queue_moves_from_unclaimed_to_claimed(self):
        unclaimed = self.ok("GET", "/queue?team=CYBER1")
        self.assertEqual([t["Ticket_number"] for t in unclaimed["Tickets"]], [self.number])
        self.assertIsNotNone(unclaimed["Tickets"][0]["Notified_At"])
        self.ok("POST", f"/tickets/{self.number}/claim", {"Team_Name": "CYBER1"}, user="alice")
        self.assertEqual(self.ok("GET", "/queue?team=CYBER1")["Tickets"], [])
        claimed = self.ok("GET", "/queue?team=CYBER1&claim=CLAIMED")
        self.assertEqual(claimed["Tickets"][0]["Claimed_By"], "CYBER1")

    def test_notified_team_sees_ticket(self):
        self.assertEqual(self.ok("GET", "/queue?team=CYBER2")["Tickets"], [])
        self.ok("POST", f"/tickets/{self.number}/notify", {"Team_Names": ["CYBER2"]})
        self.assertEqual(len(self.ok("GET", "/queue?team=CYBER2")["Tickets"]), 1)

    def test_queue_requires_team(self):
        self.err("GET", "/queue", None, 400, "INVALID_DATA")
        self.err("GET", "/queue?team=MARKETING", None, 400, "INVALID_DATA")


if __name__ == "__main__":
    unittest.main()
