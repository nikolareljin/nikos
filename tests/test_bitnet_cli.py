"""Guards on how the BitNet CLI is installed.

llama-cli links against shared libraries produced by BitNet's build and is
built with a RUNPATH holding that build directory's absolute path. Installing
it by copying the binary alone, or by wrapping it in a way that points back at
the build tree, gives a command that works only while that tree stays where it
was built, under the home it was built with:

    $ ldd ~/.local/bin/bitnet-cli
    libllama.so.0 => <build tree>/build/bin/libllama.so.0

The binary and its libraries are copied into a prefix of their own instead, so
the build tree is only needed to rebuild.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLE = REPO_ROOT / "roles/optional/bitnet"
TASKS = ROLE / "tasks/main.yml"
DEFAULTS = ROLE / "defaults/main.yml"

ENTRY_POINT = "/usr/local/bin/bitnet-cli"
BUILD_TREE = "Projects/bitnet.cpp"


@pytest.fixture(scope="module")
def tasks() -> list[dict]:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def defaults() -> dict:
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entry_point(tasks: list[dict]) -> dict:
    for task in tasks:
        copy = task.get("ansible.builtin.copy") or {}
        if copy.get("dest") == ENTRY_POINT:
            return copy
    pytest.fail(f"no task installs {ENTRY_POINT}")


def test_the_prefix_is_outside_the_build_tree(defaults: dict) -> None:
    prefix = defaults["bitnet_prefix"]
    assert BUILD_TREE not in prefix, (
        f"the install prefix {prefix} is inside the build tree, which is the "
        "dependency this was meant to remove"
    )
    assert prefix.startswith("/usr/"), "the prefix should be a system location"


def test_the_libraries_are_installed_next_to_the_binary(tasks: list[dict]) -> None:
    """ggml dlopens its backends, so every .so has to travel, not just ldd's list."""
    installs = [str(t.get("ansible.builtin.shell", "")) for t in tasks]
    copy_step = next((c for c in installs if "cp -a" in c), None)
    assert copy_step, "nothing copies the build output into the prefix"
    assert "*.so*" in copy_step, (
        "only some libraries are copied; ggml loads its backend libraries with "
        "dlopen, so a dependency-only copy passes ldd and fails at run time"
    )
    assert "llama-cli" in copy_step


def test_the_entry_point_does_not_reach_back_into_the_build_tree(entry_point: dict) -> None:
    content = entry_point["content"]
    assert BUILD_TREE not in content, (
        "the entry point references the build tree; deleting or cleaning it "
        "would break the command"
    )
    assert "LD_LIBRARY_PATH" in content
    assert "exec" in content and "llama-cli" in content


def test_the_entry_point_reports_a_missing_install_clearly(entry_point: dict) -> None:
    content = entry_point["content"]
    assert "-x" in content and "exit 127" in content


def test_the_entry_point_is_installed_for_every_user(entry_point: dict) -> None:
    assert entry_point.get("mode") == "0755"
    assert entry_point.get("force", True) is not False, (
        "force: false would keep whatever an earlier version installed"
    )


def test_the_superseded_per_user_copy_is_removed(tasks: list[dict]) -> None:
    """~/.local/bin precedes /usr/local/bin on a default PATH.

    A copy left there by an earlier version would shadow the entry point and
    keep resolving libraries out of the build tree.
    """
    removals = [
        t.get("ansible.builtin.file") or {} for t in tasks
    ]
    assert any(
        r.get("state") == "absent" and str(r.get("path", "")).endswith(".local/bin/bitnet-cli")
        for r in removals
    ), "the old ~/.local/bin/bitnet-cli is never removed, so it keeps shadowing"


def test_the_build_still_produces_the_cli(tasks: list[dict]) -> None:
    configure = [
        t for t in tasks
        if "cmake -S . -B build" in str(t.get("ansible.builtin.command", ""))
    ]
    assert configure, "no BitNet configure task found"
    command = str(configure[0]["ansible.builtin.command"])
    for flag in ("-DLLAMA_BUILD_COMMON=ON", "-DLLAMA_BUILD_TOOLS=ON"):
        assert flag in command, (
            f"{flag} missing; llama.cpp guards add_subdirectory(tools) on it, "
            "and it defaults off when llama.cpp is a subdirectory"
        )
