"""Local development: start the SEC-Check Web App (from ../web_app) and, by default, the mock Core API.

    python run.py                         Web App on http://127.0.0.1:8000, mock Core API on :8001
    python run.py --core-url http://host:port
                                          Use a real Core API instead of the mock
    python run.py --port 9000 --mock-port 9001

Settings come from "Web Dev/config/settings.json" and can be overridden by
environment variables (see dev_settings.py and web_app/secheck_web/config.py)
or the flags below. To run the Web App on its own (as in Docker), use
"python -m secheck_web" in the web_app folder.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 or newer is required.")

import devpath  # noqa: E402,F401  (puts ../web_app on sys.path)
from dev_settings import load_dev_settings  # noqa: E402
from secheck_web.app import WebApp  # noqa: E402
from secheck_web.web import make_server, serve_in_thread  # noqa: E402
from mock_core.server import MockCore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SEC-Check Web App")
    parser.add_argument("--settings", type=Path, help="settings file (default config/settings.json)")
    parser.add_argument("--host", help="interface to bind (default 127.0.0.1 = this computer only)")
    parser.add_argument("--port", type=int, help="Web App port (default 8000)")
    parser.add_argument("--core-url", help="Core API base URL; implies --no-mock")
    parser.add_argument("--no-mock", action="store_true", help="do not start the mock Core API")
    parser.add_argument("--mock-port", type=int, help="mock Core API port (default 8001)")
    parser.add_argument("--mock-local", action="store_true",
                        help="mock Core API handles test-client calls itself instead of forwarding them to the Web App")
    parser.add_argument("--open", action="store_true", help="open the app in the default browser")
    parser.add_argument("--quiet", action="store_true", help="do not log each request")
    args = parser.parse_args()

    settings = load_dev_settings(args.settings, host=args.host, port=args.port, mock_core_port=args.mock_port)
    if args.quiet:
        settings.log_requests = False
    start_mock = settings.start_mock_core and not args.no_mock and not args.core_url
    if args.core_url:
        settings.core_api_url = args.core_url.rstrip("/")
    elif start_mock:
        settings.core_api_url = f"http://127.0.0.1:{settings.mock_core_port}"

    if start_mock:
        forwarding = settings.mock_core_forwarding and not args.mock_local
        webapp_local = f"http://127.0.0.1:{settings.port}"
        mock = MockCore(teams=settings.teams, contract=settings.core_contract, log_requests=settings.log_requests,
                        webapp_url=webapp_local if forwarding else None, gateway_user=settings.mock_core_gateway_user)
        serve_in_thread(make_server(mock, "127.0.0.1", settings.mock_core_port, name="mock-core"))

    app = WebApp(settings)
    server = make_server(app, settings.host, settings.port, name="webapp")
    url = f"http://{'localhost' if settings.host in ('127.0.0.1', '0.0.0.0') else settings.host}:{settings.port}"

    print("SEC-Check Web App")
    print(f"  App:          {url}/app/")
    print(f"  API docs:     {url}/docs   (spec: {url}/openapi.json)")
    print(f"  Core API:     {settings.core_api_url}" + ("   [mock, in-memory]" if start_mock else ""))
    if start_mock:
        print("                Core API calls from test clients are " +
              ("forwarded to the Web App (gateway mode)" if mock.webapp_url else "handled by the mock directly (--mock-local)"))
    if app.missing_handlers:
        print(f"  WARNING: spec operations without handlers (answer 501): {', '.join(app.missing_handlers)}")
    if app.unused_handlers:
        print(f"  WARNING: handlers whose operationId is no longer in the spec: {', '.join(app.unused_handlers)}")
    print("Press Ctrl+C to stop.\n")
    if args.open:
        webbrowser.open(f"{url}/app/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
