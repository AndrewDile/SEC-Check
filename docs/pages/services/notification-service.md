# Notification service

**Folder:** `notification_service/`. **Stack:** Python 3.13, FastAPI, httpx and Pydantic, through
uv with the root `pyproject.toml`. **Port:** 8001, inside the stack only.

The notification service delivers a notice about each new **ingested** incident to every team,
then reports to the Core API who was reached. It isn't involved in the web app's `MATERIAL`
decision notices, which are only database records (see [Architecture](../architecture.md#materiality-decision-web-app)).

## How it works

1. **Accept:** the Core API sends `POST /notifications` with a `NotificationRequest`. The service
   answers `202` right away.
    - **Updates:** a notice with `added_dependency_ids` is about newly matched dependencies on
      an existing incident. Its subject starts with `Update:` and its body names them first.
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

The Core API sends each team's contacts (see [team contacts](core-api.md#post-teams)), and a team
with no contacts as a `log` recipient. Every channel renders the same message
(`dispatcher.render`) in its own format:

| Channel | File | Sends | Gives up on (no retry) | Retries |
|---|---|---|---|---|
| `email` | `channels/email.py` | A plain-text email over SMTP (`smtplib`), from `SMTP_FROM` | Email not set up, a refused recipient, a failed login, any `5xx` reply, a server without STARTTLS | `4xx` replies, connection errors, timeouts |
| `slack` | `channels/slack.py` | A [Block Kit](https://api.slack.com/block-kit) message to an incoming webhook: the subject as a header, the body, and a **Claim this incident** button | Any `3xx` or `4xx` but `429` (a removed webhook answers `404`, `403` or `410`) | `429`, `5xx`, connection errors, timeouts |
| `ms_teams` | `channels/teams.py` | An Adaptive Card to a Teams Workflows webhook, with the same parts | The same as Slack | The same as Slack |
| `log` | `channels/log.py` | A line in the service's log | Nothing | Nothing |

- **Webhook hosts:** Slack and Teams check the host again before posting (`hooks.slack.com`,
  `*.logic.azure.com`, `*.api.powerplatform.com`, over HTTPS), as the Core API does when the
  contact is added. They don't follow redirects, so a webhook can't send the notifier elsewhere.
- **Limits:** Slack's header is cut to 150 characters and its body to 3000, Block Kit's limits.
  Slack's markup characters (`&`, `<`, `>`) are escaped.
- **Teams lines:** the card has one text block per line of the body, because Teams clients don't
  agree on how to show newlines inside one block.
- **Email:** works with any SMTP server. For Gmail, use `smtp.gmail.com`, port 587, `starttls`,
  and an [app password](https://support.google.com/accounts/answer/185833), not the account's
  password. Gmail limits how many emails an account can send a day.
- **Reading `log` notices:** use [the log viewer](../operations.md#log-viewer) or
  `docker compose logs notification-service`.

To add a channel:

1. Subclass `Channel` in `channels/base.py`, and set `name` to the value the Core API will put
   in `Recipient.channel`.
2. Implement `send`. Raise `PermanentDeliveryError` when trying again can't help.
3. Add the channel to `CHANNELS` in `channels/__init__.py`.
4. Change the Core API's `notify()` in `api/src/services.ts` to send recipients for it.

## Interfaces

**Notification service API**, which only the Core API calls, with `NOTIF_INBOUND_TOKEN`. The
`/coverage` calls give the Core API the notifier's code coverage for `/test/report`.
`line_coverage.py` (generated from the web app's copy) answers them as middleware, so they run none
of the notifier's lines, and the Docker health check's `/healthz` doesn't count either.

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
| `CODE_COVERAGE` | on | `off` stops counting lines |
| `MAX_ATTEMPTS` | `3` | Tries per recipient |
| `HTTP_TIMEOUT_S` | `10` | Timeout for each webhook post and SMTP connection, in seconds |
| `SMTP_HOST` | empty | SMTP server. Empty turns email off: email notices fail, saying it isn't set up |
| `SMTP_PORT` | `587` | SMTP port (465 for `ssl`) |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (TLS from the start) or `none` (only for a local test server) |
| `SMTP_USER`, `SMTP_PASSWORD` | empty | Login. With `SMTP_USER` empty, it doesn't log in |
| `SMTP_FROM` | `SMTP_USER` | The sender address. Email is off without one |
| `HOST`, `PORT` | `127.0.0.1`, `8001` (the image sets `0.0.0.0`) | Where it listens |
| `LOG_LEVEL` | `INFO` | Python logging level |
