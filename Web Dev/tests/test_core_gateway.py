"""Core API gateway: test clients call the Core API, which drives the Web App.

In these tests the mock Core API runs in gateway mode. Each test sends Core API
calls straight to the Core API (like the system's API test clients), then checks:
  - which Web App API requests the Core API generated (mock.forward_log),
  - that the Web App's own calls back to the Core API were stored, not forwarded
    again (no loop),
  - the Core-format response the test client received,
  - the resulting state, read back through the Web App.
"""
import unittest

from tests.helpers import Stack, WebAppTestCase, http

TS = "2026-09-25T20:00:00Z"


class GatewayTestCase(WebAppTestCase):
    forwarding = True

    def new_incident_via_core(self, incident_id="102356304331", **fields):
        body = {"Incident_ID": incident_id, "Method": "NEW", "Timestamp": TS, "Description": "Gateway incident"}
        body.update(fields)
        return self.core_ok("/incidents", body)

    def new_ticket_via_core(self, incident_id="102356304331", **fields):
        body = {"Incident_ID": incident_id, "Method": "NEW", "Timestamp": TS, "Description": "Gateway ticket"}
        body.update(fields)
        return self.core_ok("/tickets", body)


class IncidentGatewayTests(GatewayTestCase):
    def test_incident_new_becomes_web_app_intake(self):
        self.core_ok("/dependencies", {"dp_name": "auth-service-v2", "method": "NEW"})
        self.stack.mock.forward_log.clear()
        out = self.new_incident_via_core(Dependency="auth-service-v2", Severity="HIGH", Urgency="URGENT")
        self.assertEqual(self.forwarded(), ["POST /webapp/v1/incidents"])
        self.assertEqual(self.stack.mock.forward_log[0]["body"]["Dependency_Name"], "auth-service-v2")
        # Response is in Core format: "Dependency", no Web-App-only fields.
        self.assertEqual(out["Status"], "Created")
        self.assertEqual(out["Dependency"], "auth-service-v2")
        self.assertNotIn("Dependency_Name", out)
        self.assertNotIn("Intake_Ticket_ID", out)
        # The Web App really created it, and logged the intake as the gateway user.
        incident = self.ok("GET", "/incidents/102356304331")
        self.assertEqual((incident["Severity"], incident["Dependency_Name"]), ("HIGH", "auth-service-v2"))
        intake = self.ok("GET", "/incidents/102356304331/tickets/102356304331_1")
        self.assertIn("by core-gateway", intake["Ticket_Description"])

    def test_web_app_callbacks_are_stored_not_forwarded(self):
        self.new_incident_via_core()
        log = self.stack.mock.request_log
        external = [e for e in log if e["origin"] == "external"]
        from_webapp = [e for e in log if e["origin"] == "webapp"]
        self.assertEqual([(e["path"], e["forwarded"]) for e in external], [("/incidents", True)])
        self.assertEqual([f"{e['path']} {e['body']['Method']}" for e in from_webapp], ["/incidents NEW", "/tickets NEW"])
        self.assertTrue(all(not e["forwarded"] for e in from_webapp))
        self.assertEqual(len(self.stack.mock.forward_log), 1)

    def test_duplicate_incident_error_comes_back_in_core_format(self):
        self.new_incident_via_core()
        data = self.core_err("/incidents", {"Incident_ID": "102356304331", "Method": "NEW", "Timestamp": TS,
                                            "Description": "again"}, "UUID_EXISTS")
        self.assertIn("already exists", data["Message"])

    def test_incident_get(self):
        self.new_incident_via_core(Severity="LOW")
        self.stack.mock.forward_log.clear()
        out = self.core_ok("/incidents", {"Incident_ID": "102356304331", "Method": "GET", "Timestamp": TS, "Description": ""})
        self.assertEqual(self.forwarded(), ["GET /webapp/v1/incidents/102356304331"])
        self.assertEqual((out["Status"], out["Severity"]), ("Data Fetched", "LOW"))

    def test_unknown_incident_is_uuid_dne(self):
        self.core_err("/incidents", {"Incident_ID": "000000000001", "Method": "GET", "Timestamp": TS, "Description": ""}, "UUID_DNE")

    def test_materiality_edit_becomes_web_app_decision(self):
        self.new_incident_via_core()
        self.stack.mock.forward_log.clear()
        out = self.core_ok("/incidents", {"Incident_ID": "102356304331", "Method": "EDIT", "Timestamp": TS,
                                          "Description": "Gateway incident", "Materiality": "MATERIAL"})
        self.assertEqual(self.forwarded(), [
            "GET /webapp/v1/incidents/102356304331",
            "PUT /webapp/v1/incidents/102356304331/decision",
            "GET /webapp/v1/incidents/102356304331",
        ])
        self.assertEqual((out["Status"], out["Materiality"]), ("Edited", "MATERIAL"))
        # The Web App's decision workflow ran: audit ticket, all teams notified, 8-K view available.
        view = self.ok("GET", "/incidents/102356304331/form-8k")
        self.assertIn("Recorded through the Core API", view["Item_1_05"]["Material_Impact"])
        queue = self.ok("GET", "/queue?team=CYBER2")
        self.assertEqual([t["Ticket_number"] for t in queue["Tickets"]], ["102356304331_2"])

    def test_rationale_is_passed_to_the_decision(self):
        self.new_incident_via_core()
        self.core_ok("/incidents", {"Incident_ID": "102356304331", "Method": "EDIT", "Timestamp": TS,
                                    "Description": "Gateway incident", "Materiality": "MATERIAL",
                                    "Rationale": "Customer data exposed"})
        view = self.ok("GET", "/incidents/102356304331/form-8k")
        self.assertEqual(view["Item_1_05"]["Material_Impact"], "Customer data exposed")

    def test_description_edit_becomes_web_app_patch(self):
        self.new_incident_via_core()
        self.stack.mock.forward_log.clear()
        out = self.core_ok("/incidents", {"Incident_ID": "102356304331", "Method": "EDIT", "Timestamp": TS,
                                          "Description": "Updated description"})
        self.assertIn("PATCH /webapp/v1/incidents/102356304331", self.forwarded())
        self.assertNotIn("PUT /webapp/v1/incidents/102356304331/decision", self.forwarded())
        self.assertEqual(out["Description"], "Updated description")

    def test_list_incidents(self):
        self.new_incident_via_core("111")
        self.new_incident_via_core("222")
        out = self.core_ok("/incidents", {"Method": "LIST", "Timestamp": TS})
        self.assertEqual(sorted(i["Incident_ID"] for i in out["Incidents"]), ["111", "222"])


class TicketGatewayTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        self.new_incident_via_core()
        self.stack.mock.forward_log.clear()

    def test_ticket_new_get_edit(self):
        out = self.new_ticket_via_core(Team_list=["CYBER1"], Ticket_severity="HIGH")
        self.assertEqual(self.forwarded(), ["POST /webapp/v1/incidents/102356304331/tickets"])
        self.assertIs(self.stack.mock.forward_log[0]["body"]["Notify"], False, "Core NEW does not notify; /notifier does")
        self.assertEqual((out["Status"], out["Ticket_ID"]), ("Logged", "102356304331_2_1"))
        self.assertNotIn("Notified_Teams", out)

        got = self.core_ok("/tickets", {"Incident_ID": "102356304331", "Method": "GET", "Timestamp": TS,
                                        "Ticket_number": "102356304331_2"})
        self.assertEqual((got["Status"], got["ticket_severity"]), ("Displayed", "HIGH"))

        edited = self.core_ok("/tickets", {"Incident_ID": "102356304331", "Method": "EDIT", "Timestamp": TS,
                                           "Ticket_number": "102356304331_2", "Description": "v2"})
        self.assertEqual((edited["Status"], edited["Ticket_ID"]), ("Edited", "102356304331_2_2"))
        self.assertEqual(self.ok("GET", "/incidents/102356304331/tickets/102356304331_2")["Ticket_Description"], "v2")

    def test_ticket_get_by_version_id(self):
        self.new_ticket_via_core(Ticket_severity="HIGH")
        self.core_ok("/tickets", {"Incident_ID": "102356304331", "Method": "EDIT", "Timestamp": TS,
                                  "Ticket_number": "102356304331_2", "Description": "v2", "Ticket_severity": "LOW"})
        self.stack.mock.forward_log.clear()
        old = self.core_ok("/tickets", {"Incident_ID": "102356304331", "Method": "GET", "Timestamp": TS,
                                        "Ticket_number": "102356304331_2_1"})
        self.assertEqual(self.forwarded(), ["GET /webapp/v1/incidents/102356304331/log/entries"])
        self.assertEqual((old["Ticket_ID"], old["Ticket_Description"], old["ticket_severity"]),
                         ("102356304331_2_1", "Gateway ticket", "HIGH"))
        self.core_err("/tickets", {"Incident_ID": "102356304331", "Method": "GET", "Timestamp": TS,
                                   "Ticket_number": "102356304331_2_9"}, "UUID_DNE")

    def test_logs(self):
        self.new_ticket_via_core()
        self.stack.mock.forward_log.clear()
        out = self.core_ok("/logs", {"Incident_ID": "102356304331", "Timestamp": TS})
        self.assertEqual(self.forwarded(), ["GET /webapp/v1/incidents/102356304331/log"])
        self.assertEqual(out["Ticket_ID_List"], ["102356304331_1_1", "102356304331_2_1"])

    def test_web_app_validation_error_passes_through(self):
        data = self.core_err("/tickets", {"Incident_ID": "102356304331", "Method": "NEW", "Timestamp": TS,
                                          "Description": "x", "Team_list": ["MARKETING"]}, "INVALID_DATA")
        self.assertIn("MARKETING", data["Message"])

    def test_notify_then_claim(self):
        self.new_ticket_via_core()
        out = self.core_ok("/notifier", {"Team_Names": ["CYBER2"], "Method": "NOTIFY", "Ticket_Number": "102356304331_2"})
        self.assertEqual(out["Status"], "Notified team")
        self.assertEqual(len(self.ok("GET", "/queue?team=CYBER2")["Tickets"]), 1)

        out = self.core_ok("/notifier", {"Team_Names": ["CYBER2"], "Method": "CLAIM", "Ticket_Number": "102356304331_2"})
        self.assertEqual((out["Status"], out["UUID"]), ("Claimed ticket", 102356304331))
        self.assertIn("POST /webapp/v1/tickets/102356304331_2/claim", self.forwarded())
        claimed = self.ok("GET", "/queue?team=CYBER2&claim=CLAIMED")["Tickets"]
        self.assertEqual(claimed[0]["Claimed_By"], "CYBER2")
        self.core_err("/notifier", {"Team_Names": ["LEGAL"], "Method": "CLAIM", "Ticket_Number": "102356304331_2"}, "INVALID_DATA")

    def test_claim_by_two_teams_rejected_before_forwarding(self):
        self.new_ticket_via_core()
        self.stack.mock.forward_log.clear()
        self.core_err("/notifier", {"Team_Names": ["CYBER1", "CYBER2"], "Method": "CLAIM",
                                    "Ticket_Number": "102356304331_2"}, "INVALID_DATA")
        self.assertEqual(self.forwarded(), [])

    def test_queue_list(self):
        self.new_ticket_via_core(Team_list=["LEGAL"])
        out = self.core_ok("/tickets", {"Method": "LIST", "Timestamp": TS, "Team": "LEGAL", "Ticket_Claim": "UNCLAIMED"})
        self.assertEqual([t["Ticket_number"] for t in out["Tickets"]], ["102356304331_2"])


