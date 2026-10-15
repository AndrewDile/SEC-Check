"""Refresh the OpenAPI contract files from the project spec documents.

The Web App reads web_app/contracts/webapp_api.json at startup (routing and
request validation). The mock Core API and the tests read
"Web Dev/contracts/core_api.json". When a spec document changes, run:

    python tools/sync_contracts.py

It needs PyYAML (pip install pyyaml) because the specs are written in YAML.
The app itself does not need PyYAML: it only reads the generated .json files.

Sources (in the project's spec_docs/ folder, next to "Web Dev"):
    spec_docs/Web App API.txt   -> web_app/contracts/webapp_api.yaml + webapp_api.json
    spec_docs/API Spec.txt      -> Web Dev/contracts/core_api.yaml   + core_api.json

The spec documents are never modified. API Spec.txt currently contains tab
characters and mis-indented lines that are not valid YAML; the known problems
are repaired in the extracted copy (see CORE_REPAIRS). If the extracted YAML
still does not parse, the existing contract file is kept and a warning is shown.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required for this tool: pip install pyyaml")

WEB_DEV = Path(__file__).resolve().parent.parent
PROJECT = WEB_DEV.parent
SPEC_DOCS = PROJECT / "spec_docs"
WEBAPP_CONTRACTS = PROJECT / "web_app" / "contracts"   # shipped in the Web App container
CORE_CONTRACTS = WEB_DEV / "contracts"                 # used by the mock Core API and the tests

# (bad text, fixed text) pairs applied to the YAML extracted from API Spec.txt.
CORE_REPAIRS = [
    # "Dependency" property indented with tabs under /incidents
    ("\t    Dependency:\n\t      type: string", "                Dependency:\n                  type: string"),
    # "/notifier" path written at column 0 instead of under "paths:"
    ("\n/notifier:\n", "\n  /notifier:\n"),
]

# Fields the Data Schema defines but the OpenAPI block in API Spec.txt is missing.
# They are added to the generated core contract so the mock Core API accepts them.
CORE_ADDITIONS = {
    ("/incidents", "Dependency_Name"): {"type": "string", "description": "Alias of Dependency (Data Schema name, gap G-3)."},
    ("/tickets", "Ticket_Claim"): {"type": "string", "enum": ["CLAIMED", "UNCLAIMED"], "description": "From Data Schema (gap G-3)."},
}


def extract_after(text: str, marker: str, end_marker: str | None = None) -> str:
    start = text.index(marker)
    start = text.index("openapi:", start)
    end = text.index(end_marker, start) if end_marker else len(text)
    return text[start:end].rstrip() + "\n"


def write_contract(out_dir: Path, name: str, yaml_text: str, header: str) -> None:
    doc = yaml.safe_load(yaml_text)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.yaml").write_text(header + yaml_text, encoding="utf-8")
    (out_dir / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    ops = sum(1 for item in doc["paths"].values() for m in item if m in {"get", "post", "put", "patch", "delete"})
    print(f"  {name}: {len(doc['paths'])} paths, {ops} operations")


def sync_webapp(src: Path, out_dir: Path) -> bool:
    text = src.read_text(encoding="utf-8")
    yaml_text = extract_after(text, "5. HTTP STRUCTURED SPEC", "\n" + "-" * 79 + "\n6.")
    try:
        write_contract(out_dir, "webapp_api", yaml_text, f"# Generated from '{src.name}' by tools/sync_contracts.py. Do not edit by hand.\n")
        return True
    except yaml.YAMLError as exc:
        print(f"  WARNING: {src.name} OpenAPI block is not valid YAML; kept existing contract.\n  {exc}")
        return False


def sync_core(src: Path, out_dir: Path) -> bool:
    text = src.read_text(encoding="utf-8")
    yaml_text = extract_after(text, "HTTP Structured Spec:")
    for bad, good in CORE_REPAIRS:
        yaml_text = yaml_text.replace(bad, good)
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        print(f"  WARNING: {src.name} OpenAPI block is not valid YAML even after known repairs; kept existing contract.\n  {exc}")
        return False
    added = []
    for (path, field), schema in CORE_ADDITIONS.items():
        props = doc["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
        if field not in props:
            props[field] = schema
            added.append(f"{path}.{field}")
    yaml_out = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120)
    header = (
        f"# Generated from '{src.name}' by tools/sync_contracts.py. Do not edit by hand.\n"
        f"# Repairs applied: tab/indentation fixes ({len(CORE_REPAIRS)} known issues).\n"
        f"# Fields added from Data Schema: {', '.join(added) or 'none'}\n"
    )
    write_contract(out_dir, "core_api", yaml_out, header)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--webapp-spec", type=Path, default=SPEC_DOCS / "Web App API.txt")
    parser.add_argument("--core-spec", type=Path, default=SPEC_DOCS / "API Spec.txt")
    parser.add_argument("--webapp-out", type=Path, default=WEBAPP_CONTRACTS, help="where webapp_api.* go")
    parser.add_argument("--core-out", type=Path, default=CORE_CONTRACTS, help="where core_api.* go")
    args = parser.parse_args()
    print("Syncing contracts:")
    ok = sync_webapp(args.webapp_spec, args.webapp_out) & sync_core(args.core_spec, args.core_out)
    print("Done." if ok else "Done with warnings.")
    print("Next: python -m unittest  (tests report any handler or field drift)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
