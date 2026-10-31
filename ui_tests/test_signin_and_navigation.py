"""Signing in and moving around the app."""
import unittest

from playwright.sync_api import expect

from ui_base import UITestCase


class SignedOut(UITestCase):
    user = None

    def test_asks_to_choose_a_user_first(self):
        self.page.goto("/app/")
        expect(self.tid("signin-prompt")).to_be_visible()
        expect(self.tid("new-incident")).to_have_count(0)

    def test_choosing_a_user_opens_the_incident_list(self):
        self.page.goto("/app/")
        self.tid("user-select").select_option("bob")
        expect(self.tid("signin-prompt")).to_have_count(0)
        expect(self.tid("new-incident")).to_be_visible()
        expect(self.tid("incidents-empty")).to_be_visible()

    def test_service_account_is_not_offered(self):
        self.page.goto("/app/")
        options = self.tid("user-select").locator("option")
        expect(options.filter(has_text="alice")).to_have_count(1)
        expect(options.filter(has_text="core-gateway")).to_have_count(0)


class SignedIn(UITestCase):
    def test_footer_shows_the_core_api_is_connected(self):
        expect(self.tid("core-status")).to_contain_text("Core API connected")

    def test_sign_in_is_remembered_after_reload(self):
        self.page.reload()
        expect(self.tid("user-select")).to_have_value("alice")
        expect(self.tid("new-incident")).to_be_visible()

    def test_navigation_links(self):
        self.tid("nav-dependencies").click()
        expect(self.tid("dep-add-form")).to_be_visible()
        expect(self.tid("nav-dependencies")).to_have_attribute("aria-current", "page")
        self.tid("nav-queue").click()
        expect(self.tid("queue-form")).to_be_visible()
        self.tid("nav-incidents").click()
        expect(self.tid("new-incident")).to_be_visible()


if __name__ == "__main__":
    unittest.main()
