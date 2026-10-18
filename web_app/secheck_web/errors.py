"""Error envelope shared with the Core API: {"Error": ..., "Message": ...}.

Core errors pass through unchanged. The Web App adds UNAUTHORIZED, FORBIDDEN and
UPSTREAM_UNAVAILABLE (Web App API section 3.3).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

# HTTP status for each error code. Codes not listed here (including any new
# Core error codes) are returned with 400, matching the Core API.
STATUS_FOR_ERROR = {
    "TIMEOUT": 504,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "UPSTREAM_UNAVAILABLE": 502,
    "NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "NOT_IMPLEMENTED": 501,
    "INTERNAL_ERROR": 500,
}


def status_for(error: str) -> int:
    return STATUS_FOR_ERROR.get(error, 400)


class WebAppError(Exception):
    def __init__(
        self,
        error: str,
        message: str,
        status: Optional[int] = None,
        core_path: Optional[str] = None,
        completed_steps: Optional[List[str]] = None,
    ):
        super().__init__(message)
        self.error = error
        self.message = message
        self.status = status or status_for(error)
        self.core_path = core_path
        self.completed_steps = completed_steps

    def to_body(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {"Error": self.error, "Message": self.message}
        if self.core_path:
            body["Core_Path"] = self.core_path
        if self.completed_steps is not None:
            body["Completed_Steps"] = self.completed_steps
        return body


def invalid(message: str) -> WebAppError:
    return WebAppError("INVALID_DATA", message)


@contextmanager
def tracked(steps: List[str]) -> Iterator[List[str]]:
    """Attach the Core calls completed so far to any error (Web App API 3.4)."""
    try:
        yield steps
    except WebAppError as exc:
        if exc.completed_steps is None:
            exc.completed_steps = list(steps)
        raise
