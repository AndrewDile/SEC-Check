#!/usr/bin/env bash
# Check the repo against the system model (architecture/model.yaml). CI runs it.
# `./verify.sh --list` lists the checks; `./verify.sh network` runs one group.
set -euo pipefail
cd "$(dirname "$0")"
uv run --no-project --with pyyaml==6.0.2 python -m architecture.verify "$@"
