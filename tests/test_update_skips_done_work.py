"""nikos update skips builds that are already current (BitNet, image-view,
vellum, git-lantern) and rebuilds when the pin moved, the binary is gone or broken."""
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
                                         ("vellum", "dev_tools_vellum"),
                                         ("git-lantern", "dev_tools_git_lantern")])
@pytest.mark.parametrize("exists,clone,built,want", [
    (True, SKIPPED, {"rc": 0, "stdout": "abc"}, False),
    (True, SKIPPED, {"rc": 1, "stdout": ""}, False),
    (False, SKIPPED, {"rc": 0, "stdout": "abc"}, True),
    (True, CHANGED, {"rc": 0, "stdout": "abc"}, True),
    (True, SKIPPED, {"rc": 0, "stdout": "old"}, True),
])
def test_tools_build_only_when_needed(tmp_path, name, prefix, exists, clone, built, want):
    verb = "installed" if name == "git-lantern" else "built"
    t = _task("roles/dev-tools/tasks/main.yml", f"Decide whether {name} has to be {verb}")
    facts = {f"{prefix}_bin": {"stat": {"exists": exists}}, f"{prefix}_clone": clone,
             f"{prefix}_built": built, f"{prefix}_head": HEAD}
    assert _decide(tmp_path, t, facts, f"{prefix}_needs_build") is want


def test_update_mode_alone_no_longer_forces_a_rebuild():
    text = (ROOT / "roles/dev-tools/tasks/main.yml").read_text()
    assert "nikos_update_mode | bool or not dev_tools_image_view_bin.stat.exists" not in text
    assert "nikos_update_mode | bool or not dev_tools_git_lantern_bin.stat.exists" not in text
    assert "nikos_update_mode | bool or not dev_tools_vellum_bin.stat.exists" not in text


def _mark_pending(tmp_path, name, facts):
    t = _task("roles/dev-tools/tasks/main.yml", f"Mark {name} as still to be built")
    marker = tmp_path / ".nikos-built" / name
    marker.parent.mkdir()
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"nikos_tools_dir": str(tmp_path), **facts}, "tasks": [t]}]
    (tmp_path / "p.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", "p.yml"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout
    return marker.read_text() if marker.exists() else None


# A due build that did not happen must leave a marker no commit matches; else a
# binary from an older pin, with no marker yet, is adopted as current next run.
@pytest.mark.parametrize("name,prefix,outcome", [
    ("image-view", "dev_tools_image_view_result", SKIPPED),
    ("image-view", "dev_tools_image_view_result", {"failed": True, "rc": 101}),
    ("vellum", "dev_tools_vellum_install", SKIPPED),
])
def test_due_build_that_did_not_happen_marks_pending(tmp_path, name, prefix, outcome):
    base = prefix.rsplit("_", 1)[0]
    facts = {f"{base}_needs_build": True, prefix: outcome}
    assert _mark_pending(tmp_path, name, facts) == "pending\n"


@pytest.mark.parametrize("name,prefix,needs,outcome", [
    ("image-view", "dev_tools_image_view_result", True, {"changed": True, "rc": 0}),
    ("image-view", "dev_tools_image_view_result", False, SKIPPED),
    ("vellum", "dev_tools_vellum_install", True, {"changed": True}),
    ("vellum", "dev_tools_vellum_install", False, SKIPPED),
])
def test_built_or_current_leaves_marker_alone(tmp_path, name, prefix, needs, outcome):
    base = prefix.rsplit("_", 1)[0]
    assert _mark_pending(tmp_path, name, {f"{base}_needs_build": needs, prefix: outcome}) is None
