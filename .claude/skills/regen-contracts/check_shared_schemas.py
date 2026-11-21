"""Check that schemas defined in both services' core_api.openapi.yaml are identical.

Each service's spec lists only what that service needs from the Core API, so most of each file
is its own. Schemas both define (SourceName, Incident, ...) describe the same Core API payload
and must match exactly. Exits 1 and prints the differing schemas if they don't.

    python3 .claude/skills/regen-contracts/check_shared_schemas.py
"""

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SPECS = [
    "ingestion_worker/core_api.openapi.yaml",
    "notification_service/core_api.openapi.yaml",
]


# Only schemas: responses and securitySchemes describe each service's own token, so they differ
def schemas(path):
    with open(REPO / path) as f:
        return yaml.safe_load(f).get("components", {}).get("schemas", {})


def main():
    a, b = (schemas(p) for p in SPECS)
    drift = [name for name in sorted(set(a) & set(b)) if a[name] != b[name]]

    for name in drift:
        print(f"components/schemas/{name} differs:")
        for path, spec in zip(SPECS, (a, b)):
            print(f"  {path}:")
            print("    " + json.dumps(spec[name], indent=2).replace("\n", "\n    "))
    if drift:
        return 1
    print(f"Shared schemas match: {', '.join(sorted(set(a) & set(b)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
