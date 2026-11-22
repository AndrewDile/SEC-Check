"""A fake Slack and Teams, for the end-to-end tests (docker-compose.e2e.yml).

It answers on the real services' host names, which Docker's DNS points here, so the notifier's
HTTPS and host checks run as they do in production. Its certificate is made at startup and trusted
only by the notifier in that stack. The tests read what was posted over plain HTTP, on API_PORT.
"""

import json
import os
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API_PORT = 8004
SLACK_HOST = "hooks.slack.com"
TEAMS_HOST = "e2e.environment.api.powerplatform.com"
# What each service answers when it accepts a post
ANSWERS = {SLACK_HOST: (200, b"ok"), TEAMS_HOST: (202, b"")}

received: list[dict] = []


class Webhook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        host = self.headers.get("Host", "").partition(":")[0]
        try:
            payload = json.loads(body)
            status, answer = ANSWERS[host]
        except (ValueError, KeyError):
            status, answer = 400, b"invalid_payload"
        else:
            received.append({"host": host, "path": self.path, "body": payload})
        reply(self, status, answer, "text/plain")

    def log_message(self, *args):
        pass


class Api(BaseHTTPRequestHandler):
    def do_GET(self):
        reply(self, 200, json.dumps(received).encode(), "application/json")

    def do_DELETE(self):
        received.clear()
        reply(self, 200, b"", "text/plain")

    def log_message(self, *args):
        pass


def reply(handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_certificate(cert: Path, key: Path) -> None:
    """A self-signed certificate for both hosts. The key stays in this container."""
    names = f"subjectAltName=DNS:{SLACK_HOST},DNS:{TEAMS_HOST}"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2"]
        + ["-subj", "/CN=sec-check e2e", "-addext", names]
        + ["-addext", "keyUsage=critical,digitalSignature,keyCertSign"]
        + ["-keyout", str(key), "-out", str(cert)],
        check=True,
        capture_output=True,
    )


if __name__ == "__main__":
    cert, key = Path(os.environ["CERT_FILE"]), Path("/tmp/key.pem")
    make_certificate(cert, key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    webhooks = ThreadingHTTPServer(("0.0.0.0", 443), Webhook)
    webhooks.socket = context.wrap_socket(webhooks.socket, server_side=True)
    threading.Thread(target=webhooks.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", API_PORT), Api).serve_forever()
