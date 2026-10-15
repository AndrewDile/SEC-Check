# Open decisions

What the code assumes today, and what still needs deciding. Part 1 touches the Core API, so
the whole team should weigh in. Part 2 only affects these two services.

## Part 1: For the team (Core API)

1. **Transport and auth.** REST + JSON, and every call sends a static bearer token set by an
   environment variable, with a separate token for each direction. Alternatives: mTLS or
   OAuth client credentials.
2. **Duplicate incidents.** The Core API treats `(company_id, source, external_id)` as unique,
   and reporting the same incident again returns the existing one with `200`. The worker
   relies on this, because every poll re-reports everything in its lookback window.
3. **Who triggers notifications.** The worker calls `POST /v1/incidents/{id}/notifications`
   after creating an incident. The alternative is for the Core API to notify automatically
   whenever it creates one. That saves a call, but takes control away from the worker.
4. **`notification_requested_at`.** The Core API sets it only after the notification service
   answers `202`. While it is empty, the worker asks again on every poll, so a notifier that
   was down is retried automatically.
5. **Recipients.** The Core API turns "every team of company X" into a list of `Recipient`s
   (`channel` + `address`). That means the DB must store each team's contact methods.
6. **Claim link.** The Core API puts `claim_url` in each notification. The web-app team
   decides what the URL looks like.
7. **Delivery results.** The notification service reports which recipients were reached and
   which weren't. The DB should keep these as the audit trail ("security team notified at 10:42").
8. **Dependency records.** `vendor` and `product` are required; `version`, `cpe`, `purl` and
   `vendor_cik` are optional. The web app has to collect them. Matching uses only `vendor`,
   `product` and `vendor_cik` for now. `cpe` and `purl` are there for future sources (NVD, OSV).
9. **Pagination.** `GET /v1/dependencies` returns everything in one response. That's fine
   for now; add paging once there are many companies.

## Part 2: For the two services

10. **SEC contact.** The SEC requires a `User-Agent` that names us and gives a contact email
    (`SEC_USER_AGENT`). Which one should we use?
11. **Lookback window: 30 days.** A dependency added today is not matched against older KEV
    entries or filings.
12. **Poll intervals.** KEV every hour, EDGAR every 15 minutes.
13. **Weak matches are sent.** When product names only overlap (KEV's "Windows" vs. our
    "Windows Server 2019"), the match is still sent, marked `medium` confidence.
14. **Priority hints.** KEV entries are `critical` if CISA has seen them used by ransomware,
    otherwise `high`. 8-K filings are `critical` under Item 1.05 and `high` under Item 8.01.
    Hints are for sorting only. The system never says whether an incident is material.
15. **Notification durability.** Accepted notifications live only in memory. If the
    notification service crashes after answering `202` and before sending, that notification
    is lost. The fixes are a local queue, or having the notifier pull pending jobs from the
    Core API.
16. **One recipient at a time.** Delivery is sequential, retrying after 2s and then 4s. That's
    fine with only the log channel; real channels may need to send in parallel.
17. **Unclaimed incidents.** No reminders or escalation yet. The Core API can simply send
    another `NotificationRequest` later.
18. **Deployment.** Not decided. The worker's `--once` flag lets it run from cron, a
    Kubernetes CronJob or a serverless scheduler. The notifier is an ordinary web app.

## Known limitations

- **Versions are ignored.** KEV doesn't say which versions are affected, so a match means
  "you use this product", not "your version is vulnerable".
- **Name matching is fuzzy.** It can miss: "Google Chrome" doesn't match KEV's "Google
  Chromium V8". It can also match wrongly: two vendors with the same name match each other.
  Filling in `vendor_cik` makes EDGAR matches exact.
- **EDGAR full-text search is undocumented** and could change. The documented fallback is
  `https://data.sec.gov/submissions/CIK##########.json`, whose `items` field lists each
  8-K's items, but that only works for vendors whose CIK we know.
- **Filings with several filers.** When an 8-K lists several companies (e.g. a parent and its
  subsidiaries), only the first one is matched.
- **Not built yet:** tests, a Core API stub for running locally, and Docker files.
