"""Intake, incident info, edit, decision, log and 8-K view."""
import unittest

from tests.helpers import WebAppTestCase


class IntakeTests(WebAppTestCase):
    def test_intake_with_dependency_matches_spec_example(self):
        self.ok("POST", "/dependencies", {"dp_name": "auth-service-v2"})
        out = self.ok("POST", "/incidents", {
            "Incident_ID": "102356304331",
            "Description": "Critical API gateway timeout linked to third-party auth provider.",
            "Dependency_Name": "auth-service-v2",
            "Timestamp": "2026-09-25T20:00:00Z",
            "Severity": "HIGH",
            "Urgency": "URGENT",
        })
        self.assertEqual(out["Status"], "Created")
        self.assertEqual(out["Materiality"], "UNDECIDED")
        self.assertEqual(out["Dependency_Name"], "auth-service-v2")
        self.assertEqual(out["Intake_Ticket_ID"], "102356304331_1_1")

    def test_intake_generates_id_when_omitted(self):
        out = self.new_incident()
        self.assertRegex(out["Incident_ID"], r"^[0-9]{12}$")

    def test_intake_logs_audit_ticket_with_user(self):
        inc = self.new_incident()
        ticket = self.ok("GET", f"/incidents/{inc['Incident_ID']}/tickets/{inc['Incident_ID']}_1")
        self.assertIn("manual intake by dana", ticket["Ticket_Description"])

    def test_duplicate_id_is_uuid_exists(self):
        self.new_incident(Incident_ID="555")
        self.err("POST", "/incidents", {"Incident_ID": "555", "Description": "again"}, 400, "UUID_EXISTS")

    def test_unknown_dependency_is_dp_dne_with_completed_steps(self):
        data = self.err("POST", "/incidents", {"Description": "x", "Dependency_Name": "payroll-saas"}, 400, "DP_DNE")
        self.assertEqual(data["Core_Path"], "/dependencies")
        self.assertIn("Completed_Steps", data)

    def test_future_timestamp_rejected(self):
        self.err("POST", "/incidents", {"Description": "x", "Timestamp": "2099-01-01T00:00:00Z"}, 400, "INVALID_DATA")

    def test_description_over_5000_rejected(self):
        self.err("POST", "/incidents", {"Description": "x" * 5001}, 400, "INVALID_DATA")

    def test_bad_enum_rejected(self):
        data = self.err("POST", "/incidents", {"Description": "x", "Severity": "EXTREME"}, 400, "INVALID_DATA")
        self.assertIn("Severity", data["Message"])

    def test_unknown_field_rejected(self):
        self.err("POST", "/incidents", {"Description": "x", "Colour": "red"}, 400, "INVALID_DATA")

    def test_not_json_rejected(self):
        self.err("POST", "/incidents", b"{not json", 400, "INVALID_DATA")

    def test_sign_in_required(self):
        self.err("POST", "/incidents", {"Description": "x"}, 401, "UNAUTHORIZED", user=None)

    def test_unknown_user_rejected(self):
        self.err("GET", "/teams", None, 401, "UNAUTHORIZED", user="mallory")


class IncidentInfoTests(WebAppTestCase):
    def test_get_incident(self):
        inc = self.new_incident(Severity="LOW")
        out = self.ok("GET", f"/incidents/{inc['Incident_ID']}")
        self.assertEqual((out["Status"], out["Severity"]), ("Data Fetched", "LOW"))

    def test_get_unknown_incident_is_uuid_dne(self):
        data = self.err("GET", "/incidents/000000000001", None, 400, "UUID_DNE")
        self.assertEqual(data["Core_Path"], "/incidents")

    def test_bad_incident_id_format(self):
        self.err("GET", "/incidents/abc", None, 400, "INVALID_DATA")

    def test_list_and_filter(self):
        self.new_incident(Materiality="MATERIAL")
        self.new_incident()
        self.assertEqual(self.ok("GET", "/incidents")["total"], 2)
        only = self.ok("GET", "/incidents?Materiality=MATERIAL")
        self.assertEqual([i["Materiality"] for i in only["Incidents"]], ["MATERIAL"])

    def test_list_pagination_validated(self):
        self.err("GET", "/incidents?page_size=500", None, 400, "INVALID_DATA")

    def test_edit_description_and_dependency(self):
        self.ok("POST", "/dependencies", {"dp_name": "okta"})
        inc = self.new_incident()
        out = self.ok("PATCH", f"/incidents/{inc['Incident_ID']}", {"Description": "Updated", "Dependency_Name": "okta"})
        self.assertEqual((out["Status"], out["Description"], out["Dependency_Name"]), ("Edited", "Updated", "okta"))
        self.assertTrue(out["Audit_Ticket_ID"].endswith("_2_1"))

    def test_edit_rejects_decision_fields(self):
        inc = self.new_incident()
        self.err("PATCH", f"/incidents/{inc['Incident_ID']}", {"Materiality": "MATERIAL"}, 400, "INVALID_DATA")

    def test_edit_requires_a_field(self):
        inc = self.new_incident()
        self.err("PATCH", f"/incidents/{inc['Incident_ID']}", {}, 400, "INVALID_DATA")


