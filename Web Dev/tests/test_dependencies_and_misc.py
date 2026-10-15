"""Dependencies, teams, extensions, static files and Core API failures."""
import socket
import unittest

from tests.helpers import Stack, WebAppTestCase, http


class DependencyTests(WebAppTestCase):
    def test_add_match_remove(self):
        self.assertEqual(self.ok("POST", "/dependencies", {"dp_name": "auth-service-v2"})["status"], "Added")
        self.err("POST", "/dependencies", {"dp_name": "auth-service-v2"}, 400, "DP_EXISTS")
        self.assertEqual(self.ok("GET", "/dependencies/auth-service-v2")["status"], "Exists")
        self.assertEqual(self.ok("GET", "/dependencies")["Dependencies"], ["auth-service-v2"])
        self.assertEqual(self.ok("DELETE", "/dependencies/auth-service-v2")["status"], "Removed")
        self.assertEqual(self.ok("GET", "/dependencies/auth-service-v2")["status"], "Does not Exist")
        self.err("DELETE", "/dependencies/auth-service-v2", None, 400, "DP_DNE")

    def test_names_with_spaces_are_url_decoded(self):
        self.ok("POST", "/dependencies", {"dp_name": "payroll saas"})
        self.assertEqual(self.ok("GET", "/dependencies/payroll%20saas")["status"], "Exists")


class MiscTests(WebAppTestCase):
    def test_teams(self):
        self.assertEqual(self.ok("GET", "/teams")["Teams"], ["LEGAL", "CYBER1", "CYBER2"])

    def test_session(self):
        out = self.ok("GET", "/session", user="alice")
        self.assertEqual((out["User"], out["Teams"], out["Can_Decide"]), ("alice", ["CYBER1"], True))

    def test_cookie_auth(self):
        status, data = http("GET", f"{self.stack.url}/webapp/v1/session", headers={"Cookie": "secheck_session=bob"})
        self.assertEqual((status, data["User"]), (200, "bob"))

    def test_dev_users_and_health_are_public(self):
        self.assertEqual(len(self.ok("GET", "/dev/users", user=None)["Users"]), 4)
        self.assertTrue(self.ok("GET", "/health", user=None)["Core_API_Reachable"])

    def test_unknown_path_and_method(self):
        self.err("GET", "/nope", None, 404, "NOT_FOUND")
        self.err("DELETE", "/teams", None, 405, "METHOD_NOT_ALLOWED")

    def test_static_app_and_openapi(self):
        status, _ = http("GET", f"{self.stack.url}/app/")
        self.assertEqual(status, 200)
        status, spec = http("GET", f"{self.stack.url}/openapi.json")
        self.assertEqual(spec["info"]["title"], "SEC-Check Web App API")
        status, _ = http("GET", f"{self.stack.url}/app/logo.png")
        self.assertEqual(status, 200)
        status, _ = http("GET", f"{self.stack.url}/app/../config/settings.json")
        self.assertNotEqual(status, 200)


class CoreUnavailableTests(unittest.TestCase):
    def test_upstream_unavailable_when_core_is_down(self):
        stack = Stack()
        try:
            with socket.socket() as s:  # find a port nothing listens on
                s.bind(("127.0.0.1", 0))
                dead = s.getsockname()[1]
            stack.app.core.base_url = f"http://127.0.0.1:{dead}"
            status, data = http("GET", f"{stack.url}/webapp/v1/incidents/123", headers={"X-User": "dana"})
            self.assertEqual((status, data["Error"]), (502, "UPSTREAM_UNAVAILABLE"))
            status, data = http("GET", f"{stack.url}/webapp/v1/health")
            self.assertFalse(data["Core_API_Reachable"])
        finally:
            stack.close()


if __name__ == "__main__":
    unittest.main()
