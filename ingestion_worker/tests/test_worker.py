"""The poll loop's catch-up for new dependencies, with the Core API and the feeds faked."""

import threading
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from ingestion_worker import app, config, dependency_cache, worker
from ingestion_worker.models import Dependency
from ingestion_worker.sources.base import Source, SourceEvent
from ingestion_worker.sources.cisa_kev import CisaKev


def dep(name: str, vendor: str, product: str) -> Dependency:
    return Dependency(id=name, company_id="default", vendor=vendor, product=product)


WIDGET = dep("Acme:Widget", "Acme", "Widget")
ACME = dep("Acme", "Acme", "Acme")


def event(external_id: str, days_ago: int, product: str = "Widget") -> SourceEvent:
    return SourceEvent(
        external_id=external_id,
        title=external_id,
        summary="summary",
        source_url="https://example.com/",
        published_at=datetime.now(UTC) - timedelta(days=days_ago),
        priority_hint="high",
        vendor="Acme",
        product=product,
    )


class FakeSource(Source):
    name = "cisa_kev"
    poll_interval_s = 3600

    def __init__(self, events=(), full_history=True, error=None):
        self.events = list(events)
        self.full_history = full_history
        self.error = error
        self.since = []

    def fetch(self, since):
        self.since.append(since)
        if self.error:
            raise self.error
        return [e for e in self.events if e.published_at >= since]


