#!/usr/bin/env bash
# Run every test suite against a throwaway stack, as CI does. CI runs `./test.sh` before deploying.
#
# Hermetic: the stack is its own compose project (sec-check-test) with a fresh database, built from
# .env.example, never .env. It publishes on other ports (18080, 13306, 18025, 18004), so it doesn't touch
# a dev stack or its data, and it's torn down after every run, passed or failed, volumes included.
set -euo pipefail
cd "$(dirname "$0")"

export COMPOSE_PROJECT_NAME=sec-check-test
export HTTP_PORT=18080 DB_HOST_PORT=13306 MAILPIT_PORT=18025 WEBHOOK_MOCK_PORT=18004
SYSTEM=http://localhost:$HTTP_PORT/system
LOG_FILE=${TMPDIR:-/tmp}/sec-check-test-compose.log

# Throwaway secrets for a throwaway stack. The API tests need its DB credentials and tokens too.
set -a; . ./.env.example; set +a
DC="docker compose --env-file .env.example -f docker-compose.yml -f docker-compose.e2e.yml"
E2E_SERVICES="ingestion-worker notification-service feed-mock mailpit webhook-mock"

if [ -n "$($DC ps -aq)" ]; then
  echo "A sec-check-test stack already exists: another ./test.sh is running, or one was killed." >&2
  echo "If none is running, remove it with: docker compose -p sec-check-test down -v" >&2
  exit 1
fi

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [ "$status" -ne 0 ]; then
    $DC logs --no-color >"$LOG_FILE" 2>&1 || true
    if [ "$status" -eq 130 ]; then echo "Interrupted." >&2; else echo "Tests failed." >&2; fi
    echo "Container logs: $LOG_FILE" >&2
    if [ -n "${CI:-}" ]; then cat "$LOG_FILE"; fi
  fi
  $DC down -v --remove-orphans >/dev/null 2>&1 || echo "Couldn't remove the sec-check-test stack." >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Only what the tests use: the ingestion worker would poll the real SEC and CISA feeds
$DC up -d --build --wait db api tester caddy
for _ in {1..30}; do curl -sf "$SYSTEM/health" >/dev/null && break; sleep 1; done

(cd tester && python3 -m unittest discover -s tests)
uv run python -m unittest discover -s ingestion_worker/tests -t .
uv run python -m unittest discover -s notification_service/tests -t .
(cd api && API_URL=$SYSTEM DB_HOST=127.0.0.1 DB_PORT=$DB_HOST_PORT npm test)
# The tester calls the system from inside the compose network, where Caddy is "caddy"
python3 tester/run_tests.py http://caddy/system --tester "http://localhost:$HTTP_PORT/tester"

# Last, because it needs the worker and notifier, which the tests above must run without
$DC up -d --build --wait $E2E_SERVICES
E2E_SYSTEM_URL=$SYSTEM E2E_MAILPIT_URL=http://localhost:$MAILPIT_PORT \
  E2E_WEBHOOKS_URL=http://localhost:$WEBHOOK_MOCK_PORT uv run python -m unittest ingestion_worker.tests.test_e2e -v
