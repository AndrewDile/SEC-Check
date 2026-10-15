#!/usr/bin/env sh
# Run the automated tests (no server needs to be running).
cd "$(dirname "$0")" && exec python3 -m unittest "$@"
