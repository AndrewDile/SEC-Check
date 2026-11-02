"""The notifier's tests. config.py requires these tokens as soon as it is imported."""

import os

os.environ.setdefault("CORE_API_TOKEN", "test-core-token")
os.environ.setdefault("INBOUND_TOKEN", "test-inbound-token")