class DependencyAndResetGatewayTests(GatewayTestCase):
    def test_dependency_new_match_remove_list(self):
        self.assertEqual(self.core_ok("/dependencies", {"dp_name": "okta sso", "method": "NEW"})["status"], "Added")
        self.assertEqual(self.ok("GET", "/dependencies/okta%20sso")["status"], "Exists")
        self.assertEqual(self.core_ok("/dependencies", {"dp_name": "okta sso", "method": "MATCH"})["status"], "Exists")
        self.assertEqual(self.core_ok("/dependencies", {"dp_name": "*", "method": "LIST"})["Dependencies"], ["okta sso"])
        self.core_err("/dependencies", {"dp_name": "okta sso", "method": "NEW"}, "DP_EXISTS")
        self.assertEqual(self.core_ok("/dependencies", {"dp_name": "okta sso", "method": "REMOVE"})["status"], "Removed")
        self.assertEqual(self.forwarded(), [
            "POST /webapp/v1/dependencies",
            "GET /webapp/v1/dependencies/okta%20sso",
            "GET /webapp/v1/dependencies",
            "POST /webapp/v1/dependencies",
            "DELETE /webapp/v1/dependencies/okta%20sso",
        ])

    def test_invalid_core_request_is_rejected_before_forwarding(self):
        self.core_err("/incidents", {"Incident_ID": "1", "Method": "NEW", "Timestamp": TS, "Description": "x",
                                     "Severity": "EXTREME"}, "INVALID_DATA")
        self.core_err("/incidents", {"Incident_ID": "1", "Method": "NEW", "Timestamp": "2099-01-01T00:00:00Z",
                                     "Description": "x"}, "INVALID_DATA")
        self.assertEqual(self.forwarded(), [])

    def test_reset_is_handled_by_the_core_not_forwarded(self):
        self.new_incident_via_core()
        self.stack.mock.forward_log.clear()
        self.assertEqual(self.core_ok("/reset", {"method": "RESET"})["status"], "DB Wiped")
        self.assertEqual(self.forwarded(), [])
        self.err("GET", "/incidents/102356304331", None, 400, "UUID_DNE")


