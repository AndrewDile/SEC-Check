"""python -m secheck_tester [--host H] [--port P] [--list] [--quiet]"""

from __future__ import annotations

import argparse
import logging
import sys
from http.server import ThreadingHTTPServer

from .config import Settings
from .server import TesterApp, make_handler
from .suite import SUITE


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m secheck_tester", description="SEC-Check cross-team tester (Core API)."
    )
    parser.add_argument("--host", help="listen address (TESTER_HOST, default 0.0.0.0)")
    parser.add_argument("--port", type=int, help="listen port (TESTER_PORT, default 8100)")
    parser.add_argument("--list", action="store_true", help="print the planned tests and exit")
    parser.add_argument("--quiet", action="store_true", help="log warnings only")
    args = parser.parse_args(argv)

    if args.list:
        for t in SUITE:
            after = " (after %s)" % ", ".join(t.after) if t.after else ""
            print("%s  %-64s %s%s" % (t.test_id, t.title, ", ".join(t.criteria), after))
        print("%d tests" % len(SUITE))
        return 0

    settings = Settings.from_env()
    if args.host:
        settings.host = args.host
    if args.port is not None:
        settings.port = args.port
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    httpd = ThreadingHTTPServer((settings.host, settings.port), make_handler(TesterApp(settings)))
    httpd.daemon_threads = True
    print(
        "SEC-Check tester listening on http://%s:%d%s/test/ (%d tests)"
        % (settings.host, httpd.server_address[1], settings.base_path, len(SUITE)),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
