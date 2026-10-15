"""In-memory stand-in for the Core API, validated against contracts/core_api.json."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # "Web Dev"
import devpath  # noqa: E402,F401  (the mock reuses small helpers from ../web_app)

from .server import MockCore  # noqa: E402,F401
