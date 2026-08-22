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

# Ansible reads both, so a guard that reads one is a guard with a way around it.
YAML_SUFFIXES = ("*.yml", "*.yaml")

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


def _shell_call(task: dict) -> tuple[str, str] | None:
    """Return a task's (script, interpreter), or None if it runs no shell.

    Both call forms have to be read. Free-form puts the script straight after
    the module name and its options under `args:`, while the mapping form puts
    the script in `cmd` and the options beside it, so `executable` can arrive
    by either route:

        - ansible.builtin.shell: set -o pipefail && ...
          args:
            executable: /bin/bash

        - ansible.builtin.shell:
            cmd: set -o pipefail && ...
            executable: /bin/bash
    """
    for key in SHELL_KEYS:
        module = task.get(key)
        if isinstance(module, str):
            script, options = module, {}
        elif isinstance(module, dict):
            script, options = module.get("cmd"), module
        else:
            continue
        if not isinstance(script, str):
            continue
        args = task.get("args") or {}
        executable = options.get("executable") or args.get("executable") or ""
        return script, str(executable)
    return None


def _shell_tasks() -> list[tuple[Path, str, str, str]]:
    found = []
    for suffix in YAML_SUFFIXES:
        for path in sorted(REPO_ROOT.rglob(suffix)):
            relative = path.relative_to(REPO_ROOT)
            if any(str(relative).startswith(skip) for skip in SKIP_DIRS):
                continue
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:  # linted elsewhere
                continue
            for task in _tasks(document):
                call = _shell_call(task)
                if call is None:
                    continue
                script, executable = call
                found.append((relative, str(task.get("name", "?")), script, executable))
    return sorted(found)


SHELL_TASKS = _shell_tasks()


def test_the_playbooks_still_have_shell_tasks_to_check() -> None:
    """A walk that quietly matches nothing would pass every test below."""
    assert SHELL_TASKS, "no shell tasks found; the task walk is not finding them"


@pytest.mark.parametrize(
    "relative,name,script,executable",
    SHELL_TASKS,
    ids=[f"{relative}:{name}" for relative, name, _, _ in SHELL_TASKS],
)
def test_bash_only_scripts_declare_bash(
    relative: Path, name: str, script: str, executable: str
) -> None:
    used = sorted({bashism for bashism in BASHISMS if bashism in script})
    if not used:
        return
    assert executable.endswith("bash"), (
        f"{relative}: {name!r} uses bash-only syntax ({', '.join(used)}) but "
        "runs under the default /bin/sh, which is dash on Debian and Ubuntu. "
        "Add `args: {executable: /bin/bash}`."
    )
