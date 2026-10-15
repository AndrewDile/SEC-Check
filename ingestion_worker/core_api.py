"""The Core API calls the ingestion worker makes, as defined in core_api.openapi.yaml."""

import httpx

from ingestion_worker import config
from ingestion_worker.models import Dependency, IncidentCreate

_http = httpx.Client(
    base_url=config.CORE_API_URL,
    headers={"Authorization": f"Bearer {config.CORE_API_TOKEN}"},
    timeout=30,
)


def list_dependencies() -> list[Dependency]:
    """Every software dependency of every company."""
    response = _http.get("/ingest/dependencies")
    response.raise_for_status()
    return [Dependency.model_validate(item) for item in response.json()]


def create_incident(incident: IncidentCreate) -> bool:
    """Store an incident. Returns False if the Core API already had it."""
    response = _http.post("/ingest/incidents", json=incident.model_dump(mode="json"))
    response.raise_for_status()
    return response.status_code == 201
