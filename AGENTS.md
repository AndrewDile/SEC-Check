# AGENTS.md

Guidance for coding agents working in SEC-Check: incident tracking for SEC cybersecurity
disclosure (Form 8-K Item 1.05). The developer docs in `docs/pages/` are the reference for every
service, interface and known limitation; read the relevant page before changing a service.

## Layout

| Folder | What | Stack |
|---|---|---|
| `api/` | Core API: the hub that owns all data | Express 5, TypeScript, MySQL (`mysql2`) |
| `web_app/` | Browser front end and its backend | Python, **standard library only** |
| `ingestion_worker/` | Polls CISA KEV and SEC EDGAR for incidents | Python 3.12+, FastAPI, Pydantic v2 |
| `notification_service/` | Notifies teams of new incidents | Python 3.12+, FastAPI, Pydantic v2 |
| `tester/` | Cross-team tester (54 ordered tests, T-01..T-54) | Python, **standard library only** |
| `db/migrations/` | MySQL schema | SQL |
| `docs/` | Developer docs, served at `/docs/` | MkDocs |

Services never call each other: each talks only to the Core API, which calls back the services
that need to hear about changes (`docs/pages/architecture.md`). Caddy (`Caddyfile`) is the only
public port.

## Commands

All of these run from the repo root. They need [uv](https://docs.astral.sh/uv/) and Node 24,
with `cd api && npm install` done once.

```bash
./lint.sh              # ruff + tsc + Biome; ./lint.sh --fix fixes what it can
./format.sh            # format everything; ./format.sh --check is what CI runs
./docs.sh build        # strict MkDocs build, as the docs container does it
docker compose up --build
```

`./test.sh` runs every suite against a local stack, as CI does. It **wipes the local database**,
so ask before running it.

CI (`.github/workflows/ci.yml`) runs lint and format, then tests, on every push and PR. **Every
push to `main` deploys to production (EC2)**, so work on a branch and open a PR.

## Rules

- **Don't edit generated files.** `ingestion_worker/models.py` and `notification_service/models.py`
  are generated from that service's `core_api.openapi.yaml` by its `generate_models.sh`. Change
  the spec, then regenerate.
- **Keep the shared schemas identical.** Schemas defined in both `core_api.openapi.yaml` files
  (`SourceName`, `Incident`, `Priority`, ...) describe one Core API payload. The rest of each
  file is meant to differ: it lists only what that service needs.
- **The specs aren't enforced on the Core API.** A contract change also means updating
  `api/src/services.ts` (`/ingest/*`, `/notif/*`) and its required-field checks.
- **Schema changes are manual.** Migrations in `db/migrations/` run only when the `db-data` volume
  is created. Add a new numbered file instead of editing `001_initial.sql`, and apply it by hand
  to existing databases, including the server's, before deploying code that needs it
  (`docs/pages/operations.md`).
- **The Core API's `/system` endpoints are a shared interface.** Other teams' testers call them
  per the course's API spec; don't change their paths or payloads.
- **Keep `web_app/` and `tester/` dependency-free** (standard library only). The tester must not
  import any system code, and `tester/secheck_tester/target.py` is the only place that knows the
  target's URLs.
- **Never commit or read `.env`.** It holds real secrets. `.env.example` is the template, and CI
  copies it for its throwaway stack.

## Style

- **Python:** ruff, line length 100, rules `E4 E7 E9 F I` (`pyproject.toml`).
- **TypeScript:** Biome, 2-space indent, single quotes, line width 120 (`api/biome.json`).
- Match the surrounding code: short comments that explain why, and plain names.
- Commit messages are short, lowercase and in the past tense ("added caddy reverse proxy").

## Docs

Change the docs in the same PR as the code:

- **Service behavior or config:** `docs/pages/services/<service>.md`
- **Payload shapes:** `docs/pages/data-model.md`
- **Tests:** `docs/pages/testing.md`. The suite counts there and in `README.md` are written by hand.
- **Known limitations:** `docs/pages/limitations.md`. Remove an entry when you fix it, and add
  one when you knowingly leave a gap.

The Swagger pages load each service's OpenAPI files through `docs/hooks.py`. A new spec file must
be added to its `SPECS` map.