class WorkerTestCase(unittest.TestCase):
    def setUp(self):
        self.reported = []
        patches = [
            mock.patch.object(worker.core_api, "create_incident", side_effect=self._create),
            mock.patch.object(dependency_cache.core_api, "list_dependencies", return_value=[]),
            mock.patch.object(dependency_cache, "_dependencies", {}),
            mock.patch.object(worker, "_pending", {}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        worker._wake.clear()

    def _create(self, incident):
        self.reported.append(incident)
        return True

    def known(self, *dependencies):
        for dependency in dependencies:
            dependency_cache.put(dependency.id, dependency)


class CatchUp(WorkerTestCase):
    def test_recent_match_is_a_normal_report(self):
        self.known(WIDGET)
        self.assertTrue(worker.catch_up([FakeSource([event("NEW", 2)])], [WIDGET]))
        self.assertEqual([i.external_id for i in self.reported], ["NEW"])
        self.assertFalse(self.reported[0].backfill)

    def test_older_match_is_a_backfill(self):
        self.known(WIDGET)
        worker.catch_up([FakeSource([event("OLD", config.LOOKBACK_DAYS + 30)])], [WIDGET])
        self.assertEqual([i.external_id for i in self.reported], ["OLD"])
        self.assertTrue(self.reported[0].backfill)

    def test_first_day_of_the_window_is_not_a_backfill(self):
        # A regular poll reports this day too, so it must not count as old
        self.known(WIDGET)
        old = event("EDGE", config.LOOKBACK_DAYS)
        old.published_at = old.published_at.replace(hour=0, minute=0, second=0, microsecond=0)
        worker.catch_up([FakeSource([old])], [WIDGET])
        self.assertFalse(self.reported[0].backfill)

    def test_older_low_confidence_match_is_skipped(self):
        self.known(ACME)
        source = FakeSource([event("OLD", config.LOOKBACK_DAYS + 30), event("NEW", 2)])
        worker.catch_up([source], [ACME])
        self.assertEqual([i.external_id for i in self.reported], ["NEW"])
        self.assertEqual(self.reported[0].matched_dependencies[0].confidence, "low")

    def test_only_full_history_sources_look_past_the_window(self):
        self.known(WIDGET)
        full = FakeSource()
        windowed = FakeSource(full_history=False)
        worker.catch_up([full, windowed], [WIDGET])
        self.assertEqual(full.since[0].year, 1970)
        self.assertGreater(windowed.since[0], datetime.now(UTC) - timedelta(days=365))

    def test_only_reports_the_given_dependencies(self):
        other = dep("Acme:Widget Pro", "Acme", "Widget Pro")
        self.known(WIDGET, other)
        worker.catch_up([FakeSource([event("NEW", 2)])], [other])
        self.assertEqual(
            [m.dependency_id for m in self.reported[0].matched_dependencies], ["Acme:Widget Pro"]
        )

    def test_skips_a_dependency_removed_since(self):
        self.known(WIDGET)
        dependency_cache.delete(WIDGET.id)
        self.assertTrue(worker.catch_up([FakeSource([event("NEW", 2)])], [WIDGET]))
        self.assertEqual(self.reported, [])

    def test_one_failing_source_does_not_stop_the_others(self):
        self.known(WIDGET)
        ok = worker.catch_up(
            [FakeSource(error=RuntimeError("down")), FakeSource([event("NEW", 2)])], [WIDGET]
        )
        self.assertFalse(ok)
        self.assertEqual(len(self.reported), 1)

    def test_failed_report_returns_false(self):
        self.known(WIDGET)
        worker.core_api.create_incident.side_effect = httpx.ConnectError("down")
        self.assertFalse(worker.catch_up([FakeSource([event("NEW", 2)])], [WIDGET]))

    def test_kev_source_asks_for_its_whole_history(self):
        self.assertTrue(CisaKev.full_history)


class PendingCatchUps(WorkerTestCase):
    def test_nothing_waiting_fetches_nothing(self):
        source = FakeSource()
        worker.run_pending_catch_ups([source])
        self.assertEqual(source.since, [])

    def test_runs_once(self):
        self.known(WIDGET)
        source = FakeSource([event("NEW", 2)])
        worker.request_catch_up(WIDGET)
        worker.run_pending_catch_ups([source])
        worker.run_pending_catch_ups([source])
        self.assertEqual(len(self.reported), 1)

    def test_repeated_requests_are_one_check(self):
        self.known(WIDGET)
        source = FakeSource()
        worker.request_catch_up(WIDGET)
        worker.request_catch_up(WIDGET)
        worker.run_pending_catch_ups([source])
        self.assertEqual(len(source.since), 1)

    def test_failure_stays_waiting_for_the_next_try(self):
        self.known(WIDGET)
        source = FakeSource([event("NEW", 2)], error=RuntimeError("down"))
        worker.request_catch_up(WIDGET)
        worker.run_pending_catch_ups([source])
        self.assertEqual(self.reported, [])
        source.error = None
        worker.run_pending_catch_ups([source])
        self.assertEqual(len(self.reported), 1)

    def test_loop_wakes_for_a_request_without_waiting_for_the_interval(self):
        reported = threading.Event()
        worker.core_api.create_incident.side_effect = lambda incident: reported.set() or True
        polled = threading.Event()
        real_poll, real_pending = worker.poll, worker.run_pending_catch_ups

        def poll(source):
            result = real_poll(source)  # no dependencies yet, so this reports nothing
            polled.set()
            return result

        def pending(sources):
            real_pending(sources)
            if reported.is_set():
                raise SystemExit  # ends the loop, so it can't take other tests' requests

        with (
            mock.patch.object(worker, "poll", poll),
            mock.patch.object(worker, "run_pending_catch_ups", pending),
        ):
            source = FakeSource([event("NEW", 2)])  # polled hourly, so only a wake-up can find it
            thread = threading.Thread(target=worker.run_forever, args=([source],), daemon=True)
            thread.start()
            self.assertTrue(polled.wait(5))
            self.assertFalse(reported.is_set())
            self.known(WIDGET)
            worker.request_catch_up(WIDGET)
            self.assertTrue(reported.wait(5))
            thread.join(5)
            self.assertFalse(thread.is_alive())


class EventApi(WorkerTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app.app)
        self.auth = {"Authorization": f"Bearer {config.INBOUND_TOKEN}"}

    def test_put_updates_the_cache_and_asks_for_a_catch_up(self):
        response = self.client.put(
            f"/dependencies/{WIDGET.id}", json=WIDGET.model_dump(), headers=self.auth
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual([d.id for d in dependency_cache.get_all()], [WIDGET.id])
        self.assertIn(WIDGET.id, worker._pending)
        self.assertTrue(worker._wake.is_set())

    def test_delete_removes_it_so_a_waiting_catch_up_skips_it(self):
        self.client.put(f"/dependencies/{WIDGET.id}", json=WIDGET.model_dump(), headers=self.auth)
        response = self.client.delete(f"/dependencies/{WIDGET.id}", headers=self.auth)
        self.assertEqual(response.status_code, 204)
        worker.run_pending_catch_ups([FakeSource([event("NEW", 2)])])
        self.assertEqual(self.reported, [])

    def test_rejects_a_wrong_token(self):
        response = self.client.put(
            f"/dependencies/{WIDGET.id}",
            json=WIDGET.model_dump(),
            headers={"Authorization": "Bearer nope"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(worker._pending, {})
