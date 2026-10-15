"""Make the Web App code importable from the test harness.

The Web App lives in ../web_app (its own Docker container). The harness in
"Web Dev" (mock Core API, tests, tools, run.py) imports it from there, so there
is only one copy of the Web App code. Import this module before importing
secheck_web.
"""
import sys
from pathlib import Path

WEB_DEV = Path(__file__).resolve().parent
WEB_APP = WEB_DEV.parent / "web_app"

if not (WEB_APP / "secheck_web").is_dir():
    raise SystemExit(f"Cannot find the Web App code at {WEB_APP}. Expected the web_app folder next to 'Web Dev'.")

for _path in (WEB_DEV, WEB_APP):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
