"""Turns target responses into outcomes: pass / fail / error(source) / skip.

Test functions use the expect_* helpers. They raise:
  Fail            a response came back but it is wrong            -> fail
  TargetError     the target answered 5xx                          -> error, source system
  NoResponse      nothing came back (timeout, refused)             -> error, source communication
  BudgetExceeded  the run time limit cut the test short            -> error, source tester
Any other exception means the test function itself is broken      -> error, source tester
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .target import Reply

ERROR_TYPES = {"UUID_EXISTS", "UUID_DNE", "INVALID_DATA", "DP_EXISTS", "DP_DNE", "TIMEOUT"}


class Fail(Exception):
    pass


class TargetError(Exception):
    pass


class NoResponse(Exception):
    pass


class BudgetExceeded(Exception):
    pass


@dataclass
class Outcome:
    outcome: str  # pass | fail | error | skip
    message: str
    source: Optional[str] = None  # only for error

    def as_dict(self, test_id: str) -> Dict[str, Any]:
        out = {"test_id": test_id, "outcome": self.outcome, "message": self.message or self.outcome}
        if self.outcome == "error":
            out["source"] = self.source or "unknown"
        return out


def judge_exception(exc: BaseException) -> Outcome:
    if isinstance(exc, Fail):
        return Outcome("fail", str(exc))
    if isinstance(exc, TargetError):
        return Outcome("error", str(exc), "system")
    if isinstance(exc, NoResponse):
        return Outcome("error", str(exc), "communication")
    if isinstance(exc, BudgetExceeded):
        return Outcome("error", "Run time limit reached during this test. " + str(exc), "tester")
    return Outcome("error", "Tester bug in this test: %s: %s" % (type(exc).__name__, exc), "tester")


# ---------------------------------------------------------------------- reply checks
def describe(reply: Reply) -> str:
    body = reply.body
    if isinstance(body, dict):
        if "Error" in body:
            return "%s %s: %s" % (reply.status, body.get("Error"), _short(body.get("Message")))
        if "Status" in body or "status" in body:
            return "%s Status %r" % (reply.status, body.get("Status", body.get("status")))
        if "message" in body:
            return "%s %s" % (reply.status, _short(body.get("message")))
    return "%s %s" % (reply.status, _short(body))


def answered(reply: Reply) -> Reply:
    """Raise for no response or a 5xx; otherwise return the reply."""
    if reply.status is None:
        if reply.budget_hit:
            raise BudgetExceeded(reply.error)
        raise NoResponse("%s: no response from the target (%s)." % (reply.path, reply.error))
    if reply.status >= 500:
        raise TargetError("%s returned %s." % (reply.path, describe(reply)))
    return reply


def expect_ok(
    reply: Reply, status: Optional[Union[str, Sequence[str]]] = None, status_key: str = "Status"
) -> Dict[str, Any]:
    """Expect 200 with a JSON object; check the Status string when given."""
    answered(reply)
    if reply.status != 200:
        raise Fail("%s: expected 200, got %s." % (reply.path, describe(reply)))
    if not isinstance(reply.body, dict):
        raise Fail("%s: expected a JSON object, got %s." % (reply.path, _short(reply.body)))
    if status is not None:
        allowed = [status] if isinstance(status, str) else list(status)
        got = reply.body.get(status_key)
        if got not in allowed:
            raise Fail(
                "%s: %s is %r, expected %s."
                % (reply.path, status_key, got, " or ".join(repr(a) for a in allowed))
            )
    return reply.body


def expect_error(reply: Reply, errors: Union[str, Iterable[str]]) -> Dict[str, Any]:
    """Expect 400 with {"Error": <one of errors>}."""
    allowed = {errors} if isinstance(errors, str) else set(errors)
    answered(reply)
    names = " or ".join(sorted(allowed))
    if reply.status == 200:
        raise Fail(
            "%s: accepted a request that should be rejected with %s (got %s)."
            % (reply.path, names, describe(reply))
        )
    if reply.status != 400:
        raise Fail("%s: expected 400 %s, got %s." % (reply.path, names, describe(reply)))
    body = reply.body if isinstance(reply.body, dict) else {}
    if body.get("Error") not in allowed:
        raise Fail("%s: expected Error %s, got %s." % (reply.path, names, describe(reply)))
    return body


def is_rejected_or_absent(reply: Reply, body_ok) -> bool:
    """For answers the spec allows either as an error or as a status (e.g. MATCH on a missing name)."""
    answered(reply)
    return reply.status == 400 or (reply.status == 200 and body_ok(reply.body))


# ---------------------------------------------------------------------- field checks
def field(body: Dict[str, Any], *names: str, required: bool = True, path: str = "") -> Any:
    """First present field among names (spec ambiguities such as Dependency / Dependency_Name)."""
    for name in names:
        if name in body:
            return body[name]
    if required:
        raise Fail("%sresponse has no %s field." % (path + ": " if path else "", " / ".join(names)))
    return None


def expect_equal(label: str, got: Any, want: Any) -> None:
    if got != want:
        raise Fail("%s is %r, expected %r." % (label, _short(got, 80), _short(want, 80)))


def expect_field(body: Dict[str, Any], name: str, want: Any, required: bool = True) -> None:
    if name not in body:
        if required:
            raise Fail("response has no %s field (expected %r)." % (name, _short(want, 80)))
        return
    expect_equal(name, body[name], want)


def same_id(got: Any, want: str) -> bool:
    """IDs may come back as a string or a number (gap G-1)."""
    return got is not None and str(got) == str(want)


def expect_id(body: Dict[str, Any], name: str, want: str) -> None:
    got = field(body, name)
    if not same_id(got, want):
        raise Fail("%s is %r, expected %r." % (name, got, want))


TICKET_RE = re.compile(r"^(?P<incident>.+)_(?P<number>\d+)(?:_(?P<version>\d+))?$")


def parse_ticket(value: Any, incident_id: str) -> Tuple[int, Optional[int]]:
    """'<id>_<n>' or '<id>_<n>_<v>' -> (n, v or None). Fail if it isn't a ticket of incident_id."""
    text = str(value) if value is not None else ""
    prefix = str(incident_id) + "_"
    if not text.startswith(prefix):
        raise Fail("Ticket ID %r does not belong to incident %s." % (value, incident_id))
    parts = text[len(prefix) :].split("_")
    if not 1 <= len(parts) <= 2 or not all(p.isdigit() for p in parts):
        raise Fail("Ticket ID %r is not <Incident_ID>_<number>[_<version>]." % (value,))
    return int(parts[0]), (int(parts[1]) if len(parts) == 2 else None)


def ticket_list(value: Any) -> List[str]:
    """Ticket_ID_List may be a list or one comma-joined string (gap G-9)."""
    if isinstance(value, list):
        return [str(v).strip() for v in value]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    raise Fail("Ticket_ID_List is %r, expected a list of ticket IDs." % (value,))


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."
