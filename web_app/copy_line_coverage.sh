#!/bin/sh
# Copy line_coverage.py into the worker and notifier, which can't import from web_app/.
# Usage: copy_line_coverage.sh OUTPUT. ./verify.sh --fix runs it for each copy (architecture/model.yaml).
set -e
cp "$(dirname "$0")/secheck_web/line_coverage.py" "$1"
