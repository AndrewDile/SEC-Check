#!/usr/bin/env bash
# Lint every service. CI runs `./lint.sh`; run `./lint.sh --fix` to fix what it can.
set -euo pipefail
cd "$(dirname "$0")"
ruff() { uvx ruff@0.17.1 "$@"; }

if [[ "${1:-}" == "--fix" ]]; then
    ruff check --fix .
    (cd api && npm run lint:fix)
else
    ruff check .
    (cd api && npm run lint)
fi
