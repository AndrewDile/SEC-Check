#!/usr/bin/env bash
# Run every test suite against the local stack. CI runs `./test.sh` before deploying.
# WIPES the local database: the API, DB and cross-team tests all reset it.
set -euo pipefail
cd "$(dirname "$0")"

# The API tests need DB_USER, DB_PASSWORD and INGEST_CORE_API_TOKEN from .env
set -a; . ./.env; set +a

# Only what the tests use: the ingestion worker would poll the real SEC and CISA feeds
docker compose up -d --build --wait db api tester caddy
for _ in {1..30}; do curl -sf localhost/system/health >/dev/null && break; sleep 1; done

(cd tester && python3 -m unittest discover -s tests)
(cd api && API_URL=http://localhost/system DB_HOST=127.0.0.1 npm test)
# The tester calls the system from inside the compose network, where Caddy is "caddy"
python3 tester/run_tests.py http://caddy/system --tester http://localhost/tester
