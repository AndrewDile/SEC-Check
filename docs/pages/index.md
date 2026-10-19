# SEC-Check developer docs

!!! info "These are developer docs, not user docs"
    They describe SEC-Check as delivered, for the people who build, test and run it: the services, the
    interfaces between them, the data model, how to run and deploy it, and its known limitations.
    They don't explain how to use the web app to handle an incident.

SEC-Check tracks cybersecurity incidents that a company may have to disclose to the SEC on
Form 8-K, Item 1.05. Incidents come in two ways:

- **Manually:** someone enters them in the web app.
- **Automatically:** the ingestion worker finds public reports, from the CISA KEV catalog and
  SEC EDGAR 8-K filings, about software the company depends on.

Teams then triage each incident through tickets, record a materiality decision, and see the
facts the 8-K needs gathered in one view. Every change and every read is kept in an append-only,
hash-chained audit log.

## The services

| Service | Folder | Language | Public path | What it does |
|---|---|---|---|---|
| [Core API](services/core-api.md) | `api/` | TypeScript (Express) | `/system/` | Owns the data. Implements the pod's Core API contract, plus the endpoints the other services use |
| Database | `db/` | MySQL 8.4 | none | Incidents, ticket versions, claims, notifications, dependencies, teams, audit log |
| [Web app](services/web-app.md) | `web_app/` | Python (standard library only) | `/` | Browser UI, plus the Web App API that the browser calls; it does everything through the Core API |
| [Ingestion worker](services/ingestion-worker.md) | `ingestion_worker/` | Python (FastAPI) | none | Polls CISA KEV and SEC EDGAR, matches events to dependencies, and reports possible incidents |
| [Notification service](services/notification-service.md) | `notification_service/` | Python (FastAPI) | none | Delivers notices of new ingested incidents to each team |
| [Tester](services/tester.md) | `tester/` | Python (standard library only) | `/tester/` | The cross-team tester: runs a 54-test suite against any team's system |
| Reverse proxy | `Caddyfile` | Caddy 2.10 | port 80 | The only public port; sends each path prefix to its container |
| Log viewer | n/a | Dozzle | `/logs/` | Live logs for every container, behind a password |
| Docs | `docs/` | MkDocs Material | `/docs/` | This site |

## Where to start

- To run it: [Getting started](getting-started.md).
- To see how the pieces fit: [Architecture](architecture.md), then [Data model](data-model.md).
- Before you rely on something: [Known limitations](limitations.md).
- Each service's interface, as OpenAPI with Swagger UI, is on its page under **Services**.
