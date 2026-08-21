"""Guards on how the BitNet CLI is installed.

llama-cli links against the shared libraries in BitNet's build tree and is
built with a RUNPATH holding that tree's absolute path. Copying the binary
into ~/.local/bin therefore produced something that only resolved its
libraries while the build directory stayed exactly where it was built, under
the home it was built with:

    $ ldd ~/.local/bin/bitnet-cli
    libllama.so.0 => /projects/bitnet.cpp/build/bin/libllama.so.0

A wrapper that sets LD_LIBRARY_PATH resolves the path at run time instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS = REPO_ROOT / "roles/optional/bitnet/tasks/main.yml"

CLI_DEST = "{{ nikos_home }}/.local/bin/bitnet-cli"


@pytest.fixture(scope="module")
def tasks() -> list[dict]:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def install_task(tasks: list[dict]) -> dict:
    for task in tasks:
        copy = task.get("ansible.builtin.copy") or {}
        if copy.get("dest") == CLI_DEST:
            return task
    pytest.fail(f"no task installs {CLI_DEST}")


def test_the_cli_is_a_wrapper_not_a_copy_of_the_binary(install_task: dict) -> None:
    copy = install_task["ansible.builtin.copy"]
    assert "content" in copy, (
        "bitnet-cli is installed by copying a file. The built llama-cli carries "
        "an absolute RUNPATH into the build tree, so a copy breaks as soon as "
        "that tree moves or the home differs. Install a wrapper instead."
    )
    assert "src" not in copy, "the wrapper should be generated content, not a copied file"
    assert "remote_src" not in copy


def test_the_wrapper_points_the_loader_at_the_build_output(install_task: dict) -> None:
    content = install_task["ansible.builtin.copy"]["content"]
    assert "LD_LIBRARY_PATH" in content, (
        "without LD_LIBRARY_PATH the binary falls back to the RUNPATH baked in "
        "at build time, which is the defect this replaced"
    )
    assert "exec" in content and "llama-cli" in content


def test_the_wrapper_reports_a_missing_build_tree_clearly(install_task: dict) -> None:
    """Otherwise the user gets a loader error naming a path they never chose."""
    content = install_task["ansible.builtin.copy"]["content"]
    assert "-x" in content and "exit 127" in content


def test_the_wrapper_replaces_an_existing_bitnet_cli(install_task: dict) -> None:
    """Earlier versions installed the bare binary; it has to be overwritten."""
    copy = install_task["ansible.builtin.copy"]
    assert copy.get("force", True) is not False, (
        "force: false would keep the old bare binary on every machine that "
        "already has one, so the fix would never reach them"
    )
    assert copy.get("mode") == "0755"


def test_the_build_still_produces_the_cli(tasks: list[dict]) -> None:
    """The wrapper is only useful if the tools are actually built."""
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
