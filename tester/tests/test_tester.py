"""End-to-end checks of the tester against the mock system.

    python -m unittest discover -s tests -v
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "dev"))

import mock_system  # noqa: E402
from secheck_tester.config import Settings  # noqa: E402
from secheck_tester.server import TesterApp, make_handler  # noqa: E402
from secheck_tester.suite import SUITE  # noqa: E402

OUTCOMES = {"pass", "fail", "error", "skip"}
SOURCES = {"tester", "system", "communication", "unknown"}


def call(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TesterHarness:
    def __init__(self, **overrides):
        settings = Settings(host="127.0.0.1", port=0, request_timeout=3, setup_timeout=5, run_budget=60)
        for k, v in overrides.items():
            setattr(settings, k, v)
        self.app = TesterApp(settings)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ReportShape:
    def assert_report(self, report, session_id, target):
        self.assertEqual(report["session_id"], session_id)
        self.assertEqual(report["target_url"], target)
        ids = [r["test_id"] for r in report["results"]]
        self.assertEqual(ids, [c.test_id for c in SUITE], "every planned test exactly once, in order")
        for r in report["results"]:
            self.assertIn(r["outcome"], OUTCOMES)
            self.assertTrue(r["message"])
            if r["outcome"] == "error":
                self.assertIn(r["source"], SOURCES)
            else:
                self.assertNotIn("source", r)
        for key in ("code", "component", "system"):
            cov = report["coverage"][key]
            self.assertTrue(cov["basis"])
            if cov["covered"] is None:
                self.assertIsNone(cov["total"])
            else:
                self.assertLessEqual(0, cov["covered"])
                self.assertLessEqual(cov["covered"], cov["total"])


class HappyPath(unittest.TestCase, ReportShape):
    @classmethod
    def setUpClass(cls):
        cls.system, cls.target = mock_system.start()
        cls.tester = TesterHarness()

    @classmethod
    def tearDownClass(cls):
        cls.tester.close()
        cls.system.shutdown()

    def setup_session(self):
        status, body = call("POST", self.tester.url + "/test/setup", {"target_url": self.target})
        self.assertEqual(status, 201, body)
        return body["session_id"]

    def test_full_suite_passes_against_reference_system(self):
        sid = self.setup_session()
        status, report = call("POST", self.tester.url + "/test/run", {"session_id": sid})
        self.assertEqual(status, 200)
        self.assert_report(report, sid, self.target)
        not_passed = [r for r in report["results"] if r["outcome"] != "pass"]
        self.assertEqual(not_passed, [])
        self.assertEqual(report["coverage"]["system"]["covered"], 6)
        self.assertIsNone(report["coverage"]["component"]["covered"])
        self.assertEqual(report["coverage"]["component"]["basis"], "not yet measured")
        self.assertIsNone(report["coverage"]["code"]["covered"])
        # Stored report is identical and lookups don't change it.
        status, stored = call("GET", self.tester.url + "/test/report?session_id=" + sid)
        self.assertEqual((status, stored), (200, report))

    def test_one_run_per_session(self):
        sid = self.setup_session()
        self.assertEqual(call("POST", self.tester.url + "/test/run", {"session_id": sid})[0], 200)
        status, body = call("POST", self.tester.url + "/test/run", {"session_id": sid})
        self.assertEqual(status, 409)
        self.assertEqual(body["source"], "tester")

    def test_report_before_run_is_409(self):
        sid = self.setup_session()
        self.assertEqual(call("GET", self.tester.url + "/test/report?session_id=" + sid)[0], 409)

    def test_session_ids_are_unique(self):
        self.assertNotEqual(self.setup_session(), self.setup_session())

    def test_invalid_requests(self):
        u = self.tester.url
        self.assertEqual(call("POST", u + "/test/setup", {"target_url": "ftp://x"})[0], 400)
        self.assertEqual(call("POST", u + "/test/setup", {"target_url": self.target + "/test"})[0], 400)
        self.assertEqual(call("POST", u + "/test/setup", {"target_url": "http://u:p@host"})[0], 400)
        self.assertEqual(call("POST", u + "/test/run", {})[0], 400)
        self.assertEqual(call("POST", u + "/test/run", {"session_id": "run-nope"})[0], 404)
        self.assertEqual(call("GET", u + "/test/report")[0], 400)
        self.assertEqual(call("GET", u + "/test/report?session_id=run-nope")[0], 404)

    def test_invalid_run_does_not_consume_session(self):
        sid = self.setup_session()
        self.assertEqual(call("POST", self.tester.url + "/test/run", {"session_id": ""})[0], 400)
        self.assertEqual(call("POST", self.tester.url + "/test/run", {"session_id": sid})[0], 200)


class FaultySystems(unittest.TestCase, ReportShape):
    def run_against(self, bug):
        system, target = mock_system.start(bug=bug)
        tester = TesterHarness()
        try:
            status, body = call("POST", tester.url + "/test/setup", {"target_url": target})
            if status != 201:
                return status, body
            sid = body["session_id"]
            status, report = call("POST", tester.url + "/test/run", {"session_id": sid})
            self.assert_report(report, sid, target)
            return status, report
        finally:
            tester.close()
            system.shutdown()

    def outcomes(self, report):
        return {r["test_id"]: r for r in report["results"]}

    def test_setup_failure_is_forwarded(self):
        status, body = self.run_against("setup-fails")
        self.assertEqual(status, 500)
        self.assertEqual(body, {"message": "Could not initialize the session database.", "source": "system"})

    def test_unreachable_target(self):
        tester = TesterHarness()
        try:
            status, body = call("POST", tester.url + "/test/setup", {"target_url": "http://127.0.0.1:9"})
            self.assertEqual(status, 500)
            self.assertEqual(body["source"], "communication")
        finally:
            tester.close()

    def test_wrong_status_strings_fail(self):
        status, report = self.run_against("wrong-status")
        self.assertEqual(status, 200)
        r = self.outcomes(report)
        self.assertEqual(r["T-01"]["outcome"], "fail")
        self.assertIn("Status", r["T-01"]["message"])
        self.assertEqual(r["T-02"]["outcome"], "skip")      # prerequisite failed
        self.assertEqual(r["T-04"]["outcome"], "pass")      # expected errors still pass

    def test_missing_validation_fails_boundary_tests(self):
        _, report = self.run_against("no-validation")
        r = self.outcomes(report)
        for tid in ("T-05", "T-06", "T-21", "T-26"):
            self.assertEqual(r[tid]["outcome"], "fail", tid)

    def test_internal_errors_are_system_errors(self):
        _, report = self.run_against("crash-logs")
        r = self.outcomes(report)
        self.assertEqual(r["T-23"]["outcome"], "error")
        self.assertEqual(r["T-23"]["source"], "system")
        self.assertEqual(r["T-24"]["outcome"], "skip")

    def test_log_order_checked(self):
        _, report = self.run_against("unordered-logs")
        r = self.outcomes(report)
        self.assertEqual(r["T-23"]["outcome"], "pass")
        self.assertEqual(r["T-24"]["outcome"], "fail")

    def test_abort_stores_partial_report(self):
        system, target = mock_system.start()
        tester = TesterHarness(run_budget=0)   # aborts before the first test
        try:
            _, body = call("POST", tester.url + "/test/setup", {"target_url": target})
            sid = body["session_id"]
            status, body = call("POST", tester.url + "/test/run", {"session_id": sid})
            self.assertEqual(status, 500)
            self.assertEqual(body["source"], "tester")
            status, report = call("GET", tester.url + "/test/report?session_id=" + sid)
            self.assertEqual(status, 200)
            self.assert_report(report, sid, target)
            self.assertEqual(report["results"][0]["outcome"], "error")
            self.assertEqual(report["results"][0]["source"], "tester")
            self.assertTrue(all(r["outcome"] == "skip" for r in report["results"][1:]))
            self.assertEqual(call("POST", tester.url + "/test/run", {"session_id": sid})[0], 409)
        finally:
            tester.close()
            system.shutdown()


if __name__ == "__main__":
    unittest.main()
