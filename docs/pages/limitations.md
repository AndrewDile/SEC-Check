# Known limitations

These are the known limitations of SEC-Check as delivered, grouped by area.

## Security

- **No real sign-in.** The web app lets anyone pick any user, with no password (gap G-6).
- **The Core API's pod endpoints take no credentials.**
    - Anyone who can reach `/system/` can read and change every incident.
    - `/system/reset` without a test session **wipes the real data**, and anyone can call it.
      (`/test/setup` no longer does: it makes a separate copy for the session.)
    - **`X-User` is taken on trust.** Any caller can name any existing user, so the audit log's
      `actor` is only as reliable as the caller.
- **No authorization for decisions in the Core API.** Anyone can mark an incident material or
  reverse it (with a note). Only the web app checks `decision_teams`.
- **Test session limits are per IP.** `/test/setup` is capped at `MAX_TEST_SESSIONS` active
  sessions and `SETUPS_PER_MINUTE` per client IP, which slows abuse but doesn't stop someone
  from filling the active sessions.
- **Plain HTTP only.** There's no TLS, so tokens, the `/logs/` login and all data cross the
  network unencrypted.
- **Static tokens.** The service-to-service bearer tokens never rotate.

## Data and the audit trail

- **The audit chain isn't verified through any API.** `/logs` returns an incident's audit
  entries, but `verifyAuditChain()` has no endpoint, and entries not tied to an incident (teams,
  users, dependencies, `LIST` calls) can't be read through the API.
- **`/reset` erases the audit history** of the data it wipes.
- **Only one company.** Every dependency belongs to `company_id: "default"`.
- **The web app's teams and users come from its settings.** The Core API stores teams, users and
  members, but the web app on `main` still reads its own `settings.json`, so a user added only in
  the web app is rejected as `X-User`.
- **Dependencies are bare names.** They have no version, CPE, PURL or CIK, so the worker can
  match only on names, and EDGAR's CIK match never fires.
- **The web app doesn't show the filing deadline yet.** The Core API returns `Filing_Deadline`,
  but the web app's 8-K view still has it as `null` (gap G-8).
- **Holidays end with 2027.** `business_calendar` has to be extended for later years.
- **Partial writes.** The web app's multi-step operations aren't atomic; a failure partway leaves
  the earlier steps in place, and reports them in `Completed_Steps`.
- **Failed migrations need a hand.** MySQL can't roll back schema changes, so a migration that
  fails partway has to be repaired by hand.

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
- **Limited lookback for new dependencies.** A new dependency is checked against all of KEV, but
  EDGAR only as far back as `LOOKBACK_DAYS` (30). Older low-confidence KEV matches are skipped.
- **Backfilled incidents are silent.** Older KEV matches appear as incidents without a notification.
- **Low-confidence matches carry the source's priority.** A vendor-only or product-only match can
  still be labelled `[CRITICAL]` in its notification.
- **Later matches are only partly visible.** A dependency added to an existing incident appears in
  the notification and the audit log. The web app still shows only the first dependency.

## Testing

- **Missing tests.** The worker's feed parsers and the notifier's channels and API have none. The web app's
  tests aren't in this repo.
- **Code coverage is shared between overlapping sessions.** V8 can't tell which request ran a
  line, so sessions running at the same time count each other's lines (`basis` names them).
  Component coverage isn't measured.
- **Coverage costs speed.** Precise block coverage runs for the whole Core API process.
  `CODE_COVERAGE=off` turns it off.
- **A restart ends every open test session**, and their timings so far are lost.
- **Testers must send `X-Session-ID`.** A tester that names its session another way works on the
  real data until its header is added to `SESSION_HEADERS`.

## Operations

- **The health checks don't look far.**
    - The Core API's `/health` doesn't check the database.
    - The worker has no health endpoint.
    - Only the database and web app have Docker health checks.
- **Limited observability.**
    - There are no alerts. Request timings are summarized only per test session; for the real
      data there are just the per-request log lines.
    - Container logs are lost on every deploy.
    - Container logs aren't rotated, which risks filling the small disk.
- **Downtime on deploy.** Every deploy restarts every container, with a short outage.
- **One server.** A single small EC2 instance with no redundancy and no automated backups of
  the database.

## For the pod

Open questions to settle with Team 18, since they change the shared contract or how each other's
testers behave:

- **`/reset` without a session wipes the real data.** Should it need an admin token, now that test
  sessions have their own data?
- **The session header.** We read `X-Session-ID`; Team 18's tester uses a different one. We need
  one name (or both in `SESSION_HEADERS`).
- **Reversing a materiality decision.** The spec doesn't say whether `MATERIAL` can be changed
  back, who may do it, or whether the filing deadline restarts. We require a `Note`, audit it as
  `MATERIALITY_REVERSED`, and never restart the deadline. A test that reverses a `MATERIAL`
  incident without a `Note` fails against us.
- **Per-person tasks (AC-04).** The plan's independent evaluation assigns a task with a deadline
  to a person. We route work to teams (notify and claim) and keep one filing deadline per
  incident.
- **Extensions to agree on:** `Filing_Deadline` on incidents, `Note` on `EDIT`, `Audit_Log` on
  `/logs`, `Members` on `/teams GET`, and `GET`, `LIST`, `Contact_Channel` and `Display_Name` on
  `/users`.
- **Gaps in contract v1.0.2:**
    - Its Types list `DELETE` for `/teams` and `/users`, but its OpenAPI says `REMOVE`. We take both.
    - It doesn't name the errors for adding an existing member or removing a non-member. We use
      `USER_EXISTS` and `USER_DNE`.
    - `Contact` is one string with no channel, so we added `Contact_Channel`.
    - `Auth_Hash` has no defined hashing scheme and nothing verifies it yet.
- **Multi-step operations in one request (`/batch`).** Not built. Worth deciding for Phase 5
  whether the pod wants it, and with what limits.
- **Still open from Phase 3:** the `Incident_ID` type (integer, string or UUID), and how to
  handle unknown team names.
