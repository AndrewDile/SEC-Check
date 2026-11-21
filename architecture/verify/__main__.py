"""Check the repo against the system model. Run it with ./verify.sh (see its --help)."""

import argparse
import sys

from architecture.model import ModelError
from architecture.verify.core import Repo, fix, load_checks, run, select


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="./verify.sh", description="Check the repo against architecture/model.yaml."
    )
    parser.add_argument(
        "checks",
        nargs="*",
        metavar="CHECK",
        help="check or group names, e.g. network (default: all)",
    )
    parser.add_argument("--list", action="store_true", help="list the checks and exit")
    parser.add_argument("--fix", action="store_true", help="fix what the checks can, then run them")
    args = parser.parse_args(argv)

    load_checks()
    try:
        chosen = select(args.checks)
    except KeyError as e:
        parser.error(f"no check or group named {e.args[0]} (see --list)")

    if args.list:
        for c in chosen:
            print(f"{c.name:30} {c.summary}{'  (fixable)' if c.fix else ''}")
        return 0

    try:
        if args.fix:
            for change in fix(Repo(), chosen):
                print(f"fixed {change}")
        findings = run(Repo(), chosen)
    except ModelError as e:
        print(f"architecture/model.yaml is invalid:\n{e}", file=sys.stderr)
        return 1
    for finding in findings:
        print(finding, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
