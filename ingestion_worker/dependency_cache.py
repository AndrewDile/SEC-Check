"""The worker's copy of every company's dependencies.

It is loaded from the Core API on the first poll, then kept up to date by the dependency
events the Core API sends (see app.py). It lives in memory only, so a restarted worker
loads it again.
"""

import threading

from ingestion_worker import core_api
from ingestion_worker.models import Dependency

# None until the first load succeeds. Events that arrive before then are dropped, because
# the load that follows already includes them.
_dependencies: dict[str, Dependency] | None = None
# The poll loop and the event handlers run on different threads.
_lock = threading.Lock()


def get_all() -> list[Dependency]:
    """Every dependency of every company, loading them from the Core API if needed."""
    global _dependencies
    with _lock:
        if _dependencies is None:
            _dependencies = {d.id: d for d in core_api.list_dependencies()}
        return list(_dependencies.values())


def put(dependency_id: str, dependency: Dependency) -> None:
    with _lock:
        if _dependencies is not None:
            _dependencies[dependency_id] = dependency


def delete(dependency_id: str) -> None:
    with _lock:
        if _dependencies is not None:
            _dependencies.pop(dependency_id, None)
