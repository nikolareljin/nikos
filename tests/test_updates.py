"""What `nikos update` moves forward: distrodeck and Ollama.

Both are pinned in vars/versions.yml; the pin is a minimum for an existing
install. Each test covers one way that could go wrong:

* "latest" (opt-in) resolving to a pre-release, a v-prefixed tag, or 0.9 over 0.10,
* an explicit pin being overridden by the remote, or a moved tag accepted,
* an offline run failing, or deleting a working clone,
* a clone ahead of the pin moved backwards,
* Ollama re-downloaded when it is current, downgraded, or not updated when older.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
RESOLVER = REPO / "scripts" / "distrodeck-version.sh"
ROLES = str(REPO / "roles")


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
        (tmp_path / "tools" / "distrodeck" / ".git").mkdir(parents=True)
    bin_dir = _fake_git(tmp_path, "exit 128\n")
    return subprocess.run(
        [
            "ansible-playbook", "play.yml", "-i", "localhost,",
            "-e", f"nikos_home={tmp_path}", "-e", f"nikos_tools_dir={tmp_path}/tools", "-e", "distrodeck_version=latest",
            "-e", "nikos_update_mode=true", "-e", "distrodeck_repo_url=https://example.invalid/dd.git",
        ],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        env={"PATH": f"{bin_dir}:{Path(shutil.which('ansible-playbook')).parent}:/usr/bin:/bin",
             "HOME": str(tmp_path), "ANSIBLE_ROLES_PATH": ROLES},
    )


def test_offline_update_keeps_an_existing_clone_and_warns(tmp_path: Path) -> None:
    result = _run_distrodeck_clone_tasks(tmp_path, clone_exists=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "keeping" in result.stdout and "the existing clone" in result.stdout
    assert (tmp_path / "tools" / "distrodeck" / ".git").is_dir()
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


def _run_real_clone_tasks(
    tmp_path: Path, origin: Path, update_mode: bool, version: str = "latest", commit: str = ""
) -> subprocess.CompletedProcess:
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
            "-e", f"nikos_home={tmp_path}", "-e", f"nikos_tools_dir={tmp_path}/tools",
            "-e", f"distrodeck_version={version}", "-e", f"distrodeck_commit={commit}",
            "-e", f"distrodeck_repo_url={origin}", "-e", f"nikos_update_mode={update_mode}",
        ],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        env={**os.environ, "ANSIBLE_ROLES_PATH": ROLES},
    )


@pytest.mark.parametrize("update_mode,dirty,expected", [
    (True, False, "0.2.0"), (False, False, "0.1.0"), (True, True, "0.1.0"),
], ids=["update-moves-forward", "setup-leaves-it", "local-edits-kept"])
def test_an_existing_clone_moves_to_the_newest_release(
    tmp_path: Path, update_mode: bool, dirty: bool, expected: str
) -> None:
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    origin = _origin_with_releases(tmp_path)
    clone = tmp_path / "tools" / "distrodeck"
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
    assert _git("describe", "--tags", "--exact-match", cwd=tmp_path / "tools" / "distrodeck") == "0.2.0"


def test_a_pinned_release_checks_out_the_pinned_commit(tmp_path: Path) -> None:
    origin = _origin_with_releases(tmp_path)
    commit = _git("rev-parse", "0.1.0", cwd=origin)
    result = _run_real_clone_tasks(tmp_path, origin, False, version="0.1.0", commit=commit)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git("rev-parse", "HEAD", cwd=tmp_path / "tools" / "distrodeck") == commit


def test_a_tag_that_moved_off_its_pinned_commit_stops_the_run(tmp_path: Path) -> None:
    origin = _origin_with_releases(tmp_path)
    wrong = _git("rev-parse", "0.2.0", cwd=origin)
    result = _run_real_clone_tasks(tmp_path, origin, False, version="0.1.0", commit=wrong)
    assert result.returncode != 0
    assert "is commit" in result.stdout and wrong in result.stdout
    assert not (tmp_path / "tools" / "distrodeck").exists()


def test_a_clone_ahead_of_the_pin_is_not_moved_back(tmp_path: Path) -> None:
    # The pin is a minimum: a checkout already past it (0.2.0 here, or a newer
    # release the user moved to) stays where it is on `nikos update`.
    origin = _origin_with_releases(tmp_path)
    clone = tmp_path / "tools" / "distrodeck"
    clone.parent.mkdir()
    _git("clone", "-q", "--branch", "0.2.0", str(origin), str(clone), cwd=tmp_path)
    commit = _git("rev-parse", "0.1.0", cwd=origin)
    result = _run_real_clone_tasks(tmp_path, origin, True, version="0.1.0", commit=commit)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git("describe", "--tags", "--exact-match", cwd=clone) == "0.2.0"
    assert re.search(r"TASK \[Clone distrodeck\][^\n]*\n[^\n]*skipping", result.stdout), result.stdout


def test_a_clone_behind_the_pin_moves_forward_to_it(tmp_path: Path) -> None:
    origin = _origin_with_releases(tmp_path)
    clone = tmp_path / "tools" / "distrodeck"
    clone.parent.mkdir()
    _git("clone", "-q", "--branch", "0.1.0", str(origin), str(clone), cwd=tmp_path)
    commit = _git("rev-parse", "0.2.0", cwd=origin)
    result = _run_real_clone_tasks(tmp_path, origin, True, version="0.2.0", commit=commit)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git("rev-parse", "HEAD", cwd=clone) == commit


# -- Ollama ------------------------------------------------------------------


def _ai_stack() -> list[dict]:
    return yaml.safe_load((REPO / "roles" / "ai-stack" / "tasks" / "main.yml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "installed,present,expected",
    [
        ("", False, True),
        ("ollama version is 0.12.0", True, True),
        ("ollama version is 0.34.4", True, False),
        ("ollama version is 0.35.1", True, False),
        ("ollama version is 0.34.4\nWarning: client version is 0.34.3", True, True),
        ("Warning: could not connect to a running Ollama instance\n"
         "Warning: client version is 0.34.4", True, False),
        ("Warning: could not connect to a running Ollama instance\n"
         "Warning: client version is 0.12.0", True, True),
        ("ollama version is 0.12.0\nWarning: client version is 0.34.4", True, False),
        ("", True, False),
    ],
    ids=["missing", "older", "equal", "newer-kept", "client-older", "server-down-current",
         "server-down-older", "old-server-new-client", "unreadable-kept"],
)
def test_ollama_is_installed_only_when_missing_or_older_than_the_pin(
    tmp_path: Path, installed: str, present: bool, expected: bool
) -> None:
    # The role's own gate task, against a fake /usr/local/bin/ollama.
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    gate = dict(next(t for t in _ai_stack() if t.get("name") == "Decide whether Ollama needs installing"))
    gate["vars"] = dict(gate["vars"], pin_gate_path=str(tmp_path / "ollama"))
    if present:
        (tmp_path / "ollama").write_text("", encoding="utf-8")
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "tasks": [gate, {"ansible.builtin.debug": {"msg": "RAN={{ pin_gate_install | bool }}"}}],
    }]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play), encoding="utf-8")
    extra = {
        "nikos_ollama_mode": "local",
        "ollama_version": "v0.34.4",
        "ai_stack_ollama_installed": {"stdout": installed, "rc": 0 if present else 2},
    }
    result = subprocess.run(
        ["ansible-playbook", "play.yml", "-i", "localhost,", "-e", json.dumps(extra)],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        env={**os.environ, "ANSIBLE_ROLES_PATH": ROLES},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"RAN={expected}" in result.stdout, result.stdout
    if installed.endswith("0.35.1"):
        assert "Ollama 0.35.1 is newer than the pin 0.34.4; leaving it." in result.stdout


def test_ollama_installs_from_the_checked_archive_before_the_restart() -> None:
    names = [t.get("name") for t in _ai_stack()]
    install = names.index("Install Ollama {{ ollama_version }}")
    start = names.index("Enable and start the Ollama system service")
    assert names.index("Refuse to start a second owner of the Ollama port") < install
    assert names.index("Decide whether Ollama needs installing") < install < start
    tasks = _ai_stack()
    block = {t["name"]: t for t in tasks[install]["block"]}
    download = block["Download the Ollama release archive"]["ansible.builtin.get_url"]
    assert download["checksum"] == "sha256:{{ ollama_sha256 }}"
    assert "/releases/download/{{ ollama_version }}/" in download["url"]
    assert "pin_gate_install | bool" in tasks[install]["when"]
    state = tasks[start]["ansible.builtin.systemd"]["state"]
    for changed in ("ai_stack_ollama_update", "ai_stack_ollama_unitfile", "ai_stack_ollama_dropin"):
        assert f"{changed} is changed" in state
