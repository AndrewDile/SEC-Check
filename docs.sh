#!/usr/bin/env bash
# Preview the developer docs at http://127.0.0.1:8008 (reloads on save). Needs uv.
# `./docs.sh build` checks them the way the docs container does.
set -euo pipefail
cd "$(dirname "$0")"
mkdocs() { uvx --with-requirements docs/requirements.txt mkdocs "$@"; }

if [[ "${1:-}" == "build" ]]; then
    mkdocs build --strict -f docs/mkdocs.yml -d "$(mktemp -d)"
else
    mkdocs serve -f docs/mkdocs.yml -a 127.0.0.1:8008
fi
