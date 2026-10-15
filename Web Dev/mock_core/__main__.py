"""Run the mock Core API on its own:  python -m mock_core [--host 127.0.0.1] [--port 8001]"""
import argparse

from secheck_web.config import load_settings
from secheck_web.web import make_server
from mock_core.server import MockCore


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Mock Core API for SEC-Check")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=settings.mock_core_port)
    parser.add_argument("--webapp-url", help="forward external Core API calls to this Web App (gateway mode)")
    parser.add_argument("--gateway-user", default=settings.mock_core_gateway_user)
    args = parser.parse_args()
    core = MockCore(teams=settings.teams, contract=settings.core_contract, log_requests=True,
                    webapp_url=args.webapp_url, gateway_user=args.gateway_user)
    server = make_server(core, args.host, args.port, name="mock-core")
    print(f"Mock Core API on http://{args.host}:{args.port}  (contract: {settings.core_contract.name})")
    print(f"  external calls: " + (f"forwarded to the Web App at {args.webapp_url}" if args.webapp_url else "handled locally"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
