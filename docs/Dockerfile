# Build from the repository root: docker build -f docs/Dockerfile .
FROM python:3.13-slim AS build
WORKDIR /src
COPY docs/requirements.txt docs/
RUN pip install --no-cache-dir -r docs/requirements.txt
# The OpenAPI files the Swagger pages show (see hooks.py)
COPY web_app/contracts/webapp_api.yaml web_app/contracts/
COPY tester/openapi tester/openapi
COPY ingestion_worker/*.yaml ingestion_worker/
COPY notification_service/*.yaml notification_service/
COPY docs docs
# --strict fails the build on broken links, so CI catches them
RUN mkdocs build --strict -f docs/mkdocs.yml -d /site

FROM caddy:2.10
COPY --from=build /site /srv
CMD ["caddy", "file-server", "--root", "/srv", "--listen", ":80"]
