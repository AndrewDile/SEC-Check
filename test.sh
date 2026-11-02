#!/usr/bin/env bash
# Run every test suite against the local stack. CI runs `./test.sh` before deploying.
# WIPES the local database: the API, DB and cross-team tests all reset it.
set -euo pipefail
cd "$(dirname "$0")"

# The API tests need DB_USER, DB_PASSWORD and INGEST_CORE_API_TOKEN from .env
set -a; . ./.env; set +a

E2E="docker compose -f docker-compose.yml -f docker-compose.e2e.yml"
E2E_SERVICES="ingestion-worker notification-service feed-mock"
# Left over if an earlier run failed. They would report incidents during the API tests.
$E2E rm -sf $E2E_SERVICES

# Only what the tests use: the ingestion worker would poll the real SEC and CISA feeds
docker compose up -d --build --wait db api tester caddy
for _ in {1..30}; do curl -sf localhost/system/health >/dev/null && break; sleep 1; done

(cd tester && python3 -m unittest discover -s tests)
uv run python -m unittest discover -s ingestion_worker/tests -t .
uv run python -m unittest discover -s notification_service/tests -t .
(cd api && API_URL=http://localhost/system DB_HOST=127.0.0.1 npm test)
# The tester calls the system from inside the compose network, where Caddy is "caddy"
python3 tester/run_tests.py http://caddy/system --tester http://localhost/tester

# Last, because it needs the worker and notifier, which the tests above must run without
$E2E up -d --build --wait $E2E_SERVICES
E2E_SYSTEM_URL=http://localhost/system uv run python -m unittest ingestion_worker.tests.test_e2e -v
$E2E rm -sf $E2E_SERVICES