class DecisionTests(WebAppTestCase):
    def test_material_decision_logs_and_notifies_all_teams(self):
        inc = self.new_incident()
        iid = inc["Incident_ID"]
        out = self.ok("PUT", f"/incidents/{iid}/decision", {"Materiality": "MATERIAL", "Severity": "HIGH", "Rationale": "Large impact"})
        self.assertEqual(out["Status"], "Decision Recorded")
        self.assertEqual(out["Notified_Teams"], ["LEGAL", "CYBER1", "CYBER2"])
        self.assertIsNone(out["Filing_Deadline"])
        self.assertEqual(self.ok("GET", f"/incidents/{iid}")["Materiality"], "MATERIAL")
        ticket = self.ok("GET", f"/incidents/{iid}/tickets/{out['Decision_Ticket_ID'].rsplit('_', 1)[0]}")
        self.assertIn("DECISION by dana", ticket["Ticket_Description"])
        self.assertIn("Large impact", ticket["Ticket_Description"])

    def test_repeat_material_decision_does_not_renotify(self):
        iid = self.new_incident(Materiality="MATERIAL")["Incident_ID"]
        out = self.ok("PUT", f"/incidents/{iid}/decision", {"Materiality": "MATERIAL", "Rationale": "Still material"})
        self.assertEqual(out["Notified_Teams"], [])

    def test_rationale_only_is_invalid(self):
        iid = self.new_incident()["Incident_ID"]
        self.err("PUT", f"/incidents/{iid}/decision", {"Rationale": "Reviewed."}, 400, "INVALID_DATA")

    def test_rationale_required(self):
        iid = self.new_incident()["Incident_ID"]
        self.err("PUT", f"/incidents/{iid}/decision", {"Materiality": "IMMATERIAL"}, 400, "INVALID_DATA")


class DecisionPermissionTests(WebAppTestCase):
    stack_settings = {"decision_teams": ["LEGAL"]}

    def test_non_member_forbidden(self):
        iid = self.new_incident()["Incident_ID"]
        self.err("PUT", f"/incidents/{iid}/decision", {"Materiality": "MATERIAL", "Rationale": "x"}, 403, "FORBIDDEN", user="alice")
        self.ok("PUT", f"/incidents/{iid}/decision", {"Materiality": "MATERIAL", "Rationale": "x"}, user="carol")


