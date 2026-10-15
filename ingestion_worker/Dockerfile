# Build from the repository root: docker build -f ingestion_worker/Dockerfile .
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /bin/uv

WORKDIR /app
# Dependencies first, so that changing the code doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked
COPY ingestion_worker ./ingestion_worker

ENV PATH="/app/.venv/bin:$PATH"
USER nobody
CMD ["python", "-m", "ingestion_worker"]
