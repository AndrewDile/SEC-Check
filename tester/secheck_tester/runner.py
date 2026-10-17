"""Runs the suite once for a session and builds the report."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from . import coverage
from .config import Settings
from .judge import BudgetExceeded, Outcome, judge_exception
from .suite import SUITE, Context, TestCase
from .target import Target


def run_suite(session_id: str, target_url: str, settings: Settings,
              suite: Optional[List[TestCase]] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return (report, abort_message). abort_message is set when the run time limit was hit."""
    suite = SUITE if suite is None else suite
    deadline = time.monotonic() + settings.run_budget
    target = Target(target_url, settings, session_id, deadline=deadline)
    ctx = Context(target, settings.teams, settings.id_style)

    results: List[Dict[str, Any]] = []
    criteria_hit: Set[str] = set()
    consecutive_comm = 0
    abort_message: Optional[str] = None
    unreachable = False

    for case in suite:
        if abort_message:
            outcome = Outcome("skip", "Not run: the run time limit was reached earlier.")
        elif unreachable:
            outcome = Outcome("skip", "Not sent: the target didn't respond to %d tests in a row." % settings.max_comm_errors)
        else:
            missing = [d for d in case.after if ctx.results.get(d) != "pass"]
            if missing:
                outcome = Outcome("skip", "Prerequisite %s did not pass (%s)." % (
                    ", ".join(missing), ", ".join(ctx.results.get(d, "not run") for d in missing)))
            elif time.monotonic() >= deadline:
                outcome = Outcome("error", "Run time limit (%gs) reached before this test started." % settings.run_budget, "tester")
                abort_message = "Run time limit of %gs reached at %s; partial report stored." % (settings.run_budget, case.test_id)
            else:
                outcome = _run_one(case, ctx)
                if outcome.outcome == "error" and outcome.source == "tester" and outcome.message.startswith("Run time limit"):
                    abort_message = "Run time limit of %gs reached during %s; partial report stored." % (settings.run_budget, case.test_id)
                if ctx.responded:
                    criteria_hit.update(case.criteria)
                if outcome.outcome == "error" and outcome.source == "communication":
                    consecutive_comm += 1
                    unreachable = consecutive_comm >= settings.max_comm_errors
                else:
                    consecutive_comm = 0
        ctx.results[case.test_id] = outcome.outcome
        results.append(outcome.as_dict(case.test_id))

    code = _code_coverage(target, settings)
    report = {
        "session_id": session_id,
        "target_url": target_url,
        "results": results,
        "coverage": {
            "code": code,
            "component": coverage.component_coverage(),
            "system": coverage.system_coverage(criteria_hit),
        },
    }
    return report, abort_message


def _run_one(case: TestCase, ctx: Context) -> Outcome:
    ctx.responded = False
    try:
        message = case.fn(ctx)
    except BudgetExceeded as exc:
        return judge_exception(exc)
    except Exception as exc:  # noqa: BLE001  (Fail, target errors and tester bugs all become outcomes)
        return judge_exception(exc)
    return Outcome("pass", message or "Passed.")


def _code_coverage(target: Target, settings: Settings) -> Dict[str, Any]:
    attempts = max(1, settings.report_retries + 1)
    reply = None
    for attempt in range(attempts):
        reply = target.report()
        if reply.status != 409 or attempt == attempts - 1:
            break
        time.sleep(settings.report_retry_delay)
    if reply.status is None:
        return coverage.code_coverage(None, None, "Target /test/report didn't respond (%s)." % reply.error)
    if reply.status == 409:
        return coverage.code_coverage(None, None, "Target /test/report still answered 409 after %d retries." % settings.report_retries)
    return coverage.code_coverage(reply.status, reply.body)