class GatewayWebAppDownTests(unittest.TestCase):
    def test_web_app_unreachable(self):
        stack = Stack(forwarding=True)
        try:
            stack.mock.webapp_url = "http://127.0.0.1:9"  # nothing listens there
            status, data = http("POST", f"{stack.settings.core_api_url}/dependencies", {"dp_name": "x", "method": "NEW"})
            self.assertEqual((status, data["Error"]), (400, "UPSTREAM_UNAVAILABLE"))
        finally:
            stack.close()


class LocalModeTests(WebAppTestCase):
    """Without a Web App URL the mock handles test-client calls itself (previous behaviour)."""

    def test_ticket_get_by_version_id_handled_locally(self):
        iid = self.new_incident()["Incident_ID"]
        self.ok("POST", f"/incidents/{iid}/tickets", {"Description": "v1"})
        self.ok("PATCH", f"/incidents/{iid}/tickets/{iid}_2", {"Description": "v2"})
        old = self.core_ok("/tickets", {"Incident_ID": iid, "Method": "GET", "Timestamp": TS, "Ticket_number": f"{iid}_2_1"})
        self.assertEqual((old["Ticket_ID"], old["Ticket_Description"]), (f"{iid}_2_1", "v1"))
        latest = self.core_ok("/tickets", {"Incident_ID": iid, "Method": "GET", "Timestamp": TS, "Ticket_number": f"{iid}_2"})
        self.assertEqual(latest["Ticket_ID"], f"{iid}_2_2")

    def test_external_call_handled_locally(self):
        out = self.core_ok("/dependencies", {"dp_name": "local-only", "method": "NEW"})
        self.assertEqual(out["status"], "Added")
        self.assertEqual(self.stack.mock.forward_log, [])
        self.assertEqual(self.ok("GET", "/dependencies/local-only")["status"], "Exists")


if __name__ == "__main__":
    unittest.main()
