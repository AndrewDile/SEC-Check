"""Creating teams and managing their members (Teams page), and using new teams elsewhere.

Teams and their members are stored by the Core API database (/teams). Every test starts
from the default teams and memberships, which the Core API's /reset puts back.
"""

import json
import unittest
import urllib.error
import urllib.parse
import urllib.request

from playwright.sync_api import expect
from ui_base import WEB_URL, Core, UITestCase


def web(method, path, body=None, user="alice"):
    """Call the Web App API directly (no browser) and return (status, body)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        WEB_URL + "/webapp/v1" + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-User": user},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def team_path(team, *rest):
    return "/teams/" + "/".join(urllib.parse.quote(p, safe="") for p in (team, *rest))


class TeamsPage(UITestCase):
    def setUp(self):
        super().setUp()
        self.tid("nav-teams").click()
        expect(self.tid("team-create-form")).to_be_visible()

    def card(self, team):
        return self.page.locator('[data-testid="team-card"][data-team="%s"]' % team)

    def member(self, team, user):
        return self.card(team).locator('[data-testid="team-member"][data-user="%s"]' % user)

    def create(self, name):
        self.tid("team-create-name").fill(name)
        self.tid("team-create-submit").click()

    def add_member(self, team, user):
        card = self.card(team)
        self.tid("team-add-user", card).select_option(user)
        self.tid("team-add-submit", card).click()
        self.expect_notice("Added %s to %s." % (user, team))

    # ------------------------------------------------------------------ the page
    def test_lists_existing_teams_and_members(self):
        self.assertEqual(self.page.title(), "Teams – SEC-Check")
        expect(self.tid("nav-teams")).to_have_attribute("aria-current", "page")
        expect(self.tid("team-card")).to_have_count(3)
        expect(self.member("CYBER1", "alice")).to_be_visible()
        expect(self.member("CYBER1", "dana")).to_be_visible()
        expect(self.member("CYBER2", "bob")).to_be_visible()
        # Service accounts aren't shown or offered
        expect(self.page.locator('[data-user="core-gateway"]')).to_have_count(0)

    # ------------------------------------------------------------------ create
    def test_create_a_team(self):
        self.create("Incident Response")
        self.expect_notice("Created team Incident Response.")
        card = self.card("Incident Response")
        expect(card).to_be_visible()
        expect(self.tid("team-no-members", card)).to_be_visible()
        expect(self.tid("team-name", card)).to_be_focused()  # focus moves to the new team
        self.assertIn("Incident Response", self.core.ok("/teams", {"Method": "LIST"})["Team_List"])

    def test_duplicate_team_is_rejected(self):
        self.create("CYBER1")
        self.expect_notice("TEAM_EXISTS", kind="error")
        expect(self.tid("team-card")).to_have_count(3)

    def test_team_name_is_required(self):
        self.tid("team-create-submit").click()  # the browser blocks the empty form
        expect(self.tid("team-card")).to_have_count(3)
        self.assertEqual(len(self.core.ok("/teams", {"Method": "LIST"})["Team_List"]), 3)

    # ------------------------------------------------------------------ members
    def test_add_and_remove_members(self):
        self.create("Forensics")
        self.expect_notice("Created")
        self.add_member("Forensics", "bob")
        self.add_member("Forensics", "carol")
        expect(self.card("Forensics").get_by_test_id("team-member")).to_have_count(2)
        # The sign-in picker shows bob's teams, including the new one
        expect(self.tid("user-select").locator('option[value="bob"]')).to_have_text(
            "bob (CYBER2, Forensics)"
        )
        self.member("Forensics", "bob").get_by_test_id("team-member-remove").click()
        self.expect_notice("Removed bob from Forensics.")
        expect(self.member("Forensics", "bob")).to_have_count(0)
        expect(self.member("Forensics", "carol")).to_be_visible()
        expect(self.tid("team-name", self.card("Forensics"))).to_be_focused()

    def test_only_non_members_are_offered(self):
        options = self.tid("team-add-user", self.card("CYBER2")).locator("option")
        expect(options).to_have_text(["alice", "carol", "dana"])

    def test_remove_buttons_say_who_and_where(self):
        button = self.member("CYBER1", "alice").get_by_test_id("team-member-remove")
        expect(button).to_have_attribute("aria-label", "Remove alice from CYBER1")

    def test_memberships_survive_a_reload(self):
        self.add_member("LEGAL", "alice")
        self.page.reload()
        expect(self.member("LEGAL", "alice")).to_be_visible()

    # ------------------------------------------------------------------ remove
    def test_remove_needs_confirmation(self):
        self.create("Temporary")
        self.expect_notice("Created")
        remove = self.card("Temporary").get_by_test_id("team-remove")
        remove.click()
        expect(remove).to_have_text("Confirm remove")
        expect(self.tid("announcer")).to_have_text("Press Confirm remove to remove team Temporary.")
        self.assertIn("Temporary", self.core.ok("/teams", {"Method": "LIST"})["Team_List"])
        remove.click()
        self.expect_notice("Removed team Temporary.")
        expect(self.card("Temporary")).to_have_count(0)
        self.assertNotIn("Temporary", self.core.ok("/teams", {"Method": "LIST"})["Team_List"])

    def test_removed_team_comes_back_without_members(self):
        self.create("Rotating")
        self.expect_notice("Created")
        self.add_member("Rotating", "dana")
        remove = self.card("Rotating").get_by_test_id("team-remove")
        remove.click()
        remove.click()
        self.expect_notice("Removed team Rotating.")
        self.create("Rotating")
        self.expect_notice("Created")
        expect(self.tid("team-no-members", self.card("Rotating"))).to_be_visible()

    def test_team_used_by_a_ticket_cant_be_removed(self):
        self.create("Vendor Liaison")
        self.expect_notice("Created")
        self.report_incident("Supplier breach.")
        self.log_ticket("Ask the supplier for details.", teams=["Vendor Liaison"])
        self.tid("nav-teams").click()
        remove = self.card("Vendor Liaison").get_by_test_id("team-remove")
        remove.click()
        remove.click()
        self.expect_notice("used by existing tickets", kind="error")
        expect(self.card("Vendor Liaison")).to_be_visible()


class NewTeamsElsewhere(UITestCase):
    """A team created on the Teams page works like the starting teams everywhere else."""

    def setUp(self):
        super().setUp()
        self.tid("nav-teams").click()
        self.tid("team-create-name").fill("Red Team")
        self.tid("team-create-submit").click()
        self.expect_notice("Created team Red Team.")

    def test_assign_notify_and_claim_with_a_new_team(self):
        card = self.page.locator('[data-testid="team-card"][data-team="Red Team"]')
        self.tid("team-add-user", card).select_option("alice")
        self.tid("team-add-submit", card).click()
        self.expect_notice("Added alice to Red Team.")
        iid = self.report_incident("Red team found an exposed admin panel.")
        self.log_ticket("Close the admin panel.", teams=["Red Team"])
        self.expect_notice("notified Red Team")
        number = iid + "_2"
        item = self.ticket_item(number)
        expect(item).to_contain_text("Red Team")
        # alice is now in CYBER1 and Red Team, so both are offered for claiming
        expect(item.get_by_test_id("claim-team").locator("option")).to_have_text(
            ["CYBER1", "Red Team"]
        )
        item.get_by_test_id("claim-team").select_option("Red Team")
        item.get_by_test_id("claim-submit").click()
        self.expect_notice("for Red Team")
        expect(self.ticket_item(number).get_by_test_id("ticket-claim")).to_have_text(
            "Claimed by Red Team"
        )
        self.assertEqual(self.core.ticket(iid, number).get("Claimed_By"), "Red Team")

    def test_new_team_has_a_queue(self):
        iid = self.report_incident("Phishing campaign.")
        self.log_ticket("Run the phishing simulation debrief.", teams=["Red Team"])
        self.tid("nav-queue").click()
        self.tid("queue-team").select_option("Red Team")
        self.tid("queue-submit").click()
        row = self.page.locator('[data-testid="queue-row"][data-ticket-number="%s_2"]' % iid)
        expect(row).to_contain_text("Run the phishing simulation debrief.")

    def test_material_decision_notifies_new_teams_too(self):
        self.report_incident("Customer data exposed.")
        form = self.tid("decision-form")
        self.tid("decision-materiality", form).select_option("MATERIAL")
        self.tid("decision-rationale", form).fill("Customer data.")
        self.tid("decision-submit", form).click()
        self.expect_notice("notified LEGAL, CYBER1, CYBER2, Red Team")


class TeamMembershipRules(unittest.TestCase):
    """The Web App API's team routes, checked directly (no browser)."""

    def setUp(self):
        Core().reset()

    def test_create_and_list(self):
        status, body = web("POST", "/teams", {"Team_Name": "Audit"})
        self.assertEqual((status, body["Status"], body["Members"]), (201, "Created", []))
        self.assertIn("Audit", web("GET", "/teams")[1]["Teams"])

    def test_invalid_names(self):
        for name in ("", "   ", " padded", "x" * 65):
            status, body = web("POST", "/teams", {"Team_Name": name})
            self.assertEqual((status, body["Error"]), (400, "INVALID_DATA"), repr(name))
        self.assertEqual(web("POST", "/teams", {})[1]["Error"], "INVALID_DATA")

    def test_member_errors(self):
        self.assertEqual(
            web("POST", team_path("NOPE", "members"), {"User": "bob"})[1]["Error"], "TEAM_DNE"
        )
        self.assertEqual(
            web("POST", team_path("LEGAL", "members"), {"User": "zed"})[1]["Error"], "USER_DNE"
        )
        self.assertEqual(
            web("POST", team_path("LEGAL", "members"), {"User": "core-gateway"})[1]["Error"],
            "USER_DNE",  # service accounts can't be added
        )
        self.assertEqual(
            web("POST", team_path("LEGAL", "members"), {"User": "carol"})[1]["Error"],
            "INVALID_DATA",  # already a member
        )
        self.assertEqual(
            web("DELETE", team_path("LEGAL", "members", "bob"))[1]["Error"], "INVALID_DATA"
        )
        self.assertEqual(web("DELETE", team_path("NOPE"))[1]["Error"], "TEAM_DNE")

    def test_membership_decides_who_can_claim(self):
        web("DELETE", team_path("CYBER1", "members", "alice"))
        self.assertEqual(web("GET", "/session")[1]["Teams"], [])
        web("POST", team_path("LEGAL", "members"), {"User": "alice"})
        self.assertEqual(web("GET", "/session")[1]["Teams"], ["LEGAL"])

    def test_teams_unknown_to_the_core_api_are_rejected_on_tickets(self):
        core = Core()
        incident = {
            "Incident_ID": "321321321321",
            "Method": "NEW",
            "Timestamp": "2026-10-01T12:00:00Z",
        }
        core.ok("/incidents", dict(incident, Description="x"))
        status, body = web(
            "POST", "/incidents/321321321321/tickets", {"Description": "x", "Team_list": ["Ghost"]}
        )
        self.assertEqual((status, body["Error"]), (400, "INVALID_DATA"))
        self.assertIn("Ghost", body["Message"])

    def test_names_with_spaces_and_symbols_work_in_paths(self):
        name = "R&D / Labs"
        self.assertEqual(web("POST", "/teams", {"Team_Name": name})[0], 201)
        self.assertEqual(web("POST", team_path(name, "members"), {"User": "dana"})[0], 200)
        teams = {t["Team_Name"]: t["Members"] for t in web("GET", "/team-members")[1]["Teams"]}
        self.assertEqual(teams[name], ["dana"])
        self.assertEqual(web("DELETE", team_path(name))[0], 200)


if __name__ == "__main__":
    unittest.main()
