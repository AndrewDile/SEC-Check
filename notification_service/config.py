"""Notification service settings, read from environment variables."""

import os

CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:8000")
CORE_API_TOKEN = os.environ["CORE_API_TOKEN"]

# The bearer token the Core API must send when it calls this service.
INBOUND_TOKEN = os.environ["INBOUND_TOKEN"]

# How many times to try each recipient before giving up.
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))

# Timeout for each webhook post and SMTP connection, in seconds.
HTTP_TIMEOUT_S = float(os.environ.get("HTTP_TIMEOUT_S", "10"))

# Email (SMTP). With SMTP_HOST empty, every email notice fails, saying email isn't set up.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_SECURITY = os.environ.get("SMTP_SECURITY") or "starttls"  # starttls, ssl (port 465) or none
SMTP_USER = os.environ.get("SMTP_USER", "")  # no login when empty
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM") or SMTP_USER  # the sender address
if SMTP_SECURITY not in ("starttls", "ssl", "none"):
    raise ValueError(f"SMTP_SECURITY must be starttls, ssl or none, not {SMTP_SECURITY!r}")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8001"))
