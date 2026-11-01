#!/usr/bin/env bash
# Format every service. CI runs `./format.sh --check`; run `./format.sh` to format in place.
set -euo pipefail
cd "$(dirname "$0")"
ruff() { uvx ruff@0.17.1 "$@"; }

if [[ "${1:-}" == "--check" ]]; then
    ruff format --check .
    (cd api && npm run format:check)
else
    ruff format .
    (cd api && npm run format)
fi
