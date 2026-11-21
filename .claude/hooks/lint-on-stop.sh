#!/usr/bin/env bash
# Stop: run ./lint.sh before Claude finishes, if Python or TypeScript files changed. On failure,
# exit 2 sends the errors back so Claude fixes them. Only one retry per stop, to avoid loops.
input=$(cat)
[ "$(jq -r '.stop_hook_active' <<<"$input")" = "true" ] && exit 0

cd "$CLAUDE_PROJECT_DIR" || exit 0
# lint.sh needs uv (ruff) and the API's node_modules (tsc, Biome)
command -v uvx >/dev/null && [ -d api/node_modules ] || exit 0
git status --porcelain | grep -qE '\.(py|ts)$' || exit 0

if ! out=$(./lint.sh 2>&1); then
    echo "./lint.sh failed; fix these before finishing (./lint.sh --fix fixes some):" >&2
    tail -n 40 <<<"$out" >&2
    exit 2
fi
exit 0
