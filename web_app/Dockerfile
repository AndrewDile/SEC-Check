# SEC-Check Web App container. Python standard library only: nothing to install.
#
#   docker build -t secheck-web ./web_app
#   docker run -p 8000:8000 -e CORE_API_URL=http://<core-api-host>:3001 secheck-web
#
# With docker compose (repo root):  docker compose up --build   -> http://localhost:8000/app/
FROM python:3.12-slim

WORKDIR /app
COPY secheck_web ./secheck_web
COPY contracts ./contracts
COPY config ./config

# Listen on all interfaces inside the container; point CORE_API_URL at the Core API service.
ENV SECHECK_HOST=0.0.0.0 \
    SECHECK_PORT=8000 \
    CORE_API_URL=http://api:3001 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 webapp
USER webapp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('SECHECK_PORT', '8000')}/webapp/v1/health\", timeout=4)"]

CMD ["python", "-m", "secheck_web"]
