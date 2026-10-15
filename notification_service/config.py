"""Notification service settings, read from environment variables."""

import os

CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:8000")
CORE_API_TOKEN = os.environ["CORE_API_TOKEN"]

# The bearer token the Core API must send when it calls this service.
INBOUND_TOKEN = os.environ["INBOUND_TOKEN"]

# How many times to try each recipient before giving up.
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8001"))
