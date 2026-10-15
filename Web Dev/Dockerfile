# Optional container build. No packages to install: the app uses the Python standard library only.
#   docker build -t secheck-web .
#   docker run -p 8000:8000 secheck-web                                  (with mock Core API)
#   docker run -p 8000:8000 -e CORE_API_URL=http://core:8001 secheck-web --no-mock
FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV SECHECK_HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8000
ENTRYPOINT ["python", "run.py"]
