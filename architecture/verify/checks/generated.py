"""Generated files are exactly what their command writes from the current sources."""

import subprocess
import tempfile
from pathlib import Path

from architecture.verify.core import check


def generate(repo, entry, output):
    """Run entry's command, writing to output. Returns why it failed, or None."""
    result = subprocess.run(
        ["sh", str(repo.root / entry.command), str(output)], capture_output=True, text=True
    )
    if result.returncode:
        last = (result.stderr.strip() or result.stdout.strip() or "no output").splitlines()[-1]
        return f"{entry.command} failed (exit {result.returncode}): {last}"
    return None


def regenerate(repo):
    for entry in repo.model.generated:
        path = repo.root / entry.file
        before = path.read_text() if path.exists() else None
        if error := generate(repo, entry, path):
            yield error
        elif path.read_text() != before:
            yield f"regenerated {entry.file}"


@check("generated.up-to-date", fix=regenerate)
def up_to_date(repo):
    """Generated files match what their command writes from the current sources."""
    for entry in repo.model.generated:
        path = repo.root / entry.file
        if not path.exists():
            yield f"{entry.file} is missing; ./verify.sh --fix generates it"
            continue
        # Next to the real file, so tools that look for config (ruff) find the same config
        with tempfile.TemporaryDirectory(dir=path.parent, prefix=".verify-") as tmp:
            fresh = Path(tmp) / path.name
            if error := generate(repo, entry, fresh):
                yield error
            elif fresh.read_text() != path.read_text():
                yield (
                    f"{entry.file} isn't what {entry.command} generates from "
                    f"{', '.join(entry.sources)}; edit those, then ./verify.sh --fix"
                )
