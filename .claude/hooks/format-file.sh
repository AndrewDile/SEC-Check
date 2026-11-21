#!/usr/bin/env bash
# PostToolUse (Edit|Write): format the edited file with the same tools and versions as
# format.sh. Skips quietly when uv or the API's node_modules aren't installed.
f=$(jq -r '.tool_input.file_path // empty')
api="$CLAUDE_PROJECT_DIR/api"

case "$f" in
    *.py)
        command -v uvx >/dev/null && uvx ruff@0.17.1 format -q "$f" ;;
    "$api"/*.ts|"$api"/*.json)
        [ -x "$api/node_modules/.bin/biome" ] &&
            (cd "$api" && node_modules/.bin/biome format --write "$f" >/dev/null 2>&1) ;;
esac
exit 0
