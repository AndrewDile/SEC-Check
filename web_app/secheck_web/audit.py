"""Text of the audit tickets the Web App writes for user actions (rule R-6).

The Core API has no actor field (gap G-6), so the acting user is written into
the ticket Description. The formats live here so they can change in one place,
and so the 8-K view can read decision tickets back.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, Optional

INTAKE = "INTAKE"
EDIT = "EDIT"
DECISION = "DECISION"
PREFIXES = (INTAKE, EDIT, DECISION)

_DECISION_RE = re.compile(
    r"^DECISION by (?P<user>[^:]+): Materiality=(?P<Materiality>[A-Z_]+); "
    r"Severity=(?P<Severity>[A-Z_]+); Urgency=(?P<Urgency>[A-Z_]+)\. Rationale: (?P<Rationale>.*)$",
    re.S,
)


def intake_text(user: str) -> str:
    return f"{INTAKE}: incident created via manual intake by {user}"


def edit_text(fields: Iterable[str], user: str) -> str:
    return f"{EDIT}: {', '.join(fields)} changed by {user}"


def decision_text(user: str, materiality: str, severity: str, urgency: str, rationale: str) -> str:
    return (
        f"{DECISION} by {user}: Materiality={materiality}; Severity={severity}; "
        f"Urgency={urgency}. Rationale: {rationale}"
    )


def is_audit(description: Optional[str]) -> bool:
    text = description or ""
    return any(text.startswith(p + ":") or text.startswith(p + " by ") for p in PREFIXES)


def parse_decision(description: Optional[str]) -> Optional[Dict[str, str]]:
    match = _DECISION_RE.match(description or "")
    return match.groupdict() if match else None
