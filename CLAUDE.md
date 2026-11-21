# CLAUDE.md

Project guidance for all coding agents is in [AGENTS.md](AGENTS.md):

@AGENTS.md

## Claude Code setup

- `/regen-contracts` (`.claude/skills/`): the checklist for changing a service contract.
- Hooks (`.claude/settings.json`, scripts in `.claude/hooks/`):
  - block edits to generated, secret and lock files
  - format each edited file
  - run `./lint.sh` before finishing when code changed
- Claude Code asks before running `./test.sh`, `./deploy.sh`, `git push` and `docker compose down`.
