"""What the API accepts from the Core API. Delivery itself is replaced with a mock."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from notification_service import app, config, line_coverage

BODY = {
    "notification_id": "100",
    "incident": {
        "id": "100",
        "created_at": "2026-10-01T00:00:00Z",
        "company_id": "default",
        "source": "cisa_kev",
        "external_id": "CVE-1",
        "title": "CVE-1: A bug",
        "summary": "A summary.",
        "source_url": "https://example.com/",
        "published_at": "2026-10-01T00:00:00Z",
        "detected_at": "2026-10-01T00:00:00Z",
        "priority_hint": "high",
        "matched_dependencies": [],
    },
    "claim_url": "https://example.com/claim",
    "recipients": [],
}


class AcceptNotification(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.auth = {"Authorization": f"Bearer {config.INBOUND_TOKEN}"}
        app._accepted.clear()
        self.addCleanup(app._accepted.clear)
        patcher = patch("notification_service.app.dispatch")
        self.dispatch = patcher.start()
        self.addCleanup(patcher.stop)

    def test_wrong_or_missing_token_is_rejected(self):
        for headers in [{"Authorization": "Bearer wrong"}, {}]:
            with self.subTest(headers=headers):
                response = self.client.post("/notifications", json=BODY, headers=headers)
                self.assertEqual(response.status_code, 401)
        self.dispatch.assert_not_called()

    def test_repeated_id_is_delivered_once(self):
        for _ in range(2):
            response = self.client.post("/notifications", json=BODY, headers=self.auth)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), {"notification_id": "100"})
        self.dispatch.assert_called_once()


class Coverage(unittest.TestCase):
    def setUp(self):
        line_coverage.start()
        self.client = TestClient(app.app)
        self.auth = {"Authorization": f"Bearer {config.INBOUND_TOKEN}"}

    def covered(self, since):
        return self.client.get(f"/coverage?since={since}", headers=self.auth).json()["covered"]

    def test_health_checks_do_not_count_but_requests_do(self):
        since = self.client.post("/coverage/snapshot", headers=self.auth).json()["since"]
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.covered(since), 0)
        with patch("notification_service.app.dispatch"):
            self.client.post(
                "/notifications", json={**BODY, "notification_id": "cov"}, headers=self.auth
            )
        self.assertGreater(self.covered(since), 0)
