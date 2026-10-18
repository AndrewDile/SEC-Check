"""Session store. Sessions and their reports live in memory until the process stops."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

READY, RUNNING, DONE = "ready", "running", "done"


@dataclass
class Session:
    session_id: str
    target_url: str
    state: str = READY
    report: Optional[Dict[str, Any]] = None


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, Session] = {}

    @staticmethod
    def new_id() -> str:
        return "run-" + str(uuid.uuid4())

    def add(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(session_id)

    def start_run(self, session_id: str) -> Optional[Session]:
        """Atomically move a session from ready to running. None if it isn't ready."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.state != READY:
                return None
            session.state = RUNNING
            return session

    def finish(self, session_id: str, report: Dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.report = report
            session.state = DONE
