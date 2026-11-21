import tempfile
import unittest
from pathlib import Path

from architecture.tests.support import messages
from architecture.verify.core import CHECKS, Repo

# A fake generator, so these tests don't run the real one: it upper-cases spec.txt
GENERATOR = """\
set -e
cd "$(dirname "$0")"
[ -f fail ] && { echo "bad spec" >&2; exit 3; }
tr a-z A-Z < spec.txt > "${1:-out.txt}"
"""

MODEL = """\
generated:
  - { file: svc/out.txt, from: [svc/spec.txt], command: svc/gen.sh }
"""


class GeneratedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.svc = self.root / "svc"
        self.svc.mkdir()
        (self.root / "architecture").mkdir()
        (self.root / "architecture/model.yaml").write_text(MODEL)
        (self.svc / "gen.sh").write_text(GENERATOR)
        (self.svc / "spec.txt").write_text("hello\n")
        (self.svc / "out.txt").write_text("HELLO\n")

    def check(self):
        return messages(Repo(self.root), "generated")

    def fix(self):
        return list(CHECKS["generated.up-to-date"].fix(Repo(self.root)))

    def test_current_file_passes(self):
        self.assertEqual(self.check(), [])

    def test_changed_source_is_caught(self):
        (self.svc / "spec.txt").write_text("hello again\n")
        [message] = self.check()
        self.assertIn("svc/out.txt isn't what svc/gen.sh generates from svc/spec.txt", message)

    def test_hand_edit_is_caught(self):
        (self.svc / "out.txt").write_text("HELLO, BY HAND\n")
        self.assertEqual(len(self.check()), 1)

    def test_missing_file_is_caught(self):
        (self.svc / "out.txt").unlink()
        self.assertEqual(self.check(), ["svc/out.txt is missing; ./verify.sh --fix generates it"])

    def test_generator_failure_is_reported(self):
        (self.svc / "fail").touch()
        self.assertEqual(self.check(), ["svc/gen.sh failed (exit 3): bad spec"])

    def test_check_leaves_no_files_behind(self):
        (self.svc / "spec.txt").write_text("changed\n")
        self.check()
        self.assertEqual(
            sorted(p.name for p in self.svc.iterdir()), ["gen.sh", "out.txt", "spec.txt"]
        )
        self.assertEqual((self.svc / "out.txt").read_text(), "HELLO\n")

    def test_fix_regenerates_then_check_passes(self):
        (self.svc / "spec.txt").write_text("hello again\n")
        self.assertEqual(self.fix(), ["regenerated svc/out.txt"])
        self.assertEqual((self.svc / "out.txt").read_text(), "HELLO AGAIN\n")
        self.assertEqual(self.check(), [])

    def test_fix_creates_missing_file(self):
        (self.svc / "out.txt").unlink()
        self.assertEqual(self.fix(), ["regenerated svc/out.txt"])

    def test_fix_reports_nothing_when_current(self):
        self.assertEqual(self.fix(), [])

    def test_fix_reports_generator_failure(self):
        (self.svc / "fail").touch()
        self.assertEqual(self.fix(), ["svc/gen.sh failed (exit 3): bad spec"])


class RealModelTest(unittest.TestCase):
    def test_every_generated_entry_exists(self):
        # The real generators are slow, so only ./verify.sh runs them
        root = Repo().root
        for entry in Repo().model.generated:
            for path in (entry.file, entry.command, *entry.sources):
                self.assertTrue((root / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
