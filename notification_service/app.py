"""The notification service's HTTP API. Its only caller is the Core API."""

import secrets

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException

from core_api_contract import NotificationRequest
from notification_service import config
from notification_service.dispatcher import dispatch

app = FastAPI(title="Notification Service")

# IDs of notifications already accepted, so that a retry from the Core API isn't sent twice.
# Kept in memory only: a restart forgets them.
_accepted: set[str] = set()


def _check_token(authorization: str = Header("")) -> None:
    if not secrets.compare_digest(authorization, f"Bearer {config.INBOUND_TOKEN}"):
        raise HTTPException(status_code=401)


@app.post("/v1/notifications", status_code=202, dependencies=[Depends(_check_token)])
def accept_notification(request: NotificationRequest, background: BackgroundTasks) -> dict:
    """Accept a notification and deliver it after responding."""
    if request.notification_id not in _accepted:
        _accepted.add(request.notification_id)
        background.add_task(dispatch, request)
    return {"notification_id": request.notification_id}


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}
