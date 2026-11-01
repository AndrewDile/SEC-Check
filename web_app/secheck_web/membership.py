"""Which users belong to which teams.

The teams themselves live in the Core API database (/teams). Membership isn't stored
there yet, so for now the Web App keeps it (LocalMembershipStore, a JSON file seeded
from the users in config/settings.json). When the Core API stores members, set
"membership_source": "core" and CoreMembershipStore reads and writes them through the
/teams path instead; nothing else in the Web App needs to change.

Every store answers the same questions, so handlers only ever call these methods.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .core_client import CoreClient
from .errors import WebAppError


class MembershipStore:
    """Interface. Team names are not checked here; handlers check them against the Core API."""

    def members(self) -> Dict[str, List[str]]:
        """team -> users, for every team that has members."""
        raise NotImplementedError

    def add(self, team: str, user: str) -> None:
        raise NotImplementedError

    def remove(self, team: str, user: str) -> None:
        raise NotImplementedError

    def drop_team(self, team: str) -> None:
        """Forget every membership of a team that was removed."""
        raise NotImplementedError

    def reset(self) -> None:
        """Back to the starting memberships (development and tests only)."""
        raise NotImplementedError

    # Derived answers, the same for every store
    def members_of(self, team: str) -> List[str]:
        return list(self.members().get(team, []))

    def teams_of(self, user: str) -> List[str]:
        return [team for team, users in self.members().items() if user in users]


def seed_from_users(users: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """settings.json lists each user's teams; turn that into team -> users."""
    out: Dict[str, List[str]] = {}
    for user, teams in users.items():
        for team in teams:
            out.setdefault(team, []).append(user)
    return out


class LocalMembershipStore(MembershipStore):
    """Memberships in a JSON file ({"team": ["user", ...]}), kept by the Web App."""

    def __init__(self, path: Optional[Path], seed: Dict[str, List[str]]):
        self.path = Path(path) if path else None
        self.seed = {team: list(users) for team, users in seed.items()}
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> Dict[str, List[str]]:
        if self.path and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(t): [str(u) for u in users] for t, users in data.items()}
            except (OSError, ValueError):
                pass  # unreadable file: start again from the seed
        return {team: list(users) for team, users in self.seed.items()}

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:  # memberships still work, but won't survive a restart
            print(f"Could not save team memberships to {self.path}: {exc}", flush=True)

    def members(self) -> Dict[str, List[str]]:
        with self._lock:
            return {team: list(users) for team, users in self._data.items() if users}

    def add(self, team: str, user: str) -> None:
        with self._lock:
            users = self._data.setdefault(team, [])
            if user not in users:
                users.append(user)
                self._save()

    def remove(self, team: str, user: str) -> None:
        with self._lock:
            if user in self._data.get(team, []):
                self._data[team].remove(user)
                self._save()

    def drop_team(self, team: str) -> None:
        with self._lock:
            if self._data.pop(team, None) is not None:
                self._save()

    def reset(self) -> None:
        with self._lock:
            self._data = {team: list(users) for team, users in self.seed.items()}
            self._save()


class CoreMembershipStore(MembershipStore):
    """Memberships kept by the Core API (/teams ADD_USER, REMOVE_USER, and GET with Members).

    For when the database stores team members. Until then the Core API rejects
    ADD_USER and REMOVE_USER, so keep "membership_source": "local".
    """

    def __init__(self, core: CoreClient):
        self.core = core

    def members(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for team in self.core.team_list(None):
            users = self.core.team_get(None, team).get("Members") or []
            if users:
                out[team] = list(users)
        return out

    def add(self, team: str, user: str) -> None:
        self.core.team_add_user(None, team, user)

    def remove(self, team: str, user: str) -> None:
        self.core.team_remove_user(None, team, user)

    def drop_team(self, team: str) -> None:
        pass  # the Core API removes a team's members with the team

    def reset(self) -> None:
        raise WebAppError(
            "NOT_IMPLEMENTED", "Memberships kept by the Core API are reset with /reset."
        )


def make_membership_store(settings: Settings, core: CoreClient) -> MembershipStore:
    if settings.membership_source == "core":
        return CoreMembershipStore(core)
    if settings.membership_source != "local":
        raise ValueError("membership_source must be 'local' or 'core'")
    return LocalMembershipStore(settings.membership_file, seed_from_users(settings.users))
