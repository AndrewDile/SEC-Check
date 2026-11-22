import unittest

from architecture.tests.support import messages
from architecture.verify.core import Repo


class ContainersTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def test_new_container_is_caught(self):
        self.repo.compose["cache"] = {"image": "redis"}
        self.assertIn(
            "cache: in docker-compose.yml but not in the model",
            messages(self.repo, "containers.match"),
        )

    def test_removed_container_is_caught(self):
        del self.repo.compose["docs"]
        self.assertIn(
            "docs: in the model but not in docker-compose.yml",
            messages(self.repo, "containers.match"),
        )

    def test_published_port_is_caught(self):
        self.repo.compose["api"]["ports"] = ["3001:3001"]
        self.assertIn("api: publishes", " ".join(messages(self.repo, "containers.published-ports")))

    def test_unpublished_port_is_caught(self):
        del self.repo.compose["db"]["ports"]
        self.assertIn(
            "db: publishes no ports", " ".join(messages(self.repo, "containers.published-ports"))
        )
