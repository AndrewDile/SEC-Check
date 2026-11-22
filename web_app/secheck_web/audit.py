"""Text of the audit tickets the Web App writes for user actions (rule R-6).

The Core API has no actor field (gap G-6), so the acting user is written into
the ticket Description. The formats live here so they can change in one place.
The Core API's Form 8-K export (api/src/form8k.ts) leaves out tickets with these
prefixes, so change it too.
"""

from __future__ import annotations

from typing import Iterable

INTAKE = "INTAKE"
EDIT = "EDIT"
DECISION = "DECISION"
PREFIXES = (INTAKE, EDIT, DECISION)


def intake_text(user: str) -> str:
    return f"{INTAKE}: incident created via manual intake by {user}"


def edit_text(fields: Iterable[str], user: str) -> str:
    return f"{EDIT}: {', '.join(fields)} changed by {user}"


def decision_text(user: str, materiality: str, severity: str, urgency: str, rationale: str) -> str:
    return (
        f"{DECISION} by {user}: Materiality={materiality}; Severity={severity}; "
        f"Urgency={urgency}. Rationale: {rationale}"
    )
