"""The Core API calls the ingestion worker makes. Payloads are defined in core_api_contract.py."""

import httpx

from core_api_contract import Dependency, Incident, IncidentCreate
from ingestion_worker import config

_http = httpx.Client(
    base_url=config.CORE_API_URL,
    headers={"Authorization": f"Bearer {config.CORE_API_TOKEN}"},
    timeout=30,
)


def list_dependencies() -> list[Dependency]:
    """Every software dependency of every company."""
    response = _http.get("/v1/dependencies")
    response.raise_for_status()
    return [Dependency.model_validate(item) for item in response.json()]


def create_incident(incident: IncidentCreate) -> Incident:
    """Store an incident, or get the existing one back if it was already reported."""
    response = _http.post("/v1/incidents", json=incident.model_dump(mode="json"))
    response.raise_for_status()
    return Incident.model_validate(response.json())


def request_notifications(incident_id: str) -> None:
    """Ask the Core API to notify all of the incident's company's teams."""
    _http.post(f"/v1/incidents/{incident_id}/notifications").raise_for_status()
