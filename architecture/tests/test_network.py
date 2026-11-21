import unittest

from architecture.tests.support import messages
from architecture.verify.core import Repo


class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def reachability(self):
        return " ".join(messages(self.repo, "network.reachability"))

    def addresses(self):
        return " ".join(messages(self.repo, "network.addresses"))

    def test_extra_network_is_caught(self):
        self.repo.compose["web_app"]["networks"].append("data")
        self.assertIn("db and web_app share network data", self.reachability())

    def test_missing_networks_key_means_default(self):
        del self.repo.compose["ingestion-worker"]["networks"]
        del self.repo.compose["notification-service"]["networks"]
        self.assertIn("share network default", self.reachability())

    def test_lost_connection_is_caught(self):
        self.repo.compose["db"]["networks"] = ["logs"]
        self.assertIn("connects api and db, but they share no network", self.reachability())

    def test_unmodelled_url_is_caught(self):
        self.repo.compose["web_app"]["environment"]["DB_URL"] = "http://db:3306"
        self.assertIn("web_app is configured to call db", self.addresses())

    def test_wrong_direction_is_caught(self):
        # They share a network, but only web_app -> api is modelled
        self.repo.compose["api"]["environment"]["WEB"] = "http://web_app:8000"
        self.assertIn("api is configured to call web_app", self.addresses())

    def test_wrong_port_is_caught(self):
        self.repo.compose["web_app"]["environment"]["CORE_API_URL"] = "http://api:3000"
        self.assertIn("api listens on 3001", self.addresses())

    def test_unmodelled_caddy_route_is_caught(self):
        self.repo.caddyfile += "\nhandle /x/* {\n\treverse_proxy db:3306\n}\n"
        self.assertIn("caddy is configured to call db", self.addresses())
