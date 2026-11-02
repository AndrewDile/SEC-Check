"""Which users belong to which teams, as stored in the Core API database.

Teams and their members are both kept by the Core API: /teams NEW, REMOVE, GET (with
Members), ADD_USER and REMOVE_USER, and /users LIST/GET (each user's Teams). The Core API's
/reset (and every new test session) puts back the default memberships.

Handlers only call the methods here, so where memberships come from stays in one place.
"""

from __future__ import annotations

from typing import Dict, List

from .core_client import CoreClient
from .errors import WebAppError


class Memberships:
    def __init__(self, core: CoreClient):
        self.core = core

    def members(self) -> Dict[str, List[str]]:
        """team -> users, for every team that has members (one /users LIST call)."""
        out: Dict[str, List[str]] = {}
        for user in self.core.user_list(None):
            for team in user.get("Teams") or []:
                out.setdefault(team, []).append(user["Username"])
        return out

    def members_of(self, team: str) -> List[str]:
        """The team's members, in the order they joined. Raises TEAM_DNE if there's no such team."""
        return list(self.core.team_get(None, team).get("Members") or [])

    def teams_of(self, user: str) -> List[str]:
        """The user's teams; none if the database doesn't know the user."""
        try:
            return list(self.core.user_get(None, user).get("Teams") or [])
        except WebAppError as exc:
            if exc.error == "USER_DNE":
                return []
            raise

    def add(self, team: str, user: str) -> None:
        self.core.team_add_user(None, team, user)

    def remove(self, team: str, user: str) -> None:
        self.core.team_remove_user(None, team, user)
