"""Where NikOS puts the repositories it clones, and that it pins what it installs."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TASK_FILES = sorted((ROOT / "roles").glob("**/tasks/*.yml")) + sorted((ROOT / "roles").glob("**/defaults/*.yml"))


def test_no_role_writes_into_the_users_projects_directory():
    # ~/Projects is the user's workspace and often does not exist. A developer's
    # own clone of ai-runner there made `nikos update` fail on local edits.
    hits = [f"{p.relative_to(ROOT)}:{n}" for p in TASK_FILES
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if "/Projects" in line and not line.lstrip().startswith("#")]
    assert hits == [], hits


def test_tools_dir_is_outside_the_nikos_checkout():
    value = yaml.safe_load((ROOT / "vars/main.yml").read_text())["nikos_tools_dir"]
    assert value == "{{ nikos_home }}/.local/share/nikos-tools"
    # ~/.local/share/nikos is the NikOS git checkout; clones under it would be
    # untracked files its update sync has to step around.
    assert not value.rstrip("/").endswith("/.local/share/nikos")


def test_nothing_is_installed_at_latest():
    hits = [f"{p.relative_to(ROOT)}:{n}" for p in TASK_FILES
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if re.search(r"@latest\b", line) and not line.lstrip().startswith("#")]
    assert hits == [], hits


def test_fabric_is_pinned_to_a_release_tag():
    version = yaml.safe_load((ROOT / "roles/optional/fabric/defaults/main.yml").read_text())["fabric_version"]
    assert re.fullmatch(r"v\d+\.\d+\.\d+", version), version
    tasks = (ROOT / "roles/optional/fabric/tasks/main.yml").read_text()
    assert "fabric/cmd/fabric@{{ fabric_version }}" in tasks
    assert "GOSUMDB: sum.golang.org" in tasks


def test_the_cli_never_runs_a_distrodeck_from_projects(tmp_path):
    # ~/Projects/distrodeck may be the user's own working copy.
    import subprocess
    nikos = (ROOT / "scripts/nikos").read_text()
    start = nikos.index("_distrodeck_bin() {")
    func = nikos[start:nikos.index("\n}\n", start) + 3]
    dd = tmp_path / "Projects" / "distrodeck" / "distrodeck"
    dd.parent.mkdir(parents=True)
    dd.write_text("#!/bin/sh\n")
    dd.chmod(0o755)
    out = subprocess.run(["bash", "-c", func + "\n_distrodeck_bin || echo NONE"],
                         capture_output=True, text=True,
                         env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}).stdout
    assert "Projects" not in out, out
    nt = tmp_path / ".local/share/nikos-tools/distrodeck/distrodeck"
    nt.parent.mkdir(parents=True)
    nt.write_text("#!/bin/sh\n")
    nt.chmod(0o755)
    out = subprocess.run(["bash", "-c", func + "\n_distrodeck_bin"],
                         capture_output=True, text=True,
                         env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}).stdout
    assert out.strip() == str(nt)
