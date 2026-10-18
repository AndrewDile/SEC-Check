"""Coverage measures for the report.

Coverage counts what was exercised, not what passed:
  component  not measured yet (null/null)
  system     acceptance criteria AC-01..AC-06; one counts when a test mapped to it got a response
  code       copied from the target's /test/report (coverage.code)
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set

CRITERIA = ["AC-01", "AC-02", "AC-03", "AC-04", "AC-05", "AC-06"]


def measure(covered: Optional[int], total: Optional[int], basis: str) -> Dict[str, Any]:
    return {"covered": covered, "total": total, "basis": basis}


def component_coverage() -> Dict[str, Any]:
    """Component coverage isn't measured yet; the spec allows null/null with the reason."""
    return measure(None, None, "not yet measured")


def system_coverage(responded_criteria: Iterable[str]) -> Dict[str, Any]:
    hit: Set[str] = set(responded_criteria) & set(CRITERIA)
    missing = [c for c in CRITERIA if c not in hit]
    basis = "Acceptance criteria with at least one answered test: %s." % (
        ", ".join(c for c in CRITERIA if c in hit) or "none"
    )
    if missing:
        basis += " Not exercised: %s." % ", ".join(missing)
    basis += " AC-06 is covered only as far as the Core /logs path goes."
    return measure(len(hit), len(CRITERIA), basis)


def code_coverage(status: Optional[int], body: Any, problem: str = "") -> Dict[str, Any]:
    """Read coverage.code from the target's /test/report reply; null/null with the reason otherwise."""
    if problem:
        return measure(None, None, problem)
    if status != 200:
        return measure(None, None, "Target /test/report answered %s; no code coverage." % status)
    code = (
        body.get("coverage", {}).get("code")
        if isinstance(body, dict) and isinstance(body.get("coverage"), dict)
        else None
    )
    if not isinstance(code, dict):
        return measure(None, None, "Target /test/report has no coverage.code object.")
    covered, total, basis = code.get("covered"), code.get("total"), code.get("basis")
    target_basis = basis.strip() if isinstance(basis, str) and basis.strip() else ""
    if covered is None and total is None:
        return measure(None, None, target_basis or "Target reported no code coverage (null).")
    if not (_count(covered) and _count(total)) or covered > total:
        return measure(
            None,
            None,
            "Target coverage.code is malformed (covered=%r, total=%r)." % (covered, total),
        )
    return measure(covered, total, target_basis or "Reported by the target system.")


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
