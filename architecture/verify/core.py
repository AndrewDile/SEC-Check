"""The verification core: the repo files checks read, the check registry and the runner."""

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

from architecture.model import Model

ROOT = Path(__file__).resolve().parents[2]


class Repo:
    """The files checks read, each loaded once. Tests change these attributes to fake drift."""

    def __init__(self, root=ROOT):
        self.root = Path(root)

    def text(self, path):
        return (self.root / path).read_text()

    def yaml(self, path):
        return yaml.safe_load(self.text(path))

    @cached_property
    def model(self):
        return Model.parse(self.yaml("architecture/model.yaml"))

    @cached_property
    def compose(self):
        """docker-compose.yml's services, by name."""
        return self.yaml("docker-compose.yml")["services"]

    @cached_property
    def caddyfile(self):
        return self.text("Caddyfile")


@dataclass(frozen=True)
class Check:
    name: str
    run: Callable[[Repo], Iterable[str]]
    fix: Callable[[Repo], Iterable[str]] | None = None

    @property
    def summary(self):
        return (self.run.__doc__ or "").strip().splitlines()[0]


@dataclass(frozen=True)
class Finding:
    check: str
    message: str

    def __str__(self):
        return f"{self.check}: {self.message}"


CHECKS: dict[str, Check] = {}


def check(name, fix=None):
    """Register a check: a function that takes a Repo and yields one message per problem.

    Its docstring's first line is the summary `--list` shows. Name it `<group>.<what>`.
    fix, if given, takes a Repo, changes the repo so the check passes, and yields one message
    per thing it changed; `--fix` runs it before the checks.
    """

    def register(fn):
        if name in CHECKS:
            raise ValueError(f"check {name} is registered twice")
        CHECKS[name] = Check(name, fn, fix)
        return fn

    return register


def load_checks():
    """Import every module in verify/checks/, which registers its checks."""
    from architecture.verify import checks

    for module in pkgutil.iter_modules(checks.__path__):
        importlib.import_module(f"{checks.__name__}.{module.name}")
    return CHECKS


def select(patterns):
    """The checks named, or in a group named ("network" picks network.*). None picks all."""
    if not patterns:
        return list(CHECKS.values())
    chosen = {}
    for pattern in patterns:
        matches = [c for n, c in CHECKS.items() if n == pattern or n.startswith(f"{pattern}.")]
        if not matches:
            raise KeyError(pattern)
        chosen.update((c.name, c) for c in matches)
    return list(chosen.values())


def run(repo, checks):
    return [Finding(c.name, message) for c in checks for message in c.run(repo)]


def fix(repo, checks):
    """Run the fixes of the checks that have one; returns what they changed."""
    return [Finding(c.name, message) for c in checks if c.fix for message in c.fix(repo)]
