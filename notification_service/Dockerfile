# Build from the repository root: docker build -f notification_service/Dockerfile .
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /bin/uv

WORKDIR /app
# Dependencies first, so that changing the code doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked
COPY notification_service ./notification_service

ENV PATH="/app/.venv/bin:$PATH"
# Listen on every interface, so other containers can reach the service.
ENV HOST=0.0.0.0 PORT=8001
EXPOSE 8001
USER nobody
CMD ["python", "-m", "notification_service"]
