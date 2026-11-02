import contextlib
import io
import unittest

from architecture.tests.support import messages
from architecture.verify import core
from architecture.verify.__main__ import main
from architecture.verify.core import Repo


class RunnerTest(unittest.TestCase):
    def test_real_repo_passes_the_fast_checks(self):
        # ./verify.sh runs them all; generated.* runs the real generators, which take seconds
        self.assertEqual(messages(Repo(), "containers") + messages(Repo(), "network"), [])

    def test_select_by_group_and_name(self):
        names = [c.name for c in core.select(["network", "containers.match"])]
        self.assertEqual(names, ["network.reachability", "network.addresses", "containers.match"])

    def test_unknown_name_is_rejected(self):
        with self.assertRaises(KeyError):
            core.select(["netwrk"])

    def test_every_check_has_a_summary(self):
        for c in core.CHECKS.values():
            self.assertTrue(c.summary, c.name)

    def test_fix_runs_only_fixable_checks(self):
        fixable = [c.name for c in core.select([]) if c.fix]
        self.assertEqual(fixable, ["generated.up-to-date"])
        self.assertEqual(core.fix(Repo(), core.select(["network"])), [])

    def test_duplicate_name_is_rejected(self):
        with self.assertRaises(ValueError):
            core.check("network.reachability")(lambda repo: [])

    def test_cli_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--list"]), 0)
            self.assertEqual(main(["network", "containers"]), 0)
            self.assertEqual(main(["--fix", "network"]), 0)  # no fixes there, so it only checks
