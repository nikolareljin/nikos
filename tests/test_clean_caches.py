"""scripts/clean-caches.sh (nikos clean): what it removes, and what it never does.

docker, uv, pnpm and npm are stubs that log their arguments, so nothing on the
machine is touched. The repositories are real git repositories in a temporary
directory, with their own identity and backdated commits.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "clean-caches.sh"
OLD = "2026-01-01T00:00:00"


def test_the_script_never_names_a_command_that_removes_docker_data():
    """Volumes hold databases, indexes and models; containers can hold state."""
    code = "\n".join(l for l in SCRIPT.read_text().splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("docker volume", "volume prune", "system prune", "container prune", "docker rm ", "--volumes"):
        assert forbidden not in code, forbidden
    # The one rm in the script removes a path checked to be a node_modules directory.
    assert len(re.findall(r"\brm -rf\b", code)) == 1


@pytest.fixture()
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls"
    for name in ("docker", "uv", "pnpm", "npm"):
        (bindir / name).write_text(
            f'#!/bin/sh\necho "{name} $*" >> {log}\n'
            'case "$*" in "system df"*) echo "Build Cache|1.5GB" ;; "cache dir") echo /nonexistent ;; esac\n'
            "exit 0\n"
        )
        (bindir / name).chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(PATH=f"{bindir}:{e['PATH']}", HOME=str(home),
             GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
             GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return {"env": e, "log": log, "projects": projects}


def run(env, *args, stdin=subprocess.DEVNULL):
    r = subprocess.run(["bash", str(SCRIPT), "--projects", str(env["projects"]), *args],
                       capture_output=True, text=True, env=env["env"], stdin=stdin, timeout=120)
    calls = env["log"].read_text() if env["log"].exists() else ""
    return r, calls


def repo(env, name, *, date=OLD, package_json=True, node_modules=True, track_nm=False, dirty=False):
    path = env["projects"] / name
    path.mkdir()
    e = dict(env["env"], GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=e)
    (path / "README").write_text("x\n")
    (path / ".gitignore").write_text("node_modules/\n")
    if package_json:
        (path / "package.json").write_text("{}\n")
    if node_modules:
        (path / "node_modules" / "left-pad").mkdir(parents=True)
        (path / "node_modules" / "left-pad" / "index.js").write_text("x\n")
    subprocess.run(["git", "-C", str(path), "add", "-f", "README", ".gitignore"] + (["package.json"] if package_json else [])
                   + (["node_modules"] if track_nm else []), check=True, env=e)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True, env=e)
    if dirty:
        (path / "README").write_text("changed\n")
    return path


def test_a_dry_run_removes_nothing(env):
    nm = repo(env, "idle") / "node_modules"
    r, calls = run(env)
    assert r.returncode == 0, r.stderr
    assert "Dry run: nothing was removed" in r.stdout
    assert nm.is_dir()
    for word in ("prune", "verify"):
        assert word not in calls, calls


def test_apply_runs_only_the_unused_cleanups(env):
    r, calls = run(env, "--apply", "--yes")
    assert r.returncode == 0, r.stderr
    assert "docker builder prune -f --filter until=168h" in calls
    assert "docker image prune -f\n" in calls          # dangling only: no -a
    assert "image prune -a" not in calls
    assert "uv cache prune" in calls and "pnpm store prune" in calls and "npm cache verify" in calls
    assert "volume" not in calls


def test_keep_days_sets_the_build_cache_age(env):
    _, calls = run(env, "--apply", "--yes", "--keep-days", "14", "--only", "docker")
    assert "docker builder prune -f --filter until=336h" in calls


def test_unused_tagged_images_only_when_asked(env):
    _, calls = run(env, "--apply", "--yes", "--only", "docker", "--unused-images")
    assert "docker image prune -a -f --filter until=168h" in calls


def test_node_modules_go_only_from_idle_clean_repositories(env):
    idle = repo(env, "idle")
    active = repo(env, "active", date="2099-01-01T00:00:00")
    dirty = repo(env, "dirty", dirty=True)
    no_pkg = repo(env, "no-package-json", package_json=False)
    tracked = repo(env, "tracked", track_nm=True)
    r, _ = run(env, "--apply", "--yes", "--only", "node")
    assert r.returncode == 0, r.stderr
    assert not (idle / "node_modules").exists()
    for kept in (active, dirty, no_pkg, tracked):
        assert (kept / "node_modules").is_dir(), kept.name


def test_no_terminal_and_no_yes_removes_nothing(env):
    nm = repo(env, "idle") / "node_modules"
    r, calls = run(env, "--apply")
    assert r.returncode == 1 and "pass --yes" in r.stderr
    assert nm.is_dir() and "prune" not in calls


@pytest.mark.parametrize("args", [["--keep-days", "x"], ["--only", "volumes"], ["--bogus"]])
def test_bad_options_are_refused(env, args):
    r, calls = run(env, *args)
    assert r.returncode == 2 and calls == ""
