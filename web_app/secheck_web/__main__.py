"""Run the Web App server:  python -m secheck_web  [--host H] [--port P] [--core-url URL]

This is the container entry point. It serves the Web App only; the Core API is
a separate service (CORE_API_URL). For local development with a mock Core API,
use run.py in the "Web Dev" test harness instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 or newer is required.")

from .app import WebApp
from .config import load_settings
from .web import make_server


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m secheck_web", description="SEC-Check Web App server"
    )
    parser.add_argument(
        "--settings", type=Path, help="settings file (default config/settings.json)"
    )
    parser.add_argument(
        "--host", help="interface to bind (default 127.0.0.1; the container uses 0.0.0.0)"
    )
    parser.add_argument("--port", type=int, help="port (default 8000)")
    parser.add_argument(
        "--core-url", help="Core API base URL (default from settings / CORE_API_URL)"
    )
    parser.add_argument("--quiet", action="store_true", help="do not log each request")
    args = parser.parse_args()

    settings = load_settings(
        args.settings, host=args.host, port=args.port, core_api_url=args.core_url
    )
    if args.quiet:
        settings.log_requests = False
    app = WebApp(settings)
    server = make_server(app, settings.host, settings.port, name="webapp")

    shown = "localhost" if settings.host in ("127.0.0.1", "0.0.0.0") else settings.host
    print("SEC-Check Web App", flush=True)
    print(
        f"  Listening on: {settings.host}:{settings.port}   (http://{shown}:{settings.port}/app/)",
        flush=True,
    )
    print(f"  Core API:     {settings.core_api_url}", flush=True)
    if settings.auth_mode == "dev":
        print(
            "  Sign-in:      development placeholder (no passwords); do not expose publicly",
            flush=True,
        )
    if app.missing_handlers:
        print(
            f"  WARNING: spec operations without handlers (answer 501): {', '.join(app.missing_handlers)}",
            flush=True,
        )
    if app.unused_handlers:
        print(
            f"  WARNING: handlers whose operationId is no longer in the spec: {', '.join(app.unused_handlers)}",
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
