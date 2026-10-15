"""The Core API calls the notification service makes. Payloads are in core_api.openapi.yaml."""

import httpx

from notification_service import config
from notification_service.models import DeliveryResult, NotificationResults

_http = httpx.Client(
    base_url=config.CORE_API_URL,
    headers={"Authorization": f"Bearer {config.CORE_API_TOKEN}"},
    timeout=30,
)


def report_results(notification_id: str, results: list[DeliveryResult]) -> None:
    """Tell the Core API which recipients were reached, for the audit trail."""
    body = NotificationResults(results=results)
    response = _http.post(
        f"/notif/notifications/{notification_id}/results", json=body.model_dump(mode="json")
    )
    response.raise_for_status()
