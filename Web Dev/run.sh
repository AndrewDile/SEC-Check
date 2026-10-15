#!/usr/bin/env sh
# Start the SEC-Check Web App (and the mock Core API). Extra flags pass through.
cd "$(dirname "$0")" && exec python3 run.py "$@"
