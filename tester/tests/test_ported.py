"""Checks for the tests ported from the Web App suite (T-41..T-54) and for tester behaviour
not covered by test_tester.py: shared state, unreachable targets, tester bugs, coverage parsing.

    python -m unittest discover -s tests -v
"""

import os
import subprocess
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "dev"))

import mock_system  # noqa: E402
from secheck_tester import coverage  # noqa: E402
from secheck_tester.config import Settings  # noqa: E402
from secheck_tester.runner import run_suite  # noqa: E402
from secheck_tester.suite import SUITE, TestCase  # noqa: E402
from secheck_tester.target import validate_target_url  # noqa: E402
from test_tester import TesterHarness, call  # noqa: E402

PORTED = ["T-%02d" % n for n in range(41, 55)]


def settings(**overrides):
    s = Settings(host="127.0.0.1", port=0, request_timeout=3, setup_timeout=5, run_budget=60)
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def run_against(bug="none", **overrides):
    """Full suite through the tester's HTTP interface; returns {test_id: result}."""
    system, target = mock_system.start(bug=bug)
    tester = TesterHarness(**overrides)
    try:
        status, body = call("POST", tester.url + "/test/setup", {"target_url": target})
        assert status == 201, body
        status, report = call("POST", tester.url + "/test/run", {"session_id": body["session_id"]})
        return status, report, {r["test_id"]: r for r in report["results"]}
    finally:
        tester.close()
        system.shutdown()


class PortedTests(unittest.TestCase):
    def test_suite_has_the_ported_tests_in_order(self):
        ids = [t.test_id for t in SUITE]
        self.assertEqual(ids, ["T-%02d" % n for n in range(1, 55)])
        for t in SUITE:
            self.assertTrue(set(t.criteria) <= set(coverage.CRITERIA), t.test_id)

    def test_ported_tests_pass_against_reference_system(self):
        _, _, r = run_against()
        self.assertEqual(
            {tid: r[tid]["outcome"] for tid in PORTED}, {tid: "pass" for tid in PORTED}
        )

    def test_second_team_claim_is_caught(self):
        _, _, r = run_against("claim-steal")
        self.assertEqual(r["T-41"]["outcome"], "fail")
        self.assertIn("accepted", r["T-41"]["message"])
        self.assertEqual(r["T-28"]["outcome"], "pass")

    def test_edit_dropping_fields_is_caught(self):
        _, _, r = run_against("edit-drops-fields")
        self.assertEqual(r["T-18"]["outcome"], "pass")
        self.assertEqual(r["T-48"]["outcome"], "fail")
        self.assertIn("ticket_severity", r["T-48"]["message"])

    def test_log_without_old_versions_is_caught(self):
        _, _, r = run_against("log-latest-only")
        self.assertEqual(r["T-23"]["outcome"], "pass")
        self.assertEqual(r["T-49"]["outcome"], "fail")
        self.assertIn("old version", r["T-49"]["message"])

    def test_wrong_status_strings_fail_ported_success_checks(self):
        _, _, r = run_against("wrong-status")
        self.assertEqual(r["T-53"]["outcome"], "fail")  # no prerequisites, Status checked
        self.assertEqual(r["T-54"]["outcome"], "pass")  # error envelope unaffected

    def test_crash_on_logs_is_a_system_error(self):
        _, _, r = run_against("crash-logs")
        self.assertEqual(r["T-49"]["outcome"], "skip")  # needs T-23
        self.assertEqual((r["T-25"]["outcome"], r["T-25"]["source"]), ("error", "system"))


