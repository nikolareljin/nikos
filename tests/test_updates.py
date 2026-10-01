"""What `nikos update` moves forward on its own: distrodeck and Ollama.

Neither is pinned by default. Each test covers one way that could go wrong:

* "latest" resolving to a pre-release, a v-prefixed tag, or 0.9 over 0.10,
* an explicit pin being overridden by the remote,
* an offline run failing, or deleting a working clone,
* Ollama re-downloaded when it is current, or not updated when it is not.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
RESOLVER = REPO / "scripts" / "distrodeck-version.sh"


def _fake_git(tmp_path: Path, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    git = bin_dir / "git"
    git.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    git.chmod(0o755)
    return bin_dir


def _resolve(bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RESOLVER), *args],
        capture_output=True, text=True, timeout=30,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )


TAGS = "\n".join(
    f"{i:040x}\trefs/tags/{t}"
    for i, t in enumerate(
        ["0.9.0", "0.10.3", "0.11.0-rc1", "v9.9.9", "0.10.12", "latest", "1.0"]
    )
)


def test_latest_is_the_highest_plain_release_tag(tmp_path: Path) -> None:
    bin_dir = _fake_git(tmp_path, f"cat <<'EOF'\n{TAGS}\nEOF\n")
    result = _resolve(bin_dir, "latest")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "0.10.12\n"


def test_an_explicit_version_is_a_pin_and_never_asks_the_remote(tmp_path: Path) -> None:
    log = tmp_path / "git.log"
    bin_dir = _fake_git(tmp_path, f'echo "$@" >> {log}\nexit 1\n')
    result = _resolve(bin_dir, "0.10.3")
    assert (result.returncode, result.stdout) == (0, "0.10.3\n")
    assert not log.exists()


@pytest.mark.parametrize("body", ["exit 128\n", "exit 0\n"], ids=["offline", "no-tags"])
def test_an_unresolvable_latest_fails_with_nothing_on_stdout(tmp_path: Path, body: str) -> None:
    result = _resolve(_fake_git(tmp_path, body), "latest")
    assert (result.returncode, result.stdout) == (1, "")


def _run_distrodeck_clone_tasks(tmp_path: Path, *, clone_exists: bool) -> subprocess.CompletedProcess:
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    role = (REPO / "roles" / "dev-tools" / "tasks" / "main.yml").read_text(encoding="utf-8")
    start = role.index("- name: Resolve the distrodeck release")
    end = role.index("- name: Install distrodeck PATH wrapper")
    (tmp_path / "scripts").mkdir()
    shutil.copy(RESOLVER, tmp_path / "scripts" / RESOLVER.name)
    (tmp_path / "tasks.yml").write_text("---\n" + role[start:end], encoding="utf-8")
    (tmp_path / "play.yml").write_text(
        "---\n- hosts: localhost\n  connection: local\n  gather_facts: false\n"
        "  tasks:\n    - ansible.builtin.include_tasks: tasks.yml\n",
        encoding="utf-8",
    )
    if clone_exists:
        (tmp_path / "Projects" / "distrodeck" / ".git").mkdir(parents=True)
    bin_dir = _fake_git(tmp_path, "exit 128\n")
    return subprocess.run(
        [
            "ansible-playbook", "play.yml", "-i", "localhost,",
            "-e", f"nikos_home={tmp_path}", "-e", "distrodeck_version=latest",
            "-e", "nikos_update_mode=true", "-e", "distrodeck_repo_url=https://example.invalid/dd.git",
        ],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        env={"PATH": f"{bin_dir}:{Path(shutil.which('ansible-playbook')).parent}:/usr/bin:/bin",
             "HOME": str(tmp_path)},
    )


def test_offline_update_keeps_an_existing_clone_and_warns(tmp_path: Path) -> None:
    result = _run_distrodeck_clone_tasks(tmp_path, clone_exists=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "keeping" in result.stdout and "the existing clone" in result.stdout
    assert (tmp_path / "Projects" / "distrodeck" / ".git").is_dir()
    assert re.search(r"TASK \[Clone distrodeck\][^\n]*\n[^\n]*skipping", result.stdout), result.stdout


def test_offline_first_install_stops_with_a_reason(tmp_path: Path) -> None:
    result = _run_distrodeck_clone_tasks(tmp_path, clone_exists=False)
    assert result.returncode != 0
    assert "Could not read distrodeck's release tags" in result.stdout


def _git(*args: str, cwd: Path) -> str:
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def _origin_with_releases(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "main", cwd=origin)
    for tag in ("0.1.0", "0.2.0"):
        (origin / "VERSION").write_text(tag + "\n", encoding="utf-8")
        _git("add", "VERSION", cwd=origin)
        _git("commit", "-qm", tag, cwd=origin)
        _git("tag", tag, cwd=origin)
    (origin / "VERSION").write_text("0.3.0-dev\n", encoding="utf-8")
    _git("commit", "-qam", "unreleased", cwd=origin)
    return origin


def _run_real_clone_tasks(tmp_path: Path, origin: Path, update_mode: bool) -> subprocess.CompletedProcess:
    role = (REPO / "roles" / "dev-tools" / "tasks" / "main.yml").read_text(encoding="utf-8")
    start = role.index("- name: Resolve the distrodeck release")
    end = role.index("- name: Install distrodeck PATH wrapper")
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(RESOLVER, tmp_path / "scripts" / RESOLVER.name)
    (tmp_path / "tasks.yml").write_text("---\n" + role[start:end], encoding="utf-8")
    (tmp_path / "play.yml").write_text(
        "---\n- hosts: localhost\n  connection: local\n  gather_facts: false\n"
        "  tasks:\n    - ansible.builtin.include_tasks: tasks.yml\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            "ansible-playbook", "play.yml", "-i", "localhost,",
            "-e", f"nikos_home={tmp_path}", "-e", "distrodeck_version=latest",
            "-e", f"distrodeck_repo_url={origin}", "-e", f"nikos_update_mode={update_mode}",
        ],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("update_mode,dirty,expected", [
    (True, False, "0.2.0"), (False, False, "0.1.0"), (True, True, "0.1.0"),
], ids=["update-moves-forward", "setup-leaves-it", "local-edits-kept"])
def test_an_existing_clone_moves_to_the_newest_release(
    tmp_path: Path, update_mode: bool, dirty: bool, expected: str
) -> None:
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    origin = _origin_with_releases(tmp_path)
    clone = tmp_path / "Projects" / "distrodeck"
    clone.parent.mkdir()
    _git("clone", "-q", "--branch", "0.1.0", str(origin), str(clone), cwd=tmp_path)
    if dirty:
        (clone / "VERSION").write_text("edited\n", encoding="utf-8")
    result = _run_real_clone_tasks(tmp_path, origin, update_mode)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git("describe", "--tags", "--exact-match", cwd=clone) == expected
    if dirty:
        assert "has local edits" in result.stdout
        assert (clone / "VERSION").read_text(encoding="utf-8") == "edited\n"


def test_a_first_clone_takes_the_newest_release_not_main(tmp_path: Path) -> None:
    origin = _origin_with_releases(tmp_path)
    result = _run_real_clone_tasks(tmp_path, origin, False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git("describe", "--tags", "--exact-match", cwd=tmp_path / "Projects" / "distrodeck") == "0.2.0"


# -- Ollama ------------------------------------------------------------------


def _ai_stack() -> list[dict]:
    return yaml.safe_load((REPO / "roles" / "ai-stack" / "tasks" / "main.yml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "installed,latest,update_mode,expected",
    [
        ("ollama version is 0.12.0", {"tag_name": "v0.13.1"}, True, True),
        ("ollama version is 0.13.1", {"tag_name": "v0.13.1"}, True, False),
        ("ollama version is 0.13.1\nWarning: client version is 0.13.1", {"tag_name": "v0.13.2"}, True, True),
        ("Warning: could not connect to a running Ollama instance\n"
         "Warning: client version is 0.13.1", {"tag_name": "v0.13.1"}, True, False),
        ("Warning: could not connect to a running Ollama instance\n"
         "Warning: client version is 0.12.0", {"tag_name": "v0.13.1"}, True, True),
        ("ollama version is 0.12.0\nWarning: client version is 0.13.1", {"tag_name": "v0.13.1"}, True, False),
        ("", {"tag_name": "v0.13.1"}, True, False),
        ("ollama version is 0.13.1", {"tag_name": "v0.14.0-rc1"}, True, False),
        ("ollama version is 0.12.0", {"message": "API rate limit exceeded"}, True, False),
        ("ollama version is 0.12.0", {}, True, False),
        ("ollama version is 0.12.0", {"tag_name": "v0.13.1"}, False, False),
    ],
    ids=["newer-release", "current", "client-warning", "server-down-current", "server-down-older",
         "old-server-new-client", "unreadable-version", "pre-release-tag", "rate-limited",
         "lookup-failed", "setup-run"],
)
def test_update_reruns_the_installer_only_for_a_newer_release(
    tmp_path: Path, installed: str, latest: dict, update_mode: bool, expected: bool
) -> None:
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    task = next(t for t in _ai_stack() if t.get("name") == "Update Ollama to the latest release")
    task = dict(task)
    task["ansible.builtin.shell"] = "true"  # never the real installer in a test
    task.pop("become", None)
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "tasks": [task, {"ansible.builtin.debug": {"msg": "RAN={{ ai_stack_ollama_update is changed }}"}}],
    }]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play), encoding="utf-8")
    extra = {
        "nikos_ollama_mode": "local",
        "nikos_update_mode": update_mode,
        "ai_stack_ollama_install": {"changed": False},
        "ai_stack_ollama_installed": {"stdout": installed},
        "ai_stack_ollama_latest": {"json": latest} if latest else {"status": -1},
    }
    result = subprocess.run(
        ["ansible-playbook", "play.yml", "-i", "localhost,", "-e", json.dumps(extra)],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"RAN={expected}" in result.stdout, result.stdout


def test_nikos_update_takes_the_ollama_update_path() -> None:
    # `nikos update` runs the play with nikos_update_mode=true; the update task
    # is gated on it and sits before the restart that reads its result.
    cli = (REPO / "scripts" / "nikos").read_text(encoding="utf-8")
    update = re.search(r"^cmd_update\(\) \{.*?^\}", cli, re.M | re.S).group(0)
    assert "_playbook -e nikos_update_mode=true" in update
    names = [t.get("name") for t in _ai_stack()]
    upd = names.index("Update Ollama to the latest release")
    start = names.index("Enable and start the Ollama system service")
    assert names.index("Install Ollama") < upd < names.index("Write the Ollama listen address drop-in") < start
    tasks = _ai_stack()
    assert "nikos_update_mode | bool" in tasks[upd]["when"]
    assert "ai_stack_ollama_update is changed" in tasks[start]["ansible.builtin.systemd"]["state"]


def test_a_failed_download_fails_the_installer_task(tmp_path: Path) -> None:
    # `curl | sh` without pipefail: curl fails, sh reads nothing and exits 0,
    # so the task reported a successful update and restarted the old engine.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text("#!/bin/sh\nexit 22\n", encoding="utf-8")
    (bin_dir / "curl").chmod(0o755)
    for name in ("Install Ollama", "Update Ollama to the latest release"):
        task = next(t for t in _ai_stack() if t.get("name") == name)
        cmd = task["ansible.builtin.shell"]
        assert task["args"]["executable"] == "/bin/bash"
        result = subprocess.run(["/bin/bash", "-c", cmd], env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
                                capture_output=True, text=True, timeout=30)
        assert result.returncode != 0, name
