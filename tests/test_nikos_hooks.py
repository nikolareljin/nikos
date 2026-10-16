"""scripts/nikos-hooks.sh (nikos hooks): what it passes to lantern, agentvault
and setup-hooks.sh, and that a bad option changes nothing.

lantern, agentvault and gitleaks are stubs that log their arguments. git is the
real one, with a throwaway global config.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "nikos-hooks.sh"


@pytest.fixture()
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls"
    log.write_text("")
    for name in ("lantern", "agentvault", "gitleaks"):
        (bindir / name).write_text(
            f'#!/bin/sh\necho "{name} $*" >> "{log}"\n'
            'case "$*" in "hooks export "*) echo \'{"kind":"lantern-hooks","owners":["me","my-llc"]}\' > "$3" ;;\n'
            '  "export "*) : > "$2" ;; "hooks --help") [ -n "$NO_HOOKS" ] && exit 2; exit 0 ;; esac\n'
            'exit "${STUB_RC:-0}"\n')
        (bindir / name).chmod(0o755)
    helpers = tmp_path / "sh"
    (helpers / "scripts").mkdir(parents=True)
    (helpers / "VERSION").write_text("0.50.0\n")
    (helpers / "scripts" / "setup-hooks.sh").write_text(f'echo "setup-hooks $*" >> "{log}"\n')
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("")
    e = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(tmp_path),
             GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1",
             NIKOS_HOME=str(tmp_path / "nikos"), NIKOS_HOOKS_ROOT=str(tmp_path / "Projects"))
    subprocess.run(["git", "config", "--global", "script-helpers.home", str(helpers)], env=e, check=True)
    return {"env": e, "log": log, "tmp": tmp_path}


def run(env, *args, **extra):
    e = dict(env["env"], **extra)
    return subprocess.run(["bash", str(SCRIPT), *args], env=e, capture_output=True, text=True)


def calls(env):
    return [l for l in env["log"].read_text().splitlines() if l and "hooks --help" not in l]


def git_get(env, key):
    return subprocess.run(["git", "config", "--global", "--get", key], env=env["env"],
                          capture_output=True, text=True).stdout.strip()


def test_status_is_the_default_and_lists_the_tools(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert "script-helpers:" in r.stdout and "0.50.0" in r.stdout
    assert "owners:         unset" in r.stdout
    assert calls(env)[-1] == f"lantern hooks status --root {env['tmp'] / 'Projects'}"


def test_apply_passes_its_options_and_root(env):
    r = run(env, "apply", "--dry-run", "--batch", "10", "--agents", "claude,codex", "--root", "/srv/x")
    assert r.returncode == 0, r.stderr
    assert calls(env) == ["lantern hooks apply --root /srv/x --dry-run --batch 10 --agents claude,codex"]


@pytest.mark.parametrize("args", [
    ["apply", "--force"], ["apply", "--batch"], ["repair", "--agents", "all"], ["remove", "--dry-run"],
    ["--bogus"], ["install"], ["apply", "--root="], ["apply", "--root"], ["--global", "--claude"], ["export"], ["export", "a", "b"], ["import"],
])
def test_bad_usage_exits_2_and_runs_nothing(env, args):
    r = run(env, *args)
    assert r.returncode == 2, (args, r.stdout, r.stderr)
    assert calls(env) == []


def test_a_lantern_without_hooks_is_refused(env):
    r = run(env, "apply", NO_HOOKS="1")
    assert r.returncode == 2 and "no 'hooks' command" in r.stderr
    assert calls(env) == []


def test_global_is_explicit_and_uses_the_configured_script_helpers(env):
    assert run(env, "--global").returncode == 0
    assert run(env, "--global", "--uninstall").returncode == 0
    assert calls(env) == ["setup-hooks --global", "setup-hooks --global --uninstall"]


def test_export_writes_both_files_into_one_folder(env):
    out = env["tmp"] / "carry"
    r = run(env, "export", str(out))
    assert r.returncode == 0, r.stderr
    assert (out / "lantern-hooks.json").is_file() and (out / "agentvault.avbundle").is_file()
    assert calls(env) == [f"lantern hooks export {out}/lantern-hooks.json --root {env['tmp'] / 'Projects'}",
                          f"agentvault export {out}/agentvault.avbundle"]


def test_import_sets_owners_only_when_unset_then_imports_both(env):
    out = env["tmp"] / "carry"
    run(env, "export", str(out))
    env["log"].write_text("")
    r = run(env, "import", str(out))
    assert r.returncode == 0, r.stderr
    assert git_get(env, "script-helpers.owners") == "me,my-llc"
    assert calls(env) == [f"lantern hooks import {out}/lantern-hooks.json --root {env['tmp'] / 'Projects'}",
                          f"agentvault import {out}/agentvault.avbundle"]
    subprocess.run(["git", "config", "--global", "script-helpers.owners", "someone-else"], env=env["env"], check=True)
    assert run(env, "import", str(out)).returncode == 0
    assert git_get(env, "script-helpers.owners") == "someone-else"


def test_import_of_a_folder_without_an_export_changes_nothing(env):
    (env["tmp"] / "empty").mkdir()
    r = run(env, "import", str(env["tmp"] / "empty"))
    assert r.returncode == 2
    assert calls(env) == [] and git_get(env, "script-helpers.owners") == ""


def test_a_failed_step_is_exit_1(env):
    r = run(env, "export", str(env["tmp"] / "carry"), STUB_RC="1")
    assert r.returncode == 1


def test_nikos_dispatches_hooks():
    text = (ROOT / "scripts" / "nikos").read_text()
    assert 'hooks)  shift; exec bash "${NIKOS_HOME}/scripts/nikos-hooks.sh" "$@" ;;' in text


def test_lantern_gets_the_script_helpers_the_status_shows(env):
    """Without script-helpers.home, lantern would look for its own vendored copy,
    which an installed lantern does not have; it gets NikOS's pinned copy."""
    stub = env["tmp"] / "bin" / "lantern"
    stub.write_text(f'#!/bin/sh\necho "SH=$SCRIPT_HELPERS_HOME" >> "{env["log"]}"\n')
    stub.chmod(0o755)
    subprocess.run(["git", "config", "--global", "--unset", "script-helpers.home"], env=env["env"], check=True)
    assert run(env, "apply").returncode == 0
    assert f"SH={env['tmp'] / 'nikos' / 'scripts' / 'script-helpers'}" in env["log"].read_text()