class TesterBehaviour(unittest.TestCase):
    def test_system_ignoring_session_header_still_passes(self):
        status, report, r = run_against("ignore-session")
        self.assertEqual(status, 200)
        self.assertEqual([t for t, v in r.items() if v["outcome"] != "pass"], [])

    def test_setup_object_is_empty(self):
        status, _, r = run_against("strict-setup")
        self.assertEqual(status, 200)
        self.assertEqual([t for t, v in r.items() if v["outcome"] != "pass"], [])

    def test_two_sessions_on_a_shared_system_dont_interfere(self):
        system, target = mock_system.start(bug="ignore-session")
        try:
            out = {}

            def one(key):
                out[key] = run_suite("run-%s" % key, target, settings())[0]

            threads = [threading.Thread(target=one, args=(k,)) for k in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            for report in out.values():
                self.assertEqual([r for r in report["results"] if r["outcome"] != "pass"], [])
        finally:
            system.shutdown()

    def test_target_going_away_skips_the_rest(self):
        system, target = mock_system.start()
        tester = TesterHarness(request_timeout=1, max_comm_errors=3)
        try:
            _, body = call("POST", tester.url + "/test/setup", {"target_url": target})
            system.shutdown()  # set up, then the system disappears
            status, report = call(
                "POST", tester.url + "/test/run", {"session_id": body["session_id"]}
            )
            self.assertEqual(status, 200)
            results = report["results"]
            comm = [r for r in results if r.get("source") == "communication"]
            self.assertEqual(len(comm), 3)
            self.assertTrue(all(r["outcome"] in ("error", "skip") for r in results))
            self.assertIn("in a row", results[-1]["message"])
            self.assertIsNone(report["coverage"]["component"]["covered"])
            self.assertEqual(report["coverage"]["system"]["covered"], 0)
            self.assertIsNone(report["coverage"]["code"]["covered"])
            self.assertIn("didn't respond", report["coverage"]["code"]["basis"])
        finally:
            tester.close()

    def test_bug_in_a_test_function_is_a_tester_error(self):
        def broken(ctx):
            return {}["missing"]

        suite = [
            TestCase("X-01", "broken", ("AC-01",), (), broken),
            TestCase("X-02", "needs X-01", ("AC-01",), ("X-01",), lambda ctx: "ok"),
        ]
        system, target = mock_system.start()
        try:
            report, abort = run_suite("run-x", target, settings(), suite=suite)
        finally:
            system.shutdown()
        self.assertIsNone(abort)
        self.assertEqual(
            (report["results"][0]["outcome"], report["results"][0]["source"]), ("error", "tester")
        )
        self.assertEqual(report["results"][1]["outcome"], "skip")

    def test_base_path(self):
        system, target = mock_system.start()
        tester = TesterHarness(base_path="/tester")
        try:
            status, body = call("POST", tester.url + "/tester/test/setup", {"target_url": target})
            self.assertEqual(status, 201, body)
            self.assertEqual(
                call("POST", tester.url + "/test/setup", {"target_url": target})[0], 404
            )
        finally:
            tester.close()
            system.shutdown()

    def test_target_url_rules(self):
        self.assertEqual(validate_target_url("http://host:8200/"), "http://host:8200")
        self.assertEqual(
            validate_target_url("https://team.example.edu/sys"), "https://team.example.edu/sys"
        )
        for bad in (
            "",
            "host:8200",
            "http://",
            "http://h/test",
            "http://h/test/",
            "http://h?x=1",
            "http://h#f",
            5,
        ):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_target_url(bad)

    def test_code_coverage_parsing(self):
        ok = coverage.code_coverage(
            200, {"coverage": {"code": {"covered": 40, "total": 50, "basis": "c8 lines"}}}
        )
        self.assertEqual(ok, {"covered": 40, "total": 50, "basis": "c8 lines"})
        for body in (
            {},
            {"coverage": {}},
            {"coverage": {"code": {"covered": 5, "total": 2}}},
            {"coverage": {"code": {"covered": "5", "total": 9}}},
            {"coverage": {"code": {"covered": True, "total": 9}}},
        ):
            m = coverage.code_coverage(200, body)
            self.assertEqual((m["covered"], m["total"]), (None, None), body)
            self.assertTrue(m["basis"])
        self.assertIsNone(coverage.code_coverage(404, {})["covered"])

    def test_settings_from_env(self):
        s = Settings.from_env(
            {
                "TESTER_PORT": "9000",
                "TESTER_TEAMS": "A, B",
                "TESTER_SESSION_IN_BODY": "true",
                "TESTER_BASE_PATH": "tester/",
                "TESTER_DEPENDENCIES_PATH": "dependancies",
            }
        )
        self.assertEqual(
            (s.port, s.teams, s.session_in_body, s.base_path, s.dependencies_path),
            (9000, ["A", "B"], True, "/tester", "/dependancies"),
        )

    def test_list_command(self):
        out = subprocess.run(
            [sys.executable, "-m", "secheck_tester", "--list"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("T-54", out.stdout)
        self.assertIn("54 tests", out.stdout)


if __name__ == "__main__":
    unittest.main()
