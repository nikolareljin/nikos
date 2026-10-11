"""nikos update skips builds that are already current (BitNet, image-view,
git-lantern) and rebuilds when the pin moved, the binary is gone or broken."""
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _task(path, name):
    return next(t for t in yaml.safe_load((ROOT / path).read_text()) if t.get("name") == name)


def _decide(tmp_path, task, facts, out_var):
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": facts,
             "tasks": [task, {"ansible.builtin.debug": {"msg": "OUT=[{{ %s | bool }}]" % out_var}}]}]
    (tmp_path / "p.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", "p.yml"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout
    return r.stdout.split("OUT=[", 1)[1].split("]", 1)[0] == "True"


CHANGED = {"changed": True}
SKIPPED = {"changed": False, "skipped": True}
HEAD = {"rc": 0, "stdout": "abc"}


@pytest.mark.parametrize("clone,health,built,want", [
    (SKIPPED, 0, {"rc": 0, "stdout": "abc"}, False),   # current: skip
    (SKIPPED, 0, {"rc": 1, "stdout": ""}, False),      # no marker yet, CLI works
    (CHANGED, 0, {"rc": 0, "stdout": "abc"}, True),    # pin moved
    (SKIPPED, 127, {"rc": 0, "stdout": "abc"}, True),  # CLI broken
    (SKIPPED, 0, {"rc": 0, "stdout": "old"}, True),    # built from another commit
])
def test_bitnet_builds_only_when_needed(tmp_path, clone, health, built, want):
    t = _task("roles/optional/bitnet/tasks/main.yml", "Decide whether BitNet.cpp has to be built")
    facts = {"bitnet_clone": clone, "bitnet_cli_health": {"rc": health},
             "bitnet_built_commit": built, "bitnet_head": HEAD}
    assert _decide(tmp_path, t, facts, "bitnet_needs_build") is want


@pytest.mark.parametrize("name,prefix", [("image-view", "dev_tools_image_view"),
                                         ("git-lantern", "dev_tools_git_lantern")])
@pytest.mark.parametrize("exists,clone,built,want", [
    (True, SKIPPED, {"rc": 0, "stdout": "abc"}, False),
    (True, SKIPPED, {"rc": 1, "stdout": ""}, False),
    (False, SKIPPED, {"rc": 0, "stdout": "abc"}, True),
    (True, CHANGED, {"rc": 0, "stdout": "abc"}, True),
    (True, SKIPPED, {"rc": 0, "stdout": "old"}, True),
])
def test_tools_build_only_when_needed(tmp_path, name, prefix, exists, clone, built, want):
    verb = "built" if name == "image-view" else "installed"
    t = _task("roles/dev-tools/tasks/main.yml", f"Decide whether {name} has to be {verb}")
    facts = {f"{prefix}_bin": {"stat": {"exists": exists}}, f"{prefix}_clone": clone,
             f"{prefix}_built": built, f"{prefix}_head": HEAD}
    assert _decide(tmp_path, t, facts, f"{prefix}_needs_build") is want


def test_update_mode_alone_no_longer_forces_a_rebuild():
    text = (ROOT / "roles/dev-tools/tasks/main.yml").read_text()
    assert "nikos_update_mode | bool or not dev_tools_image_view_bin.stat.exists" not in text
    assert "nikos_update_mode | bool or not dev_tools_git_lantern_bin.stat.exists" not in text
