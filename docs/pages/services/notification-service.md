# Notification service

**Folder:** `notification_service/`. **Stack:** Python 3.13, FastAPI, httpx and Pydantic, through
uv with the root `pyproject.toml`. **Port:** 8001, inside the stack only.

The notification service delivers a notice about each new **ingested** incident to every team,
then reports to the Core API who was reached. It isn't involved in the web app's `MATERIAL`
decision notices, which are only database records (see [Architecture](../architecture.md#materiality-decision-web-app)).

## How it works

1. **Accept:** the Core API sends `POST /notifications` with a `NotificationRequest`. The service
   answers `202` right away.
    - **Retries:** a `notification_id` it has already accepted is a no-op, so the Core API can
      retry safely.
    - **Delivery:** happens after the response, as a FastAPI background task.
2. **Render:** `dispatcher.render` builds one message for every channel:
    - **Subject:** `[<PRIORITY>] Possible cybersecurity incident: <title>`.
    - **Body:** the summary, the matched dependencies with their confidence and reason, the
      source link, and the claim link.
    - **Disclaimer:** the notice says it doesn't decide materiality.
3. **Deliver:** for each recipient, it looks up the channel by `Recipient.channel`, then sends.
    - **Retries:** up to `MAX_ATTEMPTS` (default 3), waiting 2 s, 4 s and so on between tries.
    - **Permanent errors:** a `PermanentDeliveryError` stops the retries for that recipient.
    - **Unknown channel:** `failed`, with `attempts: 0`.
4. **Report:** `POST /notif/notifications/{id}/results` with one `DeliveryResult` per
   recipient. The Core API stores them in the audit log.

## Channels

The only channel is **`log`** (`channels/log.py`): it writes the message to the service's log. The
Core API sends every team as a `log` recipient, so no email, SMS or chat message is sent yet. To
read the notices, use [the log viewer](../operations.md#log-viewer) or
`docker compose logs notification-service`.

To add a channel:

1. Subclass `Channel` in `channels/base.py`, and set `name` to the value the Core API will put
   in `Recipient.channel`.
2. Implement `send`. Raise `PermanentDeliveryError` when trying again can't help.
3. Add the channel to `CHANNELS` in `channels/__init__.py`.
4. Change the Core API's `notify()` in `api/src/services.ts` to send recipients for it.

## Interfaces

**Notification service API**, which only the Core API calls, with `NOTIF_INBOUND_TOKEN`.

<swagger-ui src="../openapi/notification_service/openapi.yaml"/>

**Core API endpoint the service calls**, with `NOTIF_CORE_API_TOKEN`, and the payloads they
share. `models.py` is generated from this file by `generate_models.sh`.

<swagger-ui src="../openapi/notification_service/core_api.openapi.yaml"/>

There's also `GET /healthz`, which returns `{"status": "ok"}`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CORE_API_URL` | `http://localhost:8000` (Compose sets `http://api:3001`) | Core API base URL |
| `CORE_API_TOKEN` | required | Sent to the Core API |
| `INBOUND_TOKEN` | required | Expected from the Core API |
| `MAX_ATTEMPTS` | `3` | Tries per recipient |
| `HOST`, `PORT` | `127.0.0.1`, `8001` (the image sets `0.0.0.0`) | Where it listens |
| `LOG_LEVEL` | `INFO` | Python logging level |
