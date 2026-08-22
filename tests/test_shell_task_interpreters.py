"""Guards on the shell every `shell` task actually runs under.

`ansible.builtin.shell` runs its script with `/bin/sh`, which is dash on Debian
and Ubuntu. dash is not bash: `set -o pipefail`, `[[ ]]`, process substitution
and associative arrays are all bash extensions, and a script using one dies on
the line that uses it. The BitNet install task hit exactly this:

    /bin/sh: 1: set: Illegal option -o pipefail

It failed on its first line, before the copy it existed to perform, and it took
the whole optional playbook down with rc=2. A task that needs bash has to say
so with `args: executable: /bin/bash`.

This checks the class rather than that one task, because nothing about the
failure is specific to BitNet: any `shell` task written in bash and left on the
default interpreter fails the same way, and only when it runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Vendored trees carry their own tests.
SKIP_DIRS = (".git", "scripts/script-helpers")

SHELL_KEYS = ("ansible.builtin.shell", "shell")

# Syntax dash does not have. Each is enough on its own to require bash.
BASHISMS = (
    "pipefail",
    "[[",
    "<(",
    ">(",
    "&>",
    "declare -A",
    "${!",
    "function ",
)


def _tasks(node):
    """Yield every mapping in a playbook, at any nesting depth.

    Tasks live under `tasks`, `pre_tasks`, `handlers`, `block`, `rescue` and
    `always`, and blocks nest, so this walks rather than reads fixed keys.
    """
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _tasks(value)


def _shell_tasks() -> list[tuple[Path, dict, str]]:
    found = []
    for path in sorted(REPO_ROOT.rglob("*.yml")):
        relative = path.relative_to(REPO_ROOT)
        if any(str(relative).startswith(skip) for skip in SKIP_DIRS):
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:  # linted elsewhere
            continue
        for task in _tasks(document):
            for key in SHELL_KEYS:
                script = task.get(key)
                if isinstance(script, str):
                    found.append((relative, task, script))
    return found


SHELL_TASKS = _shell_tasks()


def test_the_playbooks_still_have_shell_tasks_to_check() -> None:
    """A walk that quietly matches nothing would pass every test below."""
    assert SHELL_TASKS, "no shell tasks found; the task walk is not finding them"


@pytest.mark.parametrize(
    "relative,task,script",
    SHELL_TASKS,
    ids=[f"{relative}:{task.get('name', '?')}" for relative, task, _ in SHELL_TASKS],
)
def test_bash_only_scripts_declare_bash(relative: Path, task: dict, script: str) -> None:
    used = sorted({bashism for bashism in BASHISMS if bashism in script})
    if not used:
        return
    executable = (task.get("args") or {}).get("executable", "")
    assert executable.endswith("bash"), (
        f"{relative}: {task.get('name')!r} uses bash-only syntax "
        f"({', '.join(used)}) but runs under the default /bin/sh, which is "
        "dash on Debian and Ubuntu. Add `args: {executable: /bin/bash}`."
    )
