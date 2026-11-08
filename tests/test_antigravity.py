"""Google Antigravity from the snap store (roles/optional/antigravity).

The IDE used to come through distrodeck from Google's apt repository, which
stopped at 1.23.2. The role installs two store snaps instead and removes the
apt package, its source list and its key. Each check here is one way the move
could go wrong:

* a snap task without classic confinement or on an unnamed channel,
* an apt task that adds Google's repository back,
* a wrapper that points `antigravity` at the hub instead of the IDE (the hub
  snap's own command has that name),
* a snap name typed in two places that drift apart,
* the server checklist no longer asserting the snaps are absent.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "roles" / "optional" / "antigravity" / "tasks" / "main.yml"
TASK_FILES = sorted((REPO / "roles").glob("**/tasks/*.yml"))
VARS = yaml.safe_load((REPO / "vars" / "main.yml").read_text(encoding="utf-8"))
TASKS = yaml.safe_load(ROLE.read_text(encoding="utf-8"))

APT_REPO_FILES = {
    "/etc/apt/sources.list.d/antigravity.list",
    "/etc/apt/sources.list.d/antigravity.list.save",
    "/etc/apt/keyrings/antigravity-repo-key.gpg",
}


def _task(name: str) -> dict:
    found = [t for t in TASKS if t.get("name") == name]
    assert found, f"no task named {name!r} in {ROLE}"
    return found[0]


def test_snap_names_and_channel_are_configuration_not_pins() -> None:
    assert VARS["nikos_antigravity_ide_snap"] == "antigravity-ide-snap"
    assert VARS["nikos_antigravity_hub_snap"] == "antigravity"
    assert VARS["nikos_antigravity_snap_channel"] == "latest/stable"
    # The snap commands live under /snap/bin as <snap>.<app>, or <snap> when
    # the app carries the snap's name.
    assert VARS["nikos_antigravity_ide_command"].startswith(VARS["nikos_antigravity_ide_snap"] + ".")
    assert VARS["nikos_antigravity_hub_command"] == VARS["nikos_antigravity_hub_snap"]
    # No *_version: tests/test_pinned_sources.py would read it as a pin, and
    # the snaps are unpinned by design (vars/versions.yml header).
    assert not [k for k in VARS if k.startswith("nikos_antigravity") and k.endswith("_version")]


def test_both_snaps_are_installed_classic_on_the_named_channel() -> None:
    for name, var in (("Install the Antigravity IDE snap", "ide"), ("Install the Antigravity hub snap", "hub")):
        task = _task(name)
        snap = task["community.general.snap"]
        assert snap["name"] == "{{ nikos_antigravity_%s_snap }}" % var
        assert snap["classic"] is True
        assert snap["channel"] == "{{ nikos_antigravity_snap_channel }}"
        assert snap["state"] == "present"
        # snapd is not on the CI runner's --check path; the task has to sit it out.
        assert "not ansible_check_mode" in str(task["when"])


def test_snapd_is_installed_first() -> None:
    names = [t.get("name") for t in TASKS]
    assert names.index("Install snapd") < names.index("Install the Antigravity IDE snap")
    assert _task("Install snapd")["ansible.builtin.apt"] == {"name": "snapd", "state": "present"}


def test_the_apt_package_and_repository_are_removed_not_added() -> None:
    apt = _task("Remove Google's apt package for Antigravity (its repository stopped at 1.23.2)")
    assert apt["ansible.builtin.apt"] == {"name": "antigravity", "state": "absent", "purge": True}
    # The "moved" message keys on dpkg's answer, read before the removal and
    # also in check mode, not on the apt task's changed state.
    status = _task("Check for Google's apt package for Antigravity")
    assert status["check_mode"] is False and status["failed_when"] is False
    said = _task("Say that Antigravity moved from the apt package to the snaps")
    assert "antigravity_apt_status.stdout" in said["when"]
    files = _task("Remove Google's apt repository for Antigravity")
    assert files["ansible.builtin.file"] == {"path": "{{ item }}", "state": "absent"}
    assert set(files["loop"]) == APT_REPO_FILES
    # Nothing anywhere in the roles adds the repository back.
    for path in TASK_FILES:
        text = path.read_text(encoding="utf-8")
        assert "apt.pkg.dev" not in text, path
        assert "antigravity-debian" not in text, path
        for task in yaml.safe_load(text) or []:
            if not isinstance(task, dict):
                continue
            repo = task.get("ansible.builtin.apt_repository") or task.get("apt_repository")
            assert not repo or "antigravity" not in str(repo), (path, task.get("name"))


def _render(text: str) -> str:
    for key, value in VARS.items():
        if key.startswith("nikos_antigravity"):
            text = text.replace("{{ " + key + " }}", value)
    assert "{{" not in text, text
    return text


def test_the_antigravity_command_opens_the_ide_and_antigravity_hub_the_hub(tmp_path: Path) -> None:
    """The hub snap's command is /snap/bin/antigravity, the IDE's old name.

    /usr/local/bin comes before /snap/bin on PATH, so the wrapper decides what
    `antigravity` means. Rendered and run against a fake /snap/bin.
    """
    snap_bin = tmp_path / "snap-bin"
    snap_bin.mkdir()
    for name, tag in ((VARS["nikos_antigravity_ide_command"], "IDE"), (VARS["nikos_antigravity_hub_command"], "HUB")):
        fake = snap_bin / name
        fake.write_text(f'#!/bin/sh\necho "{tag}:$*"\n', encoding="utf-8")
        fake.chmod(0o755)
    wrappers = {
        "antigravity": "Install the antigravity command (the IDE, as with the apt package)",
        "antigravity-hub": "Install the antigravity-hub command",
    }
    for command, task_name in wrappers.items():
        task = _task(task_name)
        copy = task["ansible.builtin.copy"]
        assert copy["dest"] == f"/usr/local/bin/{command}"
        assert copy["mode"] == "0755"
        script = _render(copy["content"]).replace("/snap/bin/", f"{snap_bin}/")
        wrapper = tmp_path / command
        wrapper.write_text(script, encoding="utf-8")
        wrapper.chmod(0o755)
        out = subprocess.run(["sh", str(wrapper), "--flag", "a file"], capture_output=True, text=True, timeout=10)
        assert out.returncode == 0, out.stderr
        expected = "IDE" if command == "antigravity" else "HUB"
        assert out.stdout.strip() == f"{expected}:--flag a file", out.stdout


def test_site_runs_the_role_only_when_named_and_only_on_a_desktop() -> None:
    play = yaml.safe_load((REPO / "site.yml").read_text(encoding="utf-8"))[0]
    role = next(r for r in play["roles"] if r["role"] == "antigravity")
    assert role["tags"] == ["never", "antigravity"]
    assert role["when"] == "nikos_profile == 'desktop'"
    # Root for apt, snap and /usr/local/bin: the play's become, not become: false.
    assert "become" not in role


def test_the_server_checklist_asserts_both_snaps_are_absent() -> None:
    text = (REPO / "test").read_text(encoding="utf-8")
    server = re.search(r"^server_checks=\((.*?)^\)", text, re.M | re.S).group(1)
    for snap in (VARS["nikos_antigravity_ide_snap"], VARS["nikos_antigravity_hub_snap"]):
        assert f'"! snap list {snap} 2>/dev/null"' in server, snap
    desktop = re.search(r"^desktop_checks=\((.*?)^\)", text, re.M | re.S).group(1)
    # Opt-in: a desktop without it is correct.
    assert "antigravity" not in desktop


def test_doctor_reads_the_ide_command_from_the_playbook_vars() -> None:
    nikos = (REPO / "scripts" / "nikos").read_text(encoding="utf-8")
    line = next(l for l in nikos.splitlines() if "Antigravity IDE installed" in l)
    assert line.lstrip().startswith("optional_check"), line
    assert f'_nikos_var nikos_antigravity_ide_command {VARS["nikos_antigravity_ide_command"]}' in nikos
    # Off amd64 there is no IDE snap; doctor checks the hub there instead.
    assert f'_nikos_var nikos_antigravity_hub_command {VARS["nikos_antigravity_hub_command"]}' in nikos
    assert '"$(uname -m)" == "x86_64"' in nikos


def test_check_mode_runs_the_role_without_installing() -> None:
    """--check on a desktop: apt and file tasks are checked, the snap task sits out."""
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    result = subprocess.run(
        [
            "ansible-playbook", "site.yml", "-i", "inventory/local", "--check",
            "-e", "ansible_become=false", "--tags", "antigravity",
        ],
        cwd=REPO, capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    for name in ("Install the Antigravity IDE snap", "Install the Antigravity hub snap"):
        assert name in out
        snap_block = out[out.index(name):]
        assert snap_block.splitlines()[1].startswith("skipping:"), snap_block[:300]
    assert "Install the antigravity command" in out
    assert "failed=0" in out


def test_the_apt_package_is_removed_only_after_the_snaps_install() -> None:
    """A failed snap install must not leave the machine with no Antigravity.

    Tasks run in order and a failure stops the play, so the apt removal has to
    come after both snap installs.
    """
    names = [t.get("name") for t in TASKS]
    removal = names.index("Remove Google's apt package for Antigravity (its repository stopped at 1.23.2)")
    assert names.index("Install the Antigravity IDE snap") < removal
    assert names.index("Install the Antigravity hub snap") < removal
    assert names.index("Remove Google's apt repository for Antigravity") > names.index("Install the Antigravity hub snap")


def test_snapd_seeding_is_awaited_before_the_snap_installs() -> None:
    names = [t.get("name") for t in TASKS]
    wait = _task("Wait for snapd to finish seeding")
    assert wait["ansible.builtin.command"]["argv"] == ["snap", "wait", "system", "seed.loaded"]
    assert names.index("Install snapd") < names.index("Wait for snapd to finish seeding")
    assert names.index("Wait for snapd to finish seeding") < names.index("Install the Antigravity IDE snap")


def test_the_ide_snap_is_amd64_only_and_the_hub_installs_everywhere() -> None:
    ide = _task("Install the Antigravity IDE snap")
    assert "ansible_architecture == 'x86_64'" in str(ide["when"])
    hub = _task("Install the Antigravity hub snap")
    assert "ansible_architecture" not in str(hub.get("when", ""))
    # No IDE wrapper pointing at a snap that is not there.
    wrapper = _task("Install the antigravity command (the IDE, as with the apt package)")
    assert "ansible_architecture == 'x86_64'" in str(wrapper["when"])


def _run_guard(tmp_path: Path, existing: str | None) -> int:
    guard = _task("Check the wrapper paths for files NikOS did not write")
    argv = guard["ansible.builtin.command"]["argv"]
    target = tmp_path / "antigravity"
    if existing is not None:
        target.write_text(existing, encoding="utf-8")
    argv = [a.replace("{{ item }}", str(target)) for a in argv]
    return subprocess.run(argv, capture_output=True, text=True, timeout=10).returncode


def test_a_user_file_in_usr_local_bin_is_not_overwritten(tmp_path: Path) -> None:
    assert _run_guard(tmp_path, None) == 0
    assert _run_guard(tmp_path, "#!/bin/sh\n# NikOS: `antigravity` opens the IDE\n") == 0
    assert _run_guard(tmp_path, "#!/bin/sh\nexec my-own-thing\n") == 1
    for name in ("Install the antigravity command (the IDE, as with the apt package)", "Install the antigravity-hub command"):
        assert "antigravity_wrapper_guard" in str(_task(name)["when"]), name
