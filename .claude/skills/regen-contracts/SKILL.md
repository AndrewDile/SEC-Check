---
name: regen-contracts
description: Change an API contract between the Core API and the ingestion worker or notification service, then regenerate models.py and keep the shared schemas, Core API code and docs in step. Use whenever editing a core_api.openapi.yaml or a service's openapi.yaml, adding an ingestion source (SourceName), or changing a payload the Core API exchanges with those services.
---

# Changing a service contract

The ingestion worker and notification service each have:

- `core_api.openapi.yaml`: the Core API endpoints that service calls, plus every payload it
  exchanges with the Core API. Its `models.py` is **generated** from this file.
- `openapi.yaml`: the service's own API, which the Core API calls. Its payloads `$ref` schemas
  in `core_api.openapi.yaml`.

Nothing enforces these specs on the Core API (`api/src/`, TypeScript). Keeping it in step is
part of the change.

## Steps

1. **Edit the spec(s), never `models.py`.** It has a "Don't edit it by hand" header and is
   overwritten.
   - An endpoint or schema only one service uses: edit that service's file.
   - A schema both files define (currently `Confidence`, `Incident`, `IncidentCreate`,
     `MatchedDependency`, `Priority`, `SourceName`): make the **same** edit in both files.
     Example: a new ingestion source name goes in `SourceName` in both.

2. **Regenerate the models** of every service whose `core_api.openapi.yaml` changed (needs
   [uv](https://docs.astral.sh/uv/)):
   ```bash
   ./verify.sh --fix generated
   ```
   This runs each service's `generate_models.sh`. `./verify.sh generated` (also run in
   CI) fails while a `models.py` is out of date. Review `git diff */models.py`:
   renamed or removed fields break the service's code.

3. **Check the shared schemas still match:**
   ```bash
   python3 .claude/skills/regen-contracts/check_shared_schemas.py
   ```
   It needs PyYAML. If `python3` lacks it, run
   `uv run --no-project --with pyyaml python .claude/skills/regen-contracts/check_shared_schemas.py`.
   Fix any drift it reports by editing the specs, then go back to step 2.

4. **Update the code on both sides:**
   - The service's Python code that uses the changed models.
   - The Core API routes in `api/src/services.ts` (`/ingest/*` and `/notif/*`), including the
     required-field checks, and the calls the Core API makes to the services' own APIs.
   - `api/src/db/` if a stored field changed. Schema changes need a **new** file in
     `db/migrations/`. Migrations only run when the database volume is created, so the new
     file must also be applied by hand to existing databases, including the server's (see
     `docs/pages/operations.md`).

5. **Update the docs.** `docs/pages/data-model.md` lists the main payload shapes by hand, and
   `docs/pages/services/*.md` describe each service's endpoints. The Swagger pages pick up the
   specs on their own (see `docs/hooks.py`). Check that the site builds: `./docs.sh build`.

6. **Lint, format, verify and test:**
   ```bash
   ./lint.sh && ./format.sh --check && ./verify.sh
   ```
   `./test.sh` runs the API tests and the cross-team suite, but it **wipes the local
   database**. Ask before running it.

## Done when

- Every changed `core_api.openapi.yaml` has a regenerated `models.py`.
- `check_shared_schemas.py` passes.
- The Core API, the services and the docs agree with the specs.
- Lint and format pass.