def fake_claude(env, state, hook="/data/script-helpers/claude-hooks/scripts/claude-hooks/pretooluse_private_names.sh"):
    """A setup-hooks.sh that knows --status --porcelain --claude (newer than 0.53.1) and
    reports <state>; --claude logs and makes it ok."""
    sh = Path(git_get(env, "script-helpers.home")) / "scripts" / "setup-hooks.sh"
    st = env["tmp"] / "claude-state"
    st.write_text(state)
    sh.write_text(
        f'echo "setup-hooks $*" >> "{env["log"]}"\n'
        f'case "$*" in "--status --porcelain --claude") printf "claude_user=%s\\thook={hook}\\tinstalled=0.54.0\\n" "$(cat {st})" ;;\n'
        f'  "--claude") echo ok > {st} ;; esac\n')


@pytest.mark.parametrize("state,line", [
    ("ok", "claude hook:    ok (/data/"),
    ("absent", "claude hook:    NOT INSTALLED (nikos hooks repair)"),
    ("broken", "claude hook:    BROKEN: /data/"),
    ("stale", "claude hook:    STALE: runs /data/"),
])
def test_status_shows_the_claude_hook(env, state, line):
    fake_claude(env, state)
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert line in r.stdout
    assert "setup-hooks --claude" not in calls(env)        # status changes nothing


def test_status_with_an_older_script_helpers_never_runs_it(env):
    r = run(env)
    assert "claude hook:    not checked: script-helpers 0.50.0 cannot (nikos update)" in r.stdout
    assert not [c for c in calls(env) if c.startswith("setup-hooks")]


@pytest.mark.parametrize("sub", ["repair", "apply"])
@pytest.mark.parametrize("state", ["absent", "broken", "stale"])
def test_repair_and_apply_install_a_bad_claude_hook_first(env, sub, state):
    subprocess.run(["git", "config", "--global", "script-helpers.owners", "me"], env=env["env"], check=True)
    fake_claude(env, state)
    r = run(env, sub)
    assert r.returncode == 0, r.stderr
    c = [x for x in calls(env) if "--porcelain" not in x]
    assert c == ["setup-hooks --claude", f"lantern hooks {sub} --root {env['tmp'] / 'Projects'}"]


def test_repair_leaves_a_good_claude_hook_alone(env):
    subprocess.run(["git", "config", "--global", "script-helpers.owners", "me"], env=env["env"], check=True)
    fake_claude(env, "ok")
    assert run(env, "repair").returncode == 0
    assert "setup-hooks --claude" not in calls(env)


def test_repair_with_an_older_script_helpers_installs_anyway(env):
    subprocess.run(["git", "config", "--global", "script-helpers.owners", "me"], env=env["env"], check=True)
    assert run(env, "repair").returncode == 0
    assert calls(env)[0] == "setup-hooks --claude"


def test_dry_run_only_reports_the_claude_hook(env):
    subprocess.run(["git", "config", "--global", "script-helpers.owners", "me"], env=env["env"], check=True)
    fake_claude(env, "stale")
    r = run(env, "apply", "--dry-run")
    assert "claude hook: would install it" in r.stdout
    assert "setup-hooks --claude" not in calls(env)


def test_no_owners_says_so_and_installs_nothing(env):
    fake_claude(env, "absent")
    r = run(env, "repair")
    assert "set owners first" in r.stderr
    assert "setup-hooks --claude" not in calls(env)


def test_a_failed_claude_install_is_exit_1(env):
    subprocess.run(["git", "config", "--global", "script-helpers.owners", "me"], env=env["env"], check=True)
    fake_claude(env, "broken")
    sh = Path(git_get(env, "script-helpers.home")) / "scripts" / "setup-hooks.sh"
    sh.write_text(sh.read_text().replace('"--claude") echo ok', '"--claude") exit 2; echo ok'))
    assert run(env, "repair").returncode == 1


def test_the_playbook_installs_the_claude_hook_from_the_pinned_copy():
    text = (ROOT / "roles" / "dev-tools" / "tasks" / "main.yml").read_text()
    assert "- name: Install the Claude Code hook for this user" in text
    assert "/scripts/setup-hooks.sh\"\n      - --claude" in text


def test_a_failed_check_is_said_as_such(env):
    fake_claude(env, "ok")
    sh = Path(git_get(env, "script-helpers.home")) / "scripts" / "setup-hooks.sh"
    sh.write_text(sh.read_text().replace('"--status --porcelain --claude")', '"--status --porcelain --claude") exit 1;'))
    r = run(env)
    assert "claude hook:    could not be checked" in r.stdout


def test_only_leaves_the_user_hook_alone(env):
    only = ["--only", "a"]
    subprocess.run(["git", "config", "--global", "script-helpers.owners", "me"], env=env["env"], check=True)
    fake_claude(env, "stale")
    assert run(env, "repair", *only).returncode == 0
    assert "setup-hooks --claude" not in calls(env)


def test_no_python_is_said_as_such(env):
    fake_claude(env, "unknown")
    assert "claude hook:    unknown: no Python" in run(env).stdout
