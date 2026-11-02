#!/usr/bin/env bash
# PreToolUse (Edit|Write): block edits to files that are generated, secret or already applied.
# Exit 2 blocks the edit and shows Claude the message, so it changes approach.
f=$(jq -r '.tool_input.file_path // empty')

case "$f" in
    */models.py)
        echo "models.py is generated: edit core_api.openapi.yaml and run generate_models.sh (see /regen-contracts)" >&2 ;;
    */.env)
        echo ".env holds real secrets; edit it by hand. Template changes go in .env.example" >&2 ;;
    */uv.lock|*/package-lock.json)
        echo "$(basename "$f") is managed by uv/npm: change pyproject.toml or package.json and re-lock" >&2 ;;
    */db/migrations/001_initial.sql)
        echo "001_initial.sql only runs when the DB volume is created: add a new numbered migration, and apply it by hand to existing databases (docs/pages/operations.md)" >&2 ;;
    *)
        exit 0 ;;
esac
exit 2
