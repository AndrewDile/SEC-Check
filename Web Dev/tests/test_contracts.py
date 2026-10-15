"""Spec-drift checks. These are the tests to run after a spec changes.

- Every operation in the Web App contract has a handler, and every handler is
  still in the contract.
- The Core paths the client uses exist in the Core contract.
- The contract files are up to date with the spec documents in the project's
  spec_docs/ folder (needs PyYAML; skipped otherwise).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import WEB_DEV, make_settings
from devpath import WEB_APP
from secheck_web import core_client
from secheck_web.app import WebApp
from secheck_web.validation import Spec

SPEC_DOCS = WEB_DEV.parent / "spec_docs"


class ContractCoverageTests(unittest.TestCase):
    def test_every_spec_operation_has_a_handler(self):
        app = WebApp(make_settings())
        self.assertEqual(app.missing_handlers, [], "Spec operations with no handler (add one in secheck_web/handlers)")
        self.assertEqual(app.unused_handlers, [], "Handlers whose operationId is no longer in the spec")

    def test_core_paths_exist_in_core_contract(self):
        spec = Spec.load(make_settings().core_contract)
        for name in dir(core_client):
            if name.startswith("PATH_"):
                self.assertIn(getattr(core_client, name), spec.doc["paths"], f"{name} not in Core contract")

    def test_webapp_contract_uses_core_enums(self):
        """Web App enums must stay equal to the Core enums they mirror."""
        web = Spec.load(make_settings().webapp_contract).doc["components"]["schemas"]
        core = Spec.load(make_settings().core_contract).doc
        props = core["paths"]["/incidents"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
        for field, schema_name in (("Materiality", "Materiality_type"), ("Severity", "Severity_type"), ("Urgency", "Urgency_type")):
            self.assertEqual(web[schema_name]["enum"], props[field]["enum"], f"{schema_name} differs between contracts")


class ContractFreshnessTests(unittest.TestCase):
    def test_contracts_match_spec_documents(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        webapp_txt, core_txt = SPEC_DOCS / "Web App API.txt", SPEC_DOCS / "API Spec.txt"
        if not webapp_txt.exists() or not core_txt.exists():
            self.skipTest(f"spec documents not found in {SPEC_DOCS}")
        with tempfile.TemporaryDirectory() as tmp:
            # Run the sync tool into a temporary folder so the real contracts are untouched.
            subprocess.run([sys.executable, str(WEB_DEV / "tools" / "sync_contracts.py"),
                            "--webapp-out", tmp, "--core-out", tmp], check=True, capture_output=True)
            current_files = {"webapp_api.json": WEB_APP / "contracts" / "webapp_api.json",
                             "core_api.json": WEB_DEV / "contracts" / "core_api.json"}
            for name, current_path in current_files.items():
                fresh = json.loads((Path(tmp) / name).read_text(encoding="utf-8"))
                current = json.loads(current_path.read_text(encoding="utf-8"))
                self.assertEqual(fresh, current, f"{current_path} is out of date: run python tools/sync_contracts.py")


if __name__ == "__main__":
    unittest.main()
