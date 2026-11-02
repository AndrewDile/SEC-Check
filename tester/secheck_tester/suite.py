"""The ordered test suite.

T-01..T-40 are the original tester suite. T-41..T-54 are ported from the Web
App team's mock-Core test suite ("Web Dev/tests"): the checks from it that a
client can observe through the Core API alone. T-55..T-70 cover the /teams and
/users paths (creating teams and users, memberships, and using new teams on tickets).

Each test is a function taking a Context. It sends Core API calls with
ctx.call(...) and checks them with the judge helpers; finishing without an
exception is a pass. Field names come from spec_docs/API Spec.txt; paths are
in target.py.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .judge import (
    ERROR_TYPES,
    Fail,
    answered,
    expect_equal,
    expect_error,
    expect_field,
    expect_id,
    expect_ok,
    field,
    parse_ticket,
    ticket_list,
)
from .target import Reply, Target

CLOCK_LAG = timedelta(seconds=60)  # timestamps run 60 s behind the tester's clock


@dataclass
class TestCase:
    test_id: str
    title: str
    criteria: Tuple[str, ...]
    after: Tuple[str, ...]
    fn: Callable[["Context"], Optional[str]]
    db: bool = False  # a read-after-write check (counts toward Database coverage)


SUITE: List[TestCase] = []


def test(
    test_id: str, title: str, ac: Tuple[str, ...], after: Tuple[str, ...] = (), db: bool = False
):
    def register(fn):
        SUITE.append(TestCase(test_id, title, tuple(ac), tuple(after), fn, db))
        return fn

    return register


class Context:
    """Per-run state shared by the tests: generated IDs, results so far, values to check later."""

    def __init__(self, target: Target, teams: List[str], id_style: str = "digits"):
        self.target = target
        self.teams = list(teams)
        self.id_style = id_style
        self.ids: Dict[str, str] = {}
        self.state: Dict[str, Any] = {}
        self.results: Dict[str, str] = {}  # test_id -> outcome
        self.answered_paths: Set[str] = set()  # Core API paths that got any response
        self.responded = False  # the current test got at least one response
        self._last_ts: Optional[datetime] = None

    # -- helpers used by tests
    def call(self, name: str, body: Dict[str, Any]) -> Reply:
        reply = self.target.core(name, body)
        if reply.answered:
            self.responded = True
            self.answered_paths.add(name)
        return reply

    def iid(self, key: str) -> str:
        """A fresh Incident_ID per key and session, so sessions never collide."""
        if key not in self.ids:
            if self.id_style == "uuid":
                self.ids[key] = str(uuid.uuid4())
            else:
                self.ids[key] = str(10**11 + secrets.randbelow(9 * 10**11))  # 12 digits
        return self.ids[key]

    def dep(self, key: str, spaced: bool = False) -> str:
        name_key = "dep:" + key
        if name_key not in self.ids:
            token = secrets.token_hex(4)
            self.ids[name_key] = ("tester dep %s" if spaced else "tester-dep-%s") % token
        return self.ids[name_key]

    def ts(self) -> str:
        """RFC 3339 UTC timestamp, 60 s behind now and strictly increasing within the run."""
        now = datetime.now(timezone.utc) - CLOCK_LAG
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        if self._last_ts is not None and now <= self._last_ts:
            now = self._last_ts + timedelta(milliseconds=1)
        self._last_ts = now
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)

    @staticmethod
    def future_ts() -> str:
        return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def passed(self, test_id: str) -> bool:
        return self.results.get(test_id) == "pass"

    # -- request builders (Core field names)
    def incident(
        self, method: str, incident_id: str, description: Optional[str] = "", **extra
    ) -> Reply:
        body: Dict[str, Any] = {
            "Incident_ID": incident_id,
            "Method": method,
            "Timestamp": extra.pop("Timestamp", None) or self.ts(),
        }
        if description is not None:
            body["Description"] = description
        body.update(extra)
        return self.call("incidents", body)

    def get_incident(self, incident_id: str) -> Reply:
        return self.incident("GET", incident_id, "")

    def ticket(
        self, method: str, incident_id: str, description: Optional[str] = None, **extra
    ) -> Reply:
        body: Dict[str, Any] = {
            "Incident_ID": incident_id,
            "Method": method,
            "Timestamp": extra.pop("Timestamp", None) or self.ts(),
        }
        if description is not None:
            body["Description"] = description
        body.update(extra)
        return self.call("tickets", body)

    def get_ticket(self, incident_id: str, number: str) -> Reply:
        return self.ticket("GET", incident_id, "", Ticket_number=number)

    def notifier(self, method: str, teams: List[str], number: str) -> Reply:
        return self.call(
            "notifier", {"Team_Names": teams, "Method": method, "Ticket_Number": number}
        )

    def logs(self, incident_id: str, timestamp: Optional[str] = None) -> Reply:
        return self.call("logs", {"Incident_ID": incident_id, "Timestamp": timestamp or self.ts()})

    def dependency(self, method: str, name: str) -> Reply:
        return self.call("dependencies", {"dp_name": name, "method": method})

    def team(self, method: str, name: Optional[str] = None, **extra) -> Reply:
        body: Dict[str, Any] = {"Method": method}
        if name is not None:
            body["Team_Name"] = name
        body.update(extra)
        return self.call("teams", body)

    def user(self, method: str, name: Optional[str] = None, **extra) -> Reply:
        body: Dict[str, Any] = {"Method": method}
        if name is not None:
            body["Username"] = name
        body.update(extra)
        return self.call("users", body)

    def team_name(self, key: str) -> str:
        """A fresh team name per key and run, e.g. 'Tester team 1a2b3c4d'."""
        return self._name("team:" + key, "Tester team %s")

    def username(self, key: str) -> str:
        return self._name("user:" + key, "tester-%s")

    def _name(self, key: str, pattern: str) -> str:
        if key not in self.ids:
            self.ids[key] = pattern % secrets.token_hex(4)
        return self.ids[key]


# Values the tests create and later check.
MATERIAL_DESC = "Tester: ransomware encrypted the billing database (material incident)."
PLAIN_DESC = "Tester: phishing email reported, no data accessed."
TICKET1_DESC = "Tester: contain the billing database and rotate credentials."
TICKET1_EDIT = "Tester: containment done; credentials rotated (edited)."
TICKET2_DESC = "Tester: notify the outside counsel."
DEP_INCIDENT_DESC = "Tester: outage at a third-party identity provider."


def incident_matches(body: Dict[str, Any], materiality: str, severity: str, urgency: str) -> None:
    expect_field(body, "Materiality", materiality)
    expect_field(body, "Severity", severity)
    expect_field(body, "Urgency", urgency)


def new_ticket_number(ctx: Context, body: Dict[str, Any], incident_id: str) -> str:
    """Check a NEW ticket response and return its weak number '<id>_<n>'."""
    number, version = parse_ticket(field(body, "Ticket_ID"), incident_id)
    if version not in (None, 1):
        raise Fail("A new ticket's Ticket_ID %r should be version 1." % body["Ticket_ID"])
    return "%s_%d" % (incident_id, number)


# ====================================================================== incidents (AC-01, AC-03)
@test("T-01", "Create a material incident (NEW)", ("AC-01",))
def t01(ctx: Context):
    a = ctx.iid("A")
    body = expect_ok(
        ctx.incident(
            "NEW", a, MATERIAL_DESC, Materiality="MATERIAL", Severity="HIGH", Urgency="URGENT"
        ),
        "Created",
    )
    expect_id(body, "Incident_ID", a)
    for name, want in (("Materiality", "MATERIAL"), ("Severity", "HIGH"), ("Urgency", "URGENT")):
        expect_field(body, name, want, required=False)
    return "Created incident %s." % a


@test("T-02", "Fetch the stored incident (GET)", ("AC-01",), after=("T-01",), db=True)
def t02(ctx: Context):
    body = expect_ok(ctx.get_incident(ctx.iid("A")), "Data Fetched")
    expect_id(body, "Incident_ID", ctx.iid("A"))
    expect_field(body, "Description", MATERIAL_DESC)
    incident_matches(body, "MATERIAL", "HIGH", "URGENT")
    return "GET returned the stored incident."


@test("T-03", "Reject a duplicate Incident_ID (NEW twice)", ("AC-01",), after=("T-01",))
def t03(ctx: Context):
    expect_error(ctx.incident("NEW", ctx.iid("A"), "Tester: duplicate"), "UUID_EXISTS")
    return "Duplicate rejected with UUID_EXISTS."


@test("T-04", "Reject GET of an unknown incident", ("AC-01",))
def t04(ctx: Context):
    expect_error(ctx.get_incident(ctx.iid("unknown")), "UUID_DNE")
    return "Unknown incident rejected with UUID_DNE."


@test("T-05", "Reject an incident timestamp in the future", ("AC-01",))
def t05(ctx: Context):
    expect_error(
        ctx.incident("NEW", ctx.iid("future"), "Tester: future", Timestamp=ctx.future_ts()),
        "INVALID_DATA",
    )
    return "Future timestamp rejected."


@test("T-06", "Reject a Description over 5000 characters", ("AC-01",))
def t06(ctx: Context):
    expect_error(ctx.incident("NEW", ctx.iid("long"), "x" * 5001), "INVALID_DATA")
    return "5001-character Description rejected."


@test("T-07", "Reject an invalid Severity value", ("AC-01",))
def t07(ctx: Context):
    expect_error(
        ctx.incident("NEW", ctx.iid("badsev"), "Tester: bad severity", Severity="EXTREME"),
        "INVALID_DATA",
    )
    return "Severity EXTREME rejected."


@test("T-08", "Reject an incident without Description", ("AC-01",))
def t08(ctx: Context):
    expect_error(ctx.incident("NEW", ctx.iid("nodesc"), None), "INVALID_DATA")
    return "Missing Description rejected."


@test("T-09", "Reject an invalid Method", ("AC-01",))
def t09(ctx: Context):
    expect_error(ctx.incident("DELETE", ctx.iid("badmethod"), "Tester: bad method"), "INVALID_DATA")
    return "Method DELETE rejected."


@test("T-10", "Create an incident with optional fields omitted", ("AC-01",))
def t10(ctx: Context):
    b = ctx.iid("B")
    body = expect_ok(ctx.incident("NEW", b, PLAIN_DESC), "Created")
    expect_id(body, "Incident_ID", b)
    return "Created incident %s with only the required fields." % b


@test("T-11", "Omitted fields default to UNDECIDED", ("AC-01",), after=("T-10",), db=True)
def t11(ctx: Context):
    body = expect_ok(ctx.get_incident(ctx.iid("B")), "Data Fetched")
    incident_matches(body, "UNDECIDED", "UNDECIDED", "UNDECIDED")
    return "Materiality, Severity and Urgency default to UNDECIDED."


@test("T-12", "Mark an incident immaterial with low severity (EDIT)", ("AC-03",), after=("T-10",))
def t12(ctx: Context):
    body = expect_ok(
        ctx.incident("EDIT", ctx.iid("B"), PLAIN_DESC, Materiality="IMMATERIAL", Severity="LOW"),
        "Edited",
    )
    expect_id(body, "Incident_ID", ctx.iid("B"))
    return "EDIT accepted."


@test("T-13", "The edited marking is stored", ("AC-03",), after=("T-12",), db=True)
def t13(ctx: Context):
    body = expect_ok(ctx.get_incident(ctx.iid("B")), "Data Fetched")
    expect_field(body, "Materiality", "IMMATERIAL")
    expect_field(body, "Severity", "LOW")
    return "IMMATERIAL / LOW stored."


@test("T-14", "Reject EDIT of an unknown incident", ("AC-03",))
def t14(ctx: Context):
    expect_error(
        ctx.incident("EDIT", ctx.iid("unknown"), "Tester: edit", Materiality="IMMATERIAL"),
        "UUID_DNE",
    )
    return "EDIT of unknown incident rejected with UUID_DNE."


# ====================================================================== tickets (AC-02)
@test("T-15", "Log a ticket on the material incident (NEW)", ("AC-02", "AC-03"), after=("T-01",))
def t15(ctx: Context):
    a = ctx.iid("A")
    body = expect_ok(
        ctx.ticket(
            "NEW",
            a,
            TICKET1_DESC,
            Ticket_severity="HIGH",
            Ticket_urgency="URGENT",
            Team_list=["CYBER1"],
        ),
        "Logged",
    )
    expect_id(body, "Incident_ID", a)
    ctx.state["ticket1"] = new_ticket_number(ctx, body, a)
    return "Logged ticket %s." % ctx.state["ticket1"]


@test(
    "T-16",
    "Display the logged ticket (GET by weak ticket number)",
    ("AC-02",),
    after=("T-15",),
    db=True,
)
def t16(ctx: Context):
    a, t1 = ctx.iid("A"), ctx.state["ticket1"]
    body = expect_ok(ctx.get_ticket(a, t1), "Displayed")
    number, _ = parse_ticket(field(body, "Ticket_ID"), a)
    expect_equal("Ticket number", "%s_%d" % (a, number), t1)
    expect_field(body, "Ticket_Description", TICKET1_DESC)
    expect_field(body, "ticket_severity", "HIGH", required=False)
    expect_field(body, "ticket_urgency", "URGENT", required=False)
    return "GET %s returned the logged ticket." % t1


@test("T-17", "A second ticket gets the next ticket number", ("AC-02",), after=("T-15",))
def t17(ctx: Context):
    a = ctx.iid("A")
    body = expect_ok(ctx.ticket("NEW", a, TICKET2_DESC, Team_list=["LEGAL"]), "Logged")
    t2 = new_ticket_number(ctx, body, a)
    n1, _ = parse_ticket(ctx.state["ticket1"], a)
    n2, _ = parse_ticket(t2, a)
    if n2 != n1 + 1:
        raise Fail("Second ticket is %s, expected %s_%d." % (t2, a, n1 + 1))
    ctx.state["ticket2"] = t2
    return "Second ticket is %s." % t2


@test("T-18", "Editing a ticket creates a new version (EDIT)", ("AC-02",), after=("T-15",))
def t18(ctx: Context):
    a, t1 = ctx.iid("A"), ctx.state["ticket1"]
    body = expect_ok(
        ctx.ticket("EDIT", a, TICKET1_EDIT, Ticket_number=t1)
    )  # no EDIT Status in the spec (G-4)
    number, version = parse_ticket(field(body, "Ticket_ID"), a)
    expect_equal("Edited ticket number", "%s_%d" % (a, number), t1)
    if version is not None and version < 2:
        raise Fail("Edited ticket is version %d, expected a new version (2 or later)." % version)
    return "EDIT produced %s." % body["Ticket_ID"]


@test("T-19", "Reject a ticket for an unknown incident", ("AC-02",))
def t19(ctx: Context):
    expect_error(ctx.ticket("NEW", ctx.iid("unknown"), "Tester: orphan ticket"), "UUID_DNE")
    return "Ticket for unknown incident rejected with UUID_DNE."


@test("T-20", "Reject a NEW ticket without Description", ("AC-02",), after=("T-01",))
def t20(ctx: Context):
    expect_error(ctx.ticket("NEW", ctx.iid("A"), None), "INVALID_DATA")
    return "NEW ticket without Description rejected."


@test("T-21", "Reject a ticket timestamp in the future", ("AC-02",), after=("T-01",))
def t21(ctx: Context):
    expect_error(
        ctx.ticket("NEW", ctx.iid("A"), "Tester: future ticket", Timestamp=ctx.future_ts()),
        "INVALID_DATA",
    )
    return "Future ticket timestamp rejected."


@test("T-22", "Reject an invalid Ticket_urgency value", ("AC-02",), after=("T-01",))
def t22(ctx: Context):
    expect_error(
        ctx.ticket("NEW", ctx.iid("A"), "Tester: bad urgency", Ticket_urgency="SOON"),
        "INVALID_DATA",
    )
    return "Ticket_urgency SOON rejected."


# ====================================================================== logs (AC-02, AC-06)
def log_entries(
    ctx: Context, body: Dict[str, Any], incident_id: str
) -> List[Tuple[int, Optional[int]]]:
    return [
        parse_ticket(entry, incident_id) for entry in ticket_list(field(body, "Ticket_ID_List"))
    ]


@test(
    "T-23",
    "Retrieve the incident log with all its tickets",
    ("AC-02", "AC-06"),
    after=("T-15", "T-17"),
    db=True,
)
def t23(ctx: Context):
    a = ctx.iid("A")
    body = expect_ok(ctx.logs(a), "Log Retrieved")
    expect_id(body, "Incident_ID", a)
    entries = log_entries(ctx, body, a)
    numbers = {n for n, _ in entries}
    for key in ("ticket1", "ticket2"):
        n, _ = parse_ticket(ctx.state[key], a)
        if n not in numbers:
            raise Fail(
                "Ticket_ID_List %r is missing ticket %s." % (body["Ticket_ID_List"], ctx.state[key])
            )
    ctx.state["log_entries"] = entries
    return "Log lists %d entries including both tickets." % len(entries)


@test("T-24", "Log entries are in the order the actions happened", ("AC-02",), after=("T-23",))
def t24(ctx: Context):
    a = ctx.iid("A")
    entries = ctx.state["log_entries"]
    n1, _ = parse_ticket(ctx.state["ticket1"], a)
    n2, _ = parse_ticket(ctx.state["ticket2"], a)
    first = {}
    for pos, (n, v) in enumerate(entries):
        first.setdefault((n, v if v is not None else 1), pos)
        first.setdefault(n, pos)
    if first[n1] > first[n2]:
        raise Fail(
            "Ticket %s (logged first) appears after %s in the log."
            % (ctx.state["ticket1"], ctx.state["ticket2"])
        )
    # With version IDs and a successful edit: t1 v1, t2 v1, then t1 v2.
    if ctx.passed("T-18") and (n1, 2) in first:
        order = [first.get((n1, 1)), first.get((n2, 1)), first.get((n1, 2))]
        if None in order or not order[0] < order[1] < order[2]:
            raise Fail(
                "Expected %s_1, %s_1, %s_2 in that order; log has %r."
                % (
                    ctx.state["ticket1"],
                    ctx.state["ticket2"],
                    ctx.state["ticket1"],
                    ["%s_%d%s" % (a, n, "" if v is None else "_%d" % v) for n, v in entries],
                )
            )
    return "Log entries are in action order."


@test("T-25", "Reject a log request for an unknown incident", ("AC-06",))
def t25(ctx: Context):
    expect_error(ctx.logs(ctx.iid("unknown")), "UUID_DNE")
    return "Log for unknown incident rejected with UUID_DNE."


@test("T-26", "Reject a log request with a future timestamp", ("AC-02",), after=("T-01",))
def t26(ctx: Context):
    expect_error(ctx.logs(ctx.iid("A"), ctx.future_ts()), "INVALID_DATA")
    return "Future log timestamp rejected."


# ====================================================================== notifier (AC-04)
def notifier_body_matches(body: Dict[str, Any], incident_id: str, number: str) -> None:
    expect_id(body, "UUID", incident_id)
    expect_field(body, "Ticket_Number", number)


@test("T-27", "Notify all teams about a ticket (NOTIFY)", ("AC-04",), after=("T-15",))
def t27(ctx: Context):
    body = expect_ok(ctx.notifier("NOTIFY", ctx.teams, ctx.state["ticket1"]), "Notified team")
    notifier_body_matches(body, ctx.iid("A"), ctx.state["ticket1"])
    return "Notified %s." % ", ".join(ctx.teams)


@test("T-28", "One team claims the ticket (CLAIM)", ("AC-04",), after=("T-15",))
def t28(ctx: Context):
    body = expect_ok(ctx.notifier("CLAIM", [ctx.teams[1]], ctx.state["ticket1"]), "Claimed ticket")
    notifier_body_matches(body, ctx.iid("A"), ctx.state["ticket1"])
    return "%s claimed %s." % (ctx.teams[1], ctx.state["ticket1"])


@test("T-29", "The claim is visible on the ticket", ("AC-04",), after=("T-28",), db=True)
def t29(ctx: Context):
    body = expect_ok(ctx.get_ticket(ctx.iid("A"), ctx.state["ticket1"]), "Displayed")
    if "Ticket_Claim" not in body and "Claimed_By" not in body:
        return "Ticket read back; the system doesn't return claim fields (Ticket_Claim is not in the OpenAPI, G-3)."
    expect_field(body, "Ticket_Claim", "CLAIMED", required=False)
    expect_field(body, "Claimed_By", ctx.teams[1], required=False)
    return "Ticket shows the claim."


@test("T-30", "Reject a claim with no team", ("AC-04",), after=("T-15",))
def t30(ctx: Context):
    expect_error(ctx.notifier("CLAIM", [], ctx.state["ticket1"]), "INVALID_DATA")
    return "Claim with empty Team_Names rejected."


@test("T-31", "Reject an invalid notifier Method", ("AC-04",), after=("T-15",))
def t31(ctx: Context):
    expect_error(ctx.notifier("PING", [ctx.teams[0]], ctx.state["ticket1"]), "INVALID_DATA")
    return "Method PING rejected."


@test("T-32", "Reject a claim on an unknown ticket", ("AC-04",))
def t32(ctx: Context):
    expect_error(
        ctx.notifier("CLAIM", [ctx.teams[0]], ctx.iid("unknown") + "_1"),
        ("UUID_DNE", "INVALID_DATA"),
    )
    return "Claim on unknown ticket rejected."


# ====================================================================== dependencies (AC-05)
@test("T-33", "Add a third-party dependency (NEW)", ("AC-05",))
def t33(ctx: Context):
    name = ctx.dep("main")
    body = expect_ok(ctx.dependency("NEW", name), "Added", status_key="status")
    expect_field(body, "dp_name", name, required=False)
    return "Added dependency %s." % name


@test("T-34", "Reject a duplicate dependency", ("AC-05",), after=("T-33",))
def t34(ctx: Context):
    expect_error(ctx.dependency("NEW", ctx.dep("main")), "DP_EXISTS")
    return "Duplicate dependency rejected with DP_EXISTS."


@test("T-35", "Match a stored dependency (MATCH)", ("AC-05",), after=("T-33",), db=True)
def t35(ctx: Context):
    expect_ok(ctx.dependency("MATCH", ctx.dep("main")), "Exists", status_key="status")
    return "MATCH found the dependency."


@test("T-36", "Record an incident against a dependency", ("AC-05", "AC-01"), after=("T-33",))
def t36(ctx: Context):
    c, name = ctx.iid("C"), ctx.dep("main")
    expect_ok(ctx.incident("NEW", c, DEP_INCIDENT_DESC, Dependency=name), "Created")
    body = expect_ok(ctx.get_incident(c), "Data Fetched")
    got = field(body, "Dependency", "Dependency_Name", required=False)
    if got is not None:
        expect_equal("Dependency", got, name)
        return "Incident %s stored with dependency %s." % (c, name)
    return "Incident %s created with a dependency (the system doesn't return it on GET)." % c


@test("T-37", "Remove the dependency (REMOVE)", ("AC-05",), after=("T-33",))
def t37(ctx: Context):
    expect_ok(ctx.dependency("REMOVE", ctx.dep("main")), "Removed", status_key="status")
    return "Dependency removed."


@test("T-38", "A removed dependency no longer matches", ("AC-05",), after=("T-37",), db=True)
def t38(ctx: Context):
    reply = answered(ctx.dependency("MATCH", ctx.dep("main")))
    if reply.status == 400:
        expect_error(reply, "DP_DNE")
        return "MATCH after removal answered DP_DNE."
    expect_ok(reply, "Does not Exist", status_key="status")
    return "MATCH after removal answered 'Does not Exist'."


@test("T-39", "Reject removal of an unknown dependency", ("AC-05",))
def t39(ctx: Context):
    expect_error(ctx.dependency("REMOVE", ctx.dep("never-added")), "DP_DNE")
    return "REMOVE of unknown dependency rejected with DP_DNE."


@test("T-40", "Reject an invalid dependency method", ("AC-05",))
def t40(ctx: Context):
    expect_error(ctx.dependency("DELETE", ctx.dep("main")), "INVALID_DATA")
    return "method DELETE rejected."


# ====================================================================== ported from the Web App suite
@test("T-41", "A second team cannot claim an already claimed ticket", ("AC-04",), after=("T-28",))
def t41(ctx: Context):
    expect_error(
        ctx.notifier("CLAIM", [ctx.teams[2 % len(ctx.teams)]], ctx.state["ticket1"]), "INVALID_DATA"
    )
    return "Second claim by another team rejected."


@test("T-42", "Reject a CLAIM naming more than one team", ("AC-04",), after=("T-17",))
def t42(ctx: Context):
    expect_error(ctx.notifier("CLAIM", ctx.teams[:2], ctx.state["ticket2"]), "INVALID_DATA")
    return "CLAIM by two teams rejected."


@test("T-43", "Reject a ticket assigned to an unknown team", ("AC-02", "AC-04"), after=("T-01",))
def t43(ctx: Context):
    expect_error(
        ctx.ticket("NEW", ctx.iid("A"), "Tester: unknown team", Team_list=["MARKETING"]),
        "INVALID_DATA",
    )
    return "Team_list with an unknown team rejected."


@test("T-44", "Reject NOTIFY with no teams", ("AC-04",), after=("T-15",))
def t44(ctx: Context):
    expect_error(ctx.notifier("NOTIFY", [], ctx.state["ticket1"]), "INVALID_DATA")
    return "NOTIFY with empty Team_Names rejected."


@test(
    "T-45",
    "Reject a ticket number that belongs to another incident",
    ("AC-02",),
    after=("T-15", "T-10"),
)
def t45(ctx: Context):
    expect_error(ctx.get_ticket(ctx.iid("B"), ctx.state["ticket1"]), ("UUID_DNE", "INVALID_DATA"))
    return "Ticket of incident A not shown under incident B."


@test("T-46", "Reject an unknown ticket number on a known incident", ("AC-02",), after=("T-01",))
def t46(ctx: Context):
    expect_error(ctx.get_ticket(ctx.iid("A"), ctx.iid("A") + "_999"), ("UUID_DNE", "INVALID_DATA"))
    return "Unknown ticket number rejected."


@test("T-47", "Reject a ticket EDIT without Description", ("AC-02",), after=("T-15",))
def t47(ctx: Context):
    expect_error(
        ctx.ticket("EDIT", ctx.iid("A"), None, Ticket_number=ctx.state["ticket1"]), "INVALID_DATA"
    )
    return "EDIT without Description rejected."


@test(
    "T-48",
    "An edited ticket shows the new text and keeps unchanged fields",
    ("AC-02",),
    after=("T-18",),
    db=True,
)
def t48(ctx: Context):
    body = expect_ok(ctx.get_ticket(ctx.iid("A"), ctx.state["ticket1"]), "Displayed")
    expect_field(body, "Ticket_Description", TICKET1_EDIT)
    expect_field(body, "ticket_severity", "HIGH")
    expect_field(body, "ticket_urgency", "URGENT")
    teams = field(body, "Team_List")
    if not isinstance(teams, list) or "CYBER1" not in teams:
        raise Fail(
            "Team_List is %r after an EDIT that didn't change it; expected it to keep CYBER1."
            % (teams,)
        )
    return "Latest version has the edited text and the original severity, urgency and teams."


@test(
    "T-49",
    "The log keeps every version of an edited ticket, in order",
    ("AC-02", "AC-06"),
    after=("T-18", "T-23"),
    db=True,
)
def t49(ctx: Context):
    a = ctx.iid("A")
    body = expect_ok(ctx.logs(a), "Log Retrieved")
    n1, _ = parse_ticket(ctx.state["ticket1"], a)
    versions = [v for n, v in log_entries(ctx, body, a) if n == n1]
    if len(versions) < 2:
        raise Fail(
            "Ticket %s was edited but appears %d time(s) in Ticket_ID_List %r; the old version should stay in the log."
            % (ctx.state["ticket1"], len(versions), body["Ticket_ID_List"])
        )
    if all(v is not None for v in versions) and versions != sorted(versions):
        raise Fail(
            "Versions of %s are out of order in the log: %r." % (ctx.state["ticket1"], versions)
        )
    return "Log lists %d versions of %s in order." % (len(versions), ctx.state["ticket1"])


@test("T-50", "Ticket responses carry the incident's details", ("AC-02",), after=("T-17",), db=True)
def t50(ctx: Context):
    body = expect_ok(ctx.get_ticket(ctx.iid("A"), ctx.state["ticket2"]), "Displayed")
    expect_id(body, "Incident_ID", ctx.iid("A"))
    expect_field(body, "Ticket_Description", TICKET2_DESC)
    expect_field(body, "UUID_Description", MATERIAL_DESC)
    expect_field(body, "Materiality_type", "MATERIAL")
    expect_field(body, "uuid_severity", "HIGH")
    expect_field(body, "uuid_urgency", "URGENT")
    expect_field(body, "ticket_severity", "UNDECIDED")
    expect_field(body, "ticket_urgency", "UNDECIDED")
    expect_field(body, "Team_List", ["LEGAL"])
    return "Ticket response has every spec field, with the incident's values."


@test("T-51", "The log response carries the incident's details", ("AC-06",), after=("T-23",))
def t51(ctx: Context):
    body = expect_ok(ctx.logs(ctx.iid("A")), "Log Retrieved")
    expect_field(body, "Description", MATERIAL_DESC)
    expect_field(body, "Materiality_type", "MATERIAL")
    expect_field(body, "Severity", "HIGH")
    expect_field(body, "Urgency", "URGENT")
    return "Log response has the incident's description and markings."


@test(
    "T-52",
    "An incident's description and urgency can be edited",
    ("AC-01",),
    after=("T-13",),
    db=True,
)
def t52(ctx: Context):
    b = ctx.iid("B")
    new_desc = PLAIN_DESC + " Update: one mailbox was accessed."
    expect_ok(
        ctx.incident(
            "EDIT", b, new_desc, Materiality="IMMATERIAL", Severity="LOW", Urgency="URGENT"
        ),
        "Edited",
    )
    body = expect_ok(ctx.get_incident(b), "Data Fetched")
    expect_field(body, "Description", new_desc)
    incident_matches(body, "IMMATERIAL", "LOW", "URGENT")
    return "Edited description and urgency stored."


@test("T-53", "Dependency names with spaces work end to end", ("AC-05",))
def t53(ctx: Context):
    name = ctx.dep("spaced", spaced=True)
    expect_ok(ctx.dependency("NEW", name), "Added", status_key="status")
    expect_ok(ctx.dependency("MATCH", name), "Exists", status_key="status")
    expect_ok(ctx.dependency("REMOVE", name), "Removed", status_key="status")
    return "Added, matched and removed %r." % name


@test("T-54", "Error responses use the {Error, Message} format", ("AC-01", "AC-02", "AC-05"))
def t54(ctx: Context):
    checks = [
        (
            "incidents",
            ctx.incident("NEW", ctx.iid("envelope"), "Tester: envelope", Urgency="WHENEVER"),
        ),
        ("tickets", ctx.ticket("NEW", ctx.iid("unknown"), "Tester: envelope")),
        ("dependencies", ctx.dependency("REMOVE", ctx.dep("envelope-missing"))),
    ]
    for path, reply in checks:
        answered(reply)
        body = reply.body
        if reply.status != 400 or not isinstance(body, dict):
            raise Fail("/%s: expected a 400 error object, got %s %r." % (path, reply.status, body))
        if body.get("Error") not in ERROR_TYPES:
            raise Fail(
                "/%s: Error is %r, expected one of %s."
                % (path, body.get("Error"), ", ".join(sorted(ERROR_TYPES)))
            )
        if not isinstance(body.get("Message"), str) or not body["Message"].strip():
            raise Fail("/%s: error has no Message text: %r." % (path, body))
    return "All three errors have Error from Error_type and a Message."


# ====================================================================== teams and users (AC-04, AC-02)
AUTH_HASH = "tester-credential-not-a-real-secret"


def team_members(ctx: Context, team: str) -> List[str]:
    """GET a team and return its Members list."""
    body = expect_ok(ctx.team("GET", team), "Team Received")
    members = field(body, "Members")
    if not isinstance(members, list):
        raise Fail("/teams GET: Members should be a list of usernames, got %r." % (members,))
    return members


@test("T-55", "List the teams (LIST)", ("AC-04",))
def t55(ctx: Context):
    body = expect_ok(ctx.team("LIST"), "Teams Listed")
    teams = field(body, "Team_List")
    if not isinstance(teams, list):
        raise Fail("/teams LIST: Team_List should be a list, got %r." % (teams,))
    missing = [t for t in ctx.teams if t not in teams]
    if missing:
        raise Fail(
            "/teams LIST: Team_List %r is missing the default team(s) %s." % (teams, missing)
        )
    return "Team_List has %d teams, including %s." % (len(teams), ", ".join(ctx.teams))


@test("T-56", "Create a team (NEW)", ("AC-04",))
def t56(ctx: Context):
    name = ctx.team_name("main")
    body = expect_ok(ctx.team("NEW", name), "Created")
    expect_field(body, "Team_Name", name)
    return "Created team %r." % name


@test("T-57", "A created team is listed and has no members", ("AC-04",), after=("T-56",), db=True)
def t57(ctx: Context):
    name = ctx.team_name("main")
    teams = field(expect_ok(ctx.team("LIST"), "Teams Listed"), "Team_List")
    if not isinstance(teams, list) or name not in teams:
        raise Fail("/teams LIST: the new team %r is not in Team_List %r." % (name, teams))
    members = team_members(ctx, name)
    if members:
        raise Fail("A new team should have no members, got %r." % (members,))
    return "%r is listed and empty." % name


@test("T-58", "Reject a duplicate team", ("AC-04",), after=("T-56",))
def t58(ctx: Context):
    expect_error(ctx.team("NEW", ctx.team_name("main")), "TEAM_EXISTS")
    expect_error(ctx.team("NEW", ctx.teams[0]), "TEAM_EXISTS")
    return "NEW with an existing name rejected with TEAM_EXISTS."


@test("T-59", "Reject GET and REMOVE of an unknown team", ("AC-04",))
def t59(ctx: Context):
    name = ctx.team_name("never-created")
    expect_error(ctx.team("GET", name), "TEAM_DNE")
    expect_error(ctx.team("REMOVE", name), "TEAM_DNE")
    return "Unknown team rejected with TEAM_DNE."


@test("T-60", "Reject invalid /teams requests", ("AC-04",))
def t60(ctx: Context):
    expect_error(ctx.team("NEW"), "INVALID_DATA")  # no Team_Name
    expect_error(ctx.team("NEW", ""), "INVALID_DATA")
    expect_error(ctx.team("NEW", 42), "INVALID_DATA")
    expect_error(ctx.team("RENAME", ctx.team_name("invalid")), "INVALID_DATA")
    return "Missing, empty and non-string Team_Name and an unknown Method rejected."


@test("T-61", "Create a user (/users NEW)", ("AC-02",))
def t61(ctx: Context):
    name = ctx.username("main")
    body = expect_ok(ctx.user("NEW", name, Auth_Hash=AUTH_HASH), "Created")
    expect_field(body, "Username", name)
    if "Auth_Hash" in body:
        raise Fail("/users NEW returned the Auth_Hash; it should never be sent back.")
    return "Created user %r." % name


@test("T-62", "Reject a duplicate user and a user without Auth_Hash", ("AC-02",), after=("T-61",))
def t62(ctx: Context):
    expect_error(ctx.user("NEW", ctx.username("main"), Auth_Hash=AUTH_HASH), "USER_EXISTS")
    expect_error(ctx.user("NEW", ctx.username("no-hash")), "INVALID_DATA")
    expect_error(ctx.user("NEW", Auth_Hash=AUTH_HASH), "INVALID_DATA")  # no Username
    return (
        "Duplicate user rejected with USER_EXISTS; missing Auth_Hash or Username with INVALID_DATA."
    )


@test("T-63", "Add a user to a team (ADD_USER)", ("AC-04",), after=("T-56", "T-61"))
def t63(ctx: Context):
    team, user = ctx.team_name("main"), ctx.username("main")
    body = expect_ok(ctx.team("ADD_USER", team, Username=user), "User added")
    expect_field(body, "Team_Name", team)
    return "Added %s to %r." % (user, team)


@test("T-64", "A team's members are stored", ("AC-04",), after=("T-63",), db=True)
def t64(ctx: Context):
    team, user = ctx.team_name("main"), ctx.username("main")
    members = team_members(ctx, team)
    if members != [user]:
        raise Fail("Members of %r are %r; expected [%r]." % (team, members, user))
    return "GET %r lists %s." % (team, user)


@test("T-65", "Reject invalid membership changes", ("AC-04",), after=("T-63",))
def t65(ctx: Context):
    team, user = ctx.team_name("main"), ctx.username("main")
    expect_error(ctx.team("ADD_USER", team, Username=user), "USER_EXISTS")
    expect_error(ctx.team("ADD_USER", team, Username=ctx.username("never-created")), "USER_DNE")
    expect_error(ctx.team("ADD_USER", ctx.team_name("never-created"), Username=user), "TEAM_DNE")
    expect_error(ctx.team("ADD_USER", team), "INVALID_DATA")  # no Username
    return "Duplicate, unknown user, unknown team and missing Username rejected."


@test("T-66", "A new team can be assigned, notified and claim", ("AC-04",), after=("T-56", "T-01"))
def t66(ctx: Context):
    a, team = ctx.iid("A"), ctx.team_name("main")
    body = expect_ok(
        ctx.ticket("NEW", a, "Tester: work for the new team", Team_list=[team]), "Logged"
    )
    number = new_ticket_number(ctx, body, a)
    ctx.state["team_ticket"] = number
    expect_field(expect_ok(ctx.get_ticket(a, number), "Displayed"), "Team_List", [team])
    expect_ok(ctx.notifier("NOTIFY", [team], number), "Notified team")
    expect_ok(ctx.notifier("CLAIM", [team], number), "Claimed ticket")
    return "Ticket %s assigned to, notified to and claimed by %r." % (number, team)


@test("T-67", "A team that tickets use can't be removed", ("AC-04",), after=("T-66",))
def t67(ctx: Context):
    team = ctx.team_name("main")
    expect_error(ctx.team("REMOVE", team), "INVALID_DATA")
    expect_ok(ctx.team("GET", team), "Team Received")
    return "REMOVE of %r rejected; the team is still there." % team


@test("T-68", "Remove a user from a team (REMOVE_USER)", ("AC-04",), after=("T-64",), db=True)
def t68(ctx: Context):
    team, user = ctx.team_name("main"), ctx.username("main")
    expect_ok(ctx.team("REMOVE_USER", team, Username=user), "User removed")
    members = team_members(ctx, team)
    if user in members:
        raise Fail("%s is still a member of %r after REMOVE_USER: %r." % (user, team, members))
    expect_error(ctx.team("REMOVE_USER", team, Username=user), "USER_DNE")
    return "Removed %s from %r; removing again is USER_DNE." % (user, team)


@test("T-69", "Remove an unused team and its members", ("AC-04",), after=("T-61", "T-01"), db=True)
def t69(ctx: Context):
    team, user = ctx.team_name("spare"), ctx.username("main")
    expect_ok(ctx.team("NEW", team), "Created")
    expect_ok(ctx.team("ADD_USER", team, Username=user), "User added")
    body = expect_ok(ctx.team("REMOVE", team), "Removed")
    expect_field(body, "Team_Name", team)
    expect_error(ctx.team("GET", team), "TEAM_DNE")
    teams = field(expect_ok(ctx.team("LIST"), "Teams Listed"), "Team_List")
    if isinstance(teams, list) and team in teams:
        raise Fail("/teams LIST still has the removed team %r." % team)
    expect_error(
        ctx.ticket("NEW", ctx.iid("A"), "Tester: removed team", Team_list=[team]), "INVALID_DATA"
    )
    expect_ok(ctx.team("NEW", team), "Created")  # the name can be used again, with no members
    if team_members(ctx, team):
        raise Fail("A re-created team kept the members of the removed one.")
    return "Removed %r; it's gone, can't be assigned, and comes back empty." % team


@test("T-70", "Remove a user (/users REMOVE)", ("AC-02",), after=("T-61",))
def t70(ctx: Context):
    user = ctx.username("main")
    body = expect_ok(ctx.user("REMOVE", user), "Removed")
    expect_field(body, "Username", user)
    expect_error(ctx.user("REMOVE", user), "USER_DNE")
    expect_error(ctx.team("ADD_USER", ctx.teams[0], Username=user), "USER_DNE")
    return "Removed %s; removing again or adding them to a team is USER_DNE." % user


ALL_IDS = [t.test_id for t in SUITE]
assert len(ALL_IDS) == len(set(ALL_IDS)), "duplicate test IDs"
for _t in SUITE:
    for _dep in _t.after:
        assert ALL_IDS.index(_dep) < ALL_IDS.index(_t.test_id), (
            "%s runs before its prerequisite %s" % (_t.test_id, _dep)
        )
