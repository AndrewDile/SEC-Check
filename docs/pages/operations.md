# Deployment and operations

## Where it runs

There's one EC2 instance running Amazon Linux, with about 1 GB of RAM and 2 GB of swap. The
whole `docker-compose.yml` stack runs on it. Only port 80 (HTTP) needs to be open to the
internet, plus port 22 for deploys.

## Deployment

`deploy.sh` deploys the current checkout. CI runs it after tests pass on `main`, and you can
also run it from your machine with `DEPLOY_HOST` and `DEPLOY_KEY` set. It goes like this:

1. **Set up the host** over SSH. After the first run, this does nothing.
    - Installs Docker.
    - Installs pinned `docker-compose` and `docker-buildx` plugins.
    - Creates the swap file.
2. **Copy the files:** `rsync --delete` of the repo to `~/sec-check/`. It skips `.env`, `.git`,
   `node_modules`, `dist`, `.venv` and caches.
3. **Check `.env`:** stops if `~/sec-check/.env` is missing.
4. **Restart:** `docker compose down`, then `up -d --build`, then `docker image prune -f`.

GitHub Actions needs two repo secrets:

- `DEPLOY_HOST`, as `user@host`
- `DEPLOY_SSH_KEY`, the private key's contents

Deploys queue rather than run at the same time.

**The server's `.env`** is installed by hand and never copied. Besides the database credentials
and tokens, set:

- `WEB_APP_URL` to `http://<public host>`, for the claim links in notifications
- `SEC_USER_AGENT`
- both `LOGS_*` variables

Every deploy recreates every container. That causes:

- a short outage
- in-memory state in the worker, notifier and tester is reset
- container logs from before the deploy are lost

The database volume is kept.

**Schema changes** aren't applied automatically. The migrations run only when the `db-data`
volume is first created, so a change to the schema has to be applied to the server's database
by hand.

## Log viewer

`/logs/` runs [Dozzle](https://dozzle.dev): live, searchable logs for every container. It has
read-only access to the Docker socket and stores nothing itself.

Caddy protects it with `basic_auth`, using `LOGS_USER` and `LOGS_PASSWORD_HASH`:

```bash
docker run --rm -it caddy:2.10 caddy hash-password      # prompts for the password
```

Put the hash in `.env` **in single quotes**, because it contains `$`. **Set both variables or
neither:**

| `.env` | Result |
|---|---|
| Both set | Login works |
| Both empty | `/logs/` returns 401 for everyone; the rest of the site works |
| Only one set | Caddy refuses its config, and **the whole site goes down** |

After changing them, run `sudo docker compose up -d caddy`.

## What each service logs

| Service | Logs |
|---|---|
| Core API | Startup; unexpected errors (with stack); outbound calls that failed 5 times. No request log |
| Web app | One line per request (`log_requests`); startup summary |
| Ingestion worker | Events per poll, new incidents, failures (Python `logging`, timestamped) |
| Notification service | Every message sent through the `log` channel, retries, delivery summary |
| Tester | Session start and finish, crashes |
| Caddy | Startup and errors only. Access logging is off |

## Docs

This site is built by the `docs` container (`docs/Dockerfile`):

1. A build stage installs MkDocs Material and `mkdocs-swagger-ui-tag` from
   `docs/requirements.txt`.
2. `docs/hooks.py` copies each service's OpenAPI files in, so the specs aren't duplicated.
3. It runs `mkdocs build --strict`, which fails on broken links.
4. A Caddy stage serves the result.

Locally, `./docs.sh` serves the site with live reload.

Swagger UI is bundled with the site. The Mermaid diagrams load their script from a CDN, so they
need internet access to render.

To add a page, put a Markdown file under `docs/pages/` and list it under `nav` in
`docs/mkdocs.yml`. To show a spec, add it to `SPECS` in `docs/hooks.py` and its `COPY` line in
`docs/Dockerfile`, then embed it with `<swagger-ui src="..."/>`.