class LogAnd8kTests(WebAppTestCase):
    def test_log_lists_every_version_in_order(self):
        iid = self.new_incident()["Incident_ID"]
        self.ok("POST", f"/incidents/{iid}/tickets", {"Description": "Triage"})
        self.ok("PATCH", f"/incidents/{iid}/tickets/{iid}_2", {"Description": "Triage, updated"})
        log = self.ok("GET", f"/incidents/{iid}/log")
        self.assertEqual(log["Status"], "Log Retrieved")
        self.assertEqual(log["Ticket_ID_List"], [f"{iid}_1_1", f"{iid}_2_1", f"{iid}_2_2"])

    def test_log_entries_show_every_version(self):
        iid = self.new_incident()["Incident_ID"]
        self.ok("POST", f"/incidents/{iid}/tickets", {"Description": "Contain host", "Ticket_severity": "HIGH", "Team_list": ["CYBER1"]})
        self.ok("PATCH", f"/incidents/{iid}/tickets/{iid}_2", {"Description": "Host contained", "Ticket_severity": "LOW"})
        self.ok("PUT", f"/incidents/{iid}/decision", {"Materiality": "IMMATERIAL", "Rationale": "No data accessed"})
        out = self.ok("GET", f"/incidents/{iid}/log/entries")
        self.assertEqual(out["Status"], "Log Entries Retrieved")
        entries = out["Entries"]
        self.assertEqual([e["Ticket_ID"] for e in entries], self.ok("GET", f"/incidents/{iid}/log")["Ticket_ID_List"])
        self.assertTrue(all(e["Details_Available"] for e in entries))
        self.assertEqual([e["Entry_Type"] for e in entries], ["INTAKE", "TICKET", "TICKET", "DECISION"])
        v1, v2 = entries[1], entries[2]
        self.assertEqual((v1["Ticket_ID"], v1["Version"], v1["Ticket_Description"], v1["ticket_severity"]),
                         (f"{iid}_2_1", 1, "Contain host", "HIGH"))
        self.assertEqual((v2["Ticket_ID"], v2["Version"], v2["Ticket_Description"], v2["ticket_severity"]),
                         (f"{iid}_2_2", 2, "Host contained", "LOW"))
        self.assertEqual(v1["Team_List"], ["CYBER1"])
        self.assertIn("Timestamp", v1)

    def test_log_entries_fetch_each_version_from_the_core_api(self):
        iid = self.new_incident()["Incident_ID"]
        self.ok("POST", f"/incidents/{iid}/tickets", {"Description": "v1"})
        self.ok("PATCH", f"/incidents/{iid}/tickets/{iid}_2", {"Description": "v2"})
        self.stack.mock.request_log.clear()
        self.ok("GET", f"/incidents/{iid}/log/entries")
        gets = [e["body"]["Ticket_number"] for e in self.stack.mock.request_log if e["path"] == "/tickets"]
        self.assertEqual(gets, [f"{iid}_1_1", f"{iid}_2_1", f"{iid}_2_2"])

    def test_log_entries_unknown_incident(self):
        self.err("GET", "/incidents/000000000001/log/entries", None, 400, "UUID_DNE")
        self.err("GET", "/incidents/abc/log/entries", None, 400, "INVALID_DATA")

    def test_8k_rejected_when_not_material(self):
        iid = self.new_incident(Materiality="IMMATERIAL")["Incident_ID"]
        data = self.err("GET", f"/incidents/{iid}/form-8k", None, 400, "INVALID_DATA")
        self.assertIn("MATERIAL", data["Message"])

    def test_8k_view_sections(self):
        self.ok("POST", "/dependencies", {"dp_name": "auth-service-v2"})
        iid = self.new_incident(Description="Gateway outage", Dependency_Name="auth-service-v2",
                                Timestamp="2026-09-25T20:00:00Z")["Incident_ID"]
        self.ok("POST", f"/incidents/{iid}/tickets", {"Description": "Triage", "Team_list": ["CYBER1", "LEGAL"]})
        decision = self.ok("PUT", f"/incidents/{iid}/decision", {"Materiality": "MATERIAL", "Rationale": "Revenue impact"})
        view = self.ok("GET", f"/incidents/{iid}/form-8k")
        item = view["Item_1_05"]
        self.assertIn("Gateway outage", item["Nature"])
        self.assertIn("Triage", item["Nature"])
        self.assertNotIn("INTAKE", item["Nature"])
        self.assertEqual(item["Scope"]["Dependency_Name"], "auth-service-v2")
        self.assertEqual(item["Scope"]["Teams_Involved"], ["CYBER1", "LEGAL"])
        self.assertEqual(item["Timing"]["Discovered_At"], "2026-09-25T20:00:00.000Z")
        self.assertEqual(item["Timing"]["Determined_At"], decision["Determined_At"])
        self.assertEqual(item["Material_Impact"], "Revenue impact")
        self.assertEqual(len(view["Source_Tickets"]), 3)



class LogEntriesWithoutVersionLookupTests(WebAppTestCase):
    """A Core API that only supports GET by Ticket_type_weak (the current spec, gap G-7)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stack.mock.version_lookup = False

    def test_older_versions_marked_unavailable_latest_shown(self):
        iid = self.new_incident()["Incident_ID"]
        self.ok("POST", f"/incidents/{iid}/tickets", {"Description": "v1"})
        self.ok("PATCH", f"/incidents/{iid}/tickets/{iid}_2", {"Description": "v2"})
        entries = self.ok("GET", f"/incidents/{iid}/log/entries")["Entries"]
        self.assertEqual([(e["Ticket_ID"], e["Details_Available"]) for e in entries],
                         [(f"{iid}_1_1", True), (f"{iid}_2_1", False), (f"{iid}_2_2", True)])
        self.assertEqual(entries[2]["Ticket_Description"], "v2")
        self.assertNotIn("Ticket_Description", entries[1])

if __name__ == "__main__":
    unittest.main()
