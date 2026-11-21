"""Helpers for check tests: each test loads the real repo, breaks one thing and runs a check."""

from architecture.verify.core import load_checks, run, select

load_checks()


def messages(repo, name):
    """What the check (or group) called name reports for repo."""
    return [finding.message for finding in run(repo, select([name]))]
