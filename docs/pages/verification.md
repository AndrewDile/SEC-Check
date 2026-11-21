# Architecture verification

`architecture/model.yaml` describes what the system is made of and how it fits together. It's the
source of truth: the repo's config has to agree with it, and `./verify.sh` checks that it does.
CI runs it in its own `verify` job, so CI fails on any drift.

```bash
./verify.sh              # every check
./verify.sh --list       # names and summaries; "(fixable)" marks checks with a fix
./verify.sh network      # one group (network.*), or name single checks
./verify.sh --fix        # fix what the checks can, then run them
```

Each problem prints as `<check>: <message>`, and the script exits nonzero if there are any.
Like a formatter's `--check`, plain `./verify.sh` never changes the repo. `--fix` runs the fixes
of the checks you pick, prints what they changed, and then runs the checks.

## Layout

| Path | What |
|---|---|
| `architecture/model.yaml` | The model |
| `architecture/model.py` | Parses and validates the model into types (`Model`, `Service`, `Connection`, `Generated`) |
| `architecture/verify/core.py` | `Repo` (the files checks read), the `@check` registry and the runner |
| `architecture/verify/checks/` | The checks, one module per group |
| `architecture/tests/` | Tests for the model and every check |

The checks run on the standard library plus PyYAML, which `verify.sh` gets through `uv run --with`.
Nothing is added to the project's dependencies.

## The model

| Section | Each entry |
|---|---|
| `services` | A container: the `port` it listens on inside the compose network, and the `published` host ports, written as in compose |
| `connections` | `from` and `to` (services) and `why`: one container may call another |
| `generated` | A `file` a tool writes, what it's generated `from`, and the `command` that writes it. The command takes the output path as its first argument and defaults to the file |

`model.py` rejects anything it doesn't know: an unknown section, a connection to an unknown
service, a missing field. If the model is invalid, no checks run.

## Checks

| Check | Fails when |
|---|---|
| `containers.match` | a container is in the compose file but not the model, or the other way round |
| `containers.published-ports` | a container publishes host ports other than the model's |
| `generated.up-to-date` (fixable) | a generated file is missing, or differs from what its command writes now: the source changed or the file was edited by hand. The check writes into a temporary folder next to the file and compares; the fix runs the command on the file itself |
| `network.reachability` | two containers share a network that the model doesn't connect, or the model connects two that share none |
| `network.addresses` | a container URL in a compose `environment` value, or a Caddyfile `reverse_proxy` target, isn't a modelled connection in that direction, or uses the wrong port |

## Adding a check

1. Add a function to a module in `architecture/verify/checks/`, or start a new module for a new
   group. Modules there are loaded automatically.
2. Register it with `@check("<group>.<what>")`. It takes a `Repo` and yields one message per
   problem. The first line of its docstring is what `--list` shows. If the problem can be fixed
   mechanically, pass `fix=`: a function that takes a `Repo`, changes the repo, and yields one
   message per change. The check itself must never change the repo.
3. Read files through `Repo`: `repo.model`, `repo.compose`, `repo.caddyfile`, or `repo.text()` /
   `repo.yaml()` for anything else. If several checks need the same file, add a cached property.
4. Add tests in `architecture/tests/`. Load the real repo with `Repo()`, break one thing on it,
   and assert that the check reports it (`support.messages`). A check that runs tools or changes
   files should get a throwaway repo in a temp folder instead (`Repo(root)`), as
   `test_generated.py` does with a fake generator. Keep the tests fast: `./verify.sh` is what
   runs the slow checks against the real repo.
5. Add the check to the table above.

```python
@check("containers.listen-all")
def listen_all(repo):
    """Python services listen on every interface inside their container."""
    ...
```

## Adding to the model

To describe something new (a contract, an env var, a dependency rule):

1. Add a section to `model.yaml`.
2. In `model.py`, add a type for its entries, parse and validate them in `Model.parse`, and add
   the section name to `SECTIONS`.
3. Add checks that compare it with the repo, and a model test for its validation.
