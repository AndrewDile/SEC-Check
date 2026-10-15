"""Run the ingestion worker: python -m ingestion_worker [--once] [--source NAME]"""

import argparse
import logging
import os
import sys

from ingestion_worker.sources import ALL_SOURCES
from ingestion_worker.worker import poll, run_forever

parser = argparse.ArgumentParser(prog="python -m ingestion_worker")
parser.add_argument("--once", action="store_true", help="poll each source once, then exit")
parser.add_argument(
    "--source", choices=[source.name for source in ALL_SOURCES], help="poll only this source"
)
args = parser.parse_args()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every request at INFO
sources = [source for source in ALL_SOURCES if args.source in (None, source.name)]

if args.once:
    results = [poll(source) for source in sources]
    sys.exit(0 if all(results) else 1)

try:
    run_forever(sources)
except KeyboardInterrupt:
    pass
