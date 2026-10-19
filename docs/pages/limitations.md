# Known limitations

These are the known limitations of SEC-Check as delivered, grouped by area.

## Security

- **No real sign-in.** The web app lets anyone pick any user, with no password (gap G-6).
- **The Core API's pod endpoints take no credentials.**
    - Anyone who can reach `/system/` can read and change every incident.
    - `/system/reset` and `/system/test/setup` **wipe the database**, and anyone can call them.
- **Plain HTTP only.** There's no TLS, so tokens, the `/logs/` login and all data cross the
  network unencrypted.
- **Static tokens.** The service-to-service bearer tokens never rotate.
- **No actor in the audit log.** `audit_log.actor` is never filled in. The acting user appears
  only in the text of the web app's audit tickets.

## Data and the audit trail

- **The audit log can't be read through any API.** `/logs` returns ticket version IDs, not audit
  entries. `verifyAuditChain()` exists but no endpoint calls it.
- **Resets erase the audit history.** `/reset` and `/test/setup` truncate the audit log too.
- **Only one company.** Every dependency belongs to `company_id: "default"`.
- **Fixed teams.**
    - The teams are `LEGAL`, `CYBER1` and `CYBER2`, and there's no API to add or change them.
    - The web app's `teams` setting must match them.
- **Dependencies are bare names.** They have no version, CPE, PURL or CIK, so the worker can
  match only on names, and EDGAR's CIK match never fires.
- **No filing deadline.** The 8-K view's `Filing_Deadline` is always `null` (gap G-8).
- **Manual schema changes.** Migrations run only on a new database volume.
- **Partial writes.** The web app's multi-step operations aren't atomic; a failure partway leaves
  the earlier steps in place, and reports them in `Completed_Steps`.

## Ingestion and notifications

- **Notifications aren't sent anywhere yet.** The only channel is `log`, so a notice is a line
  in the notification service's log.
- **MATERIAL decisions don't go through the notification service.** The web app's notice for a
  `MATERIAL` decision is only a database record, made through `/notifier NOTIFY`.
- **Failed calls are eventually dropped.**
    - The Core API's calls to the worker and notifier are retried 5 times, then dropped with one
      error line.
    - The retry queue is in memory, so a restart loses it.
- **State that a restart loses:**
    - **Notifier:** the record of which notifications it already accepted, so a retry after a
      restart may send twice.
    - **Worker:** its dependency cache (it reloads it).
    - **Tester:** its reports.
- **Matching is name-based and ignores versions.** False positives are expected; the team that
  claims an incident checks whether its version is affected.
- **EDGAR's search API is undocumented.** It can change without notice.
- **A short lookback.** Events older than `LOOKBACK_DAYS` (30) are never matched, even for a
  dependency added later.

## Testing

- **Missing tests.** The ingestion worker and notification service have none. The web app's
  tests aren't in this repo.
- **No code coverage.** `/test/report` gives `null` for it, and component coverage isn't
  measured.
- **One test session at a time.** A new `/test/setup` ends the previous session and wipes its
  data. Teams can't test our system concurrently.

## Operations

- **The health checks don't look far.**
    - The Core API's `/health` doesn't check the database.
    - The worker has no health endpoint.
    - Only the database and web app have Docker health checks.
- **Limited observability.**
    - There are no metrics or alerts, and the Core API has no request log.
    - Container logs are lost on every deploy.
    - Container logs aren't rotated, which risks filling the small disk.
- **Downtime on deploy.** Every deploy restarts every container, with a short outage.
- **One server.** A single small EC2 instance with no redundancy and no automated backups of
  the database.
