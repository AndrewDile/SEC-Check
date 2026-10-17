FROM python:3.12-slim
WORKDIR /app
COPY secheck_tester/ secheck_tester/
ENV TESTER_HOST=0.0.0.0 TESTER_PORT=8100 PYTHONUNBUFFERED=1
EXPOSE 8100
USER nobody
CMD ["python", "-m", "secheck_tester"]
