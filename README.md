# SEC-Check

Incident tracking for SEC cybersecurity disclosure (Form 8-K Item 1.05).

```
api/   Core API (Express + TypeScript)
web/   Web app (Next.js) — coming
db/    SQL migrations — not wired up yet
```

## Setup

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Node 24.

```bash
git clone git@github.com:AndrewDile/SEC-Check.git
cd SEC-Check
docker compose up --build        # API at http://localhost:3001/health
```

Working on just the API (reloads on save):

```bash
cd api && npm install && npm run dev
```

## Adding a container

Put your part in its own folder with a `Dockerfile`, then add a service to `docker-compose.yml`.
Containers reach each other by service name, e.g. `http://api:3001`.
