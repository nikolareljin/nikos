"""`nikos update` on a terminal with `dialog` runs the repository sync and the
Ansible collection install behind a progressbox; their output goes to a log. These tests run the real `cmd_update`,
`_playbook` and `_boxed_step` from scripts/nikos under a pty (`script`), with
stub sync, sudo, ansible-galaxy and ansible-playbook on PATH and, in most of
them, a stub `dialog` that records its arguments. One test drives the real
`dialog`. Nothing real runs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NIKOS = REPO_ROOT / "scripts" / "nikos"
PROGRESS_LIB = REPO_ROOT / "scripts" / "nikos-progress.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("script") is None, reason="util-linux `script` is required to provide a /dev/tty"
)

BOX_FUNCTIONS = (
    "_leave_box",
    "_boxed_step",
    "_boxed_step_tail",
    "_url_may_use_ssh",
    "_sync_ssh_command",
    "_sync_log_shows_auth_failure",
    "_sync_may_ask_over_ssh",
    "_publish_run_log",
)
# Fails after reading everything, as tee does on a full disk.
TEE_FAILS = "#!/bin/sh\ncat >/dev/null\nexit 1\n"
PLAYBOOK_FUNCTIONS = (
    "_restore_terminal_cursor",
    "_cleanup_become_password_file",
    "_start_sudo_keepalive",
    "_stop_sudo_keepalive",
    "_cleanup_run",
    "_plain_view_notice",
    "_become_password_box",
    "_collect_become_password",
    "_ensure_become_password",
    "_playbook",
)

# Records every call; drains stdin, as a progressbox does, and exits 0.
DIALOG_STUB = (
    "#!/bin/bash\n"
    'printf "%s\\n" "$*" >> "{log}"\n'
    'case " $* " in *" --progressbox "*) cat >/dev/null ;; esac\n'
    "exit 0\n"
)
# A terminal too small for the box: dialog exits at once without reading stdin.
DIALOG_CANNOT_DRAW = (
    "#!/bin/bash\n"
    'printf "%s\\n" "$*" >> "{log}"\n'
    "exit 255\n"
)

COMMON = (
    "set -euo pipefail\n"
    'NIKOS_VERSION="test"\nUSE_DIALOG=1\nPROGRESS_LIB="none"\n_PROGRESS_LIB_LOADED=true\n'
    'print_error() { echo "[error] $*" >&2; }\n'
    'print_info() { echo "[info] $*"; }\n'
    'print_warn() { echo "[warn] $*"; }\n'
    "_logfile() { :; }\n"
    # No user or system git config: a test's remotes are the only ones.
    "export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1\n"
    f'source "{PROGRESS_LIB}"\n'
)


def extract(name: str) -> str:
    text = NIKOS.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"scripts/nikos no longer defines {name}"
    return match.group(0)


def run_in_pty(work: Path, program: Path, bindir: Path, *, before: str = "") -> dict:
    """Runs `bash program` on a pty. `before` is shell run first, such as stty."""
    result = subprocess.run(
        [
            "script", "-qec",
            f"{before}PATH={bindir}:$PATH TMPDIR={work / 'tmp'} TERM=xterm bash {program}; echo PROBE_RC=$?",
            "/dev/null",
        ],
        input=b"",
        capture_output=True,
        timeout=120,
    )
    raw = result.stdout
    out = raw.decode(errors="replace").replace("\r", "")
    dialog_log = work / "dialog.log"
    return {
        "raw": raw,
        "out": out,
        "rc": int(re.search(r"PROBE_RC=(\d+)", out).group(1)),
        "dialog": dialog_log.read_text().splitlines() if dialog_log.exists() else [],
    }


def make_bindir(work: Path, dialog_stub: str | None) -> Path:
    bindir = work / "bin"
    bindir.mkdir()
    (work / "tmp").mkdir()
    if dialog_stub is not None:
        (bindir / "dialog").write_text(dialog_stub.format(log=work / "dialog.log"))
    for p in bindir.iterdir():
        p.chmod(0o755)
    return bindir


# -- cmd_update: the repository sync ------------------------------------------


def git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def drive_update(
    tmp_path: Path,
    *,
    gauge: bool,
    sync_rc: int = 0,
    sync_lines: int = 2,
    dialog_stub: str | None = DIALOG_STUB,
    origin: str | None = "https://example.invalid/nikos.git",
    real_logfile: bool = False,
    log_dir: str = "logs",
    setup: str = "",
    sync_extra: str = "",
    tee_fails: bool = False,
    gitmodules: str = "",
) -> dict:
    work = tmp_path
    bindir = make_bindir(work, dialog_stub)
    if tee_fails:
        (bindir / "tee").write_text(TEE_FAILS)
        (bindir / "tee").chmod(0o755)
    (bindir / "ssh").write_text(f'#!/bin/sh\necho "$*" >> "{work}/ssh.log"\nexit 255\n')
    (bindir / "ssh").chmod(0o755)
    (work / "home").mkdir()
    git("init", "-q", cwd=work / "home")
    if origin is not None:
        git("remote", "add", "origin", origin, cwd=work / "home")
    if gitmodules:
        (work / "home" / ".gitmodules").write_text(gitmodules)
    (work / "logs").mkdir()
    calls = work / "calls.log"
    program = work / "probe.sh"
    program.write_text(
        COMMON
        + setup
        + f'NIKOS_HOME="{work}/home"\nNIKOS_LOG_DIR="{work}/{log_dir}"\n'
        'REPO_URL="https://example.invalid/nikos"\nREPO_SYNC_HELPERS="/nonexistent"\n'
        f'CALLS="{calls}"\n'
        f"_can_use_gauge() {{ return {0 if gauge else 1}; }}\n"
        '_resolve_update_ref() { printf "0.6.5\\n"; }\n'
        # The sync prints what git would, coloured, and ends with its own status.
        "_sync_repo_to_ref() {\n"
        '  echo "sync:$* prompt=${GIT_TERMINAL_PROMPT:-unset}" >> "${CALLS}"\n'
        '  echo "sshcmd=${GIT_SSH_COMMAND:-unset}" >> "${CALLS}.env"\n'
        '  if [[ /dev/stdin -ef /dev/null ]]; then echo "stdin=null" >> "${CALLS}.env"; else echo "stdin=open" >> "${CALLS}.env"; fi\n'
        + sync_extra +
        f'  seq -f "git: line %g" {sync_lines}\n'
        '  printf "\\033[31mgit: fatal: could not fetch\\033[0m\\n"\n'
        f"  return {sync_rc}\n"
        "}\n"
        '_playbook() { echo "playbook:$*" >> "${CALLS}"; NIKOS_LAST_RUN_LOG=/logs/run.log; }\n'
        '_models_offer_removal() { echo "models:offer-removal" >> "${CALLS}"; }\n'
        '_exec_update_continuation() { echo "continuation" >> "${CALLS}"; }\n'
        '_migrate_antigravity_to_snap() { :; }\n'
        '_get_saved_optional_tags() { printf "\\n"; }\n'
        + (extract("_logfile") + "\n\n" if real_logfile else "")
        + "\n\n".join(extract(name) for name in BOX_FUNCTIONS + ("cmd_update",))
        + '\n\necho BEFORE\ncmd_update\necho "END"\n',
        encoding="utf-8",
    )
    r = run_in_pty(work, program, bindir)
    r["calls"] = calls.read_text().splitlines() if calls.exists() else []
    env_log = work / "calls.log.env"
    r["env"] = env_log.read_text().splitlines() if env_log.exists() else []
    ssh_log = work / "ssh.log"
    r["ssh"] = ssh_log.read_text() if ssh_log.exists() else ""
    logs = sorted((work / "logs").glob("nikos-*-sync.log"))
    r["sync_log"] = logs[0] if logs else None
    return r


def test_with_the_gauge_the_sync_runs_behind_a_box_with_its_output_in_a_log(tmp_path):
    r = drive_update(tmp_path, gauge=True)
    assert "END" in r["out"], r["out"]
    boxes = [line for line in r["dialog"] if "--progressbox" in line]
    assert len(boxes) == 1, r["dialog"]
    assert "--keep-tite" in boxes[0] and "Updating NikOS repo and submodules to 0.6.5..." in boxes[0], boxes
    # Neither the step's caption nor git's output on the terminal.
    assert "Updating NikOS repo" not in r["out"] and "git: line" not in r["out"], r["out"]
    assert r["sync_log"] is not None, "the sync wrote no log"
    assert "git: line 1" in r["sync_log"].read_text() and "could not fetch" in r["sync_log"].read_text()
    assert r["calls"][0] == "sync:0.6.5 nikos-update-autostash prompt=0", r["calls"]
    assert r["calls"][1:] == ["continuation", "models:offer-removal", "playbook:-e nikos_update_mode=true"], r["calls"]


def test_a_sync_that_fails_behind_the_box_shows_its_error_and_log_and_exits_1(tmp_path):
    r = drive_update(tmp_path, gauge=True, sync_rc=2)
    assert r["rc"] == 1, (r["rc"], r["out"])
    assert "END" not in r["out"] and not [c for c in r["calls"] if c.startswith("playbook")], r["calls"]
    assert "[error] Failed to update" in r["out"], r["out"]
    # The box is gone: what it hid is printed, then the path to the rest.
    assert "Last lines of" in r["out"] and "git: fatal: could not fetch" in r["out"], r["out"]
    assert r["sync_log"] is not None and f"Log: {r['sync_log']}" in r["out"], r["out"]
    assert "\x1b[31m" not in r["sync_log"].read_bytes().decode(), "the log keeps git's colour codes"


def test_without_the_gauge_the_sync_prints_as_before(tmp_path):
    r = drive_update(tmp_path, gauge=False)
    assert "END" in r["out"], r["out"]
    assert r["dialog"] == [], r["dialog"]
    assert "[info] Updating NikOS repo and submodules to 0.6.5..." in r["out"], r["out"]
    assert "git: line 1" in r["out"] and "git: fatal: could not fetch" in r["out"], r["out"]
    assert r["sync_log"] is None, "the plain path must not write a sync log"
    assert r["calls"][0] == "sync:0.6.5 nikos-update-autostash prompt=unset", r["calls"]


def test_without_the_gauge_a_failed_sync_exits_1_as_before(tmp_path):
    r = drive_update(tmp_path, gauge=False, sync_rc=3)
    assert r["rc"] == 1, (r["rc"], r["out"])
    assert "[error] Failed to update git submodules" in r["out"], r["out"]
    assert "Last lines of" not in r["out"] and r["sync_log"] is None


def test_a_box_that_cannot_draw_does_not_stop_the_sync(tmp_path):
    """dialog exits at once without reading its stdin. The sync must still run
    to its end, with every line in the log, or a checkout is left half-switched."""
    r = drive_update(tmp_path, gauge=True, sync_lines=50000, dialog_stub=DIALOG_CANNOT_DRAW)
    assert "END" in r["out"], r["out"]
    assert r["rc"] == 0 and "playbook:-e nikos_update_mode=true" in r["calls"], r["calls"]
    assert r["sync_log"] is not None
    assert r["sync_log"].read_text().count("git: line ") == 50000


def test_the_boxed_sync_has_no_stdin_to_wait_on(tmp_path):
    r = drive_update(tmp_path, gauge=True)
    assert "stdin=null" in r["env"], r["env"]


@pytest.mark.parametrize(
    "origin",
    ["git@github.com:o/nikos.git", "ssh://git@example.invalid/o/nikos.git", "git+ssh://example.invalid/nikos", "example.invalid:nikos"],
)
def test_an_ssh_origin_syncs_plain_so_a_passphrase_can_be_typed(tmp_path, origin):
    r = drive_update(tmp_path, gauge=True, origin=origin)
    assert "END" in r["out"], r["out"]
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]
    assert "git: line 1" in r["out"] and r["sync_log"] is None, r["out"]
    # Nothing is set that would fail a key with a passphrase and no agent.
    assert r["calls"][0].endswith("prompt=unset") and "sshcmd=unset" in r["env"], (r["calls"], r["env"])


def test_an_ssh_submodule_syncs_plain(tmp_path):
    r = drive_update(
        tmp_path, gauge=True,
        gitmodules='[submodule "s"]\n\tpath = s\n\turl = git@example.invalid:o/s.git\n',
    )
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]


def test_a_local_submodule_url_override_over_ssh_syncs_plain(tmp_path):
    r = drive_update(
        tmp_path, gauge=True,
        setup=f'git -C "{tmp_path}/home" config submodule.s.url git@example.invalid:o/s.git\n',
    )
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]


def test_an_initialised_submodule_whose_own_origin_is_ssh_syncs_plain(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git("init", "-q", cwd=upstream)
    git("commit", "-q", "--allow-empty", "-m", "first", cwd=upstream)
    r = drive_update(
        tmp_path, gauge=True,
        setup=(
            f'git -C "{tmp_path}/home" -c protocol.file.allow=always submodule --quiet add "{upstream}" s\n'
            f'git -C "{tmp_path}/home/s" remote set-url origin git@example.invalid:o/s.git\n'
        ),
    )
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]


def test_an_https_submodule_stays_boxed(tmp_path):
    r = drive_update(
        tmp_path, gauge=True,
        gitmodules='[submodule "s"]\n\tpath = s\n\turl = https://example.invalid/s.git\n',
    )
    assert [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]


def test_an_https_submodule_rewritten_to_ssh_by_insteadof_syncs_plain(tmp_path):
    (tmp_path / "gitconfig").write_text('[url "git@example.invalid:"]\n\tinsteadOf = https://example.invalid/\n')
    r = drive_update(
        tmp_path, gauge=True,
        origin="https://other.invalid/nikos.git",
        setup=f'export GIT_CONFIG_GLOBAL="{tmp_path}/gitconfig"\n',
        gitmodules='[submodule "s"]\n\tpath = s\n\turl = https://example.invalid/s.git\n',
    )
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]


def test_a_git_ssh_wrapper_syncs_plain(tmp_path):
    r = drive_update(tmp_path, gauge=True, setup='export GIT_SSH=/bin/true\n')
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]


def test_an_ssh_url_the_check_could_not_see_gets_batchmode_on_the_users_ssh_command(tmp_path):
    """A submodule only the target ref declares. Real git, stub ssh."""
    r = drive_update(
        tmp_path, gauge=True,
        setup="export GIT_SSH_COMMAND='ssh -i /k'\n",
        sync_extra='  git ls-remote ssh://example.invalid/x || true\n',
    )
    assert [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]
    assert "-i /k -o BatchMode=yes" in r["ssh"], r["ssh"]


def test_core_sshcommand_is_kept_under_batchmode(tmp_path):
    work = tmp_path
    r = drive_update(
        work, gauge=True,
        setup=f'git -C "{work}/home" config core.sshCommand "ssh -i /c"\n',
        sync_extra='  git ls-remote ssh://example.invalid/x || true\n',
    )
    assert "-i /c -o BatchMode=yes" in r["ssh"], r["ssh"]


def test_a_hash_in_git_ssh_command_syncs_plain_as_a_comment_would_swallow_batchmode(tmp_path):
    r = drive_update(tmp_path, gauge=True, setup="export GIT_SSH_COMMAND='ssh -i /k # work key'\n")
    assert "END" in r["out"], r["out"]
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]
    assert "sshcmd=ssh -i /k # work key" in r["env"], r["env"]


def test_a_hash_in_core_sshcommand_syncs_plain(tmp_path):
    r = drive_update(
        tmp_path, gauge=True,
        setup=f"""git -C "{tmp_path}/home" config core.sshCommand 'ssh -i /c # work key'\n""",
    )
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]


def test_an_empty_core_sshcommand_still_names_ssh_under_batchmode(tmp_path):
    r = drive_update(tmp_path, gauge=True, setup=f'git -C "{tmp_path}/home" config core.sshCommand ""\n')
    assert "sshcmd=ssh -o BatchMode=yes" in r["env"], r["env"]


def test_a_checkout_with_no_origin_syncs_plain(tmp_path):
    r = drive_update(tmp_path, gauge=True, origin=None)
    assert "END" in r["out"], r["out"]
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]
    assert "git: line 1" in r["out"] and r["sync_log"] is None, r["out"]


PLAIN_VIEW_HINT = "NIKOS_USE_DIALOG=0 nikos update prints the steps and allows credential prompts."


@pytest.mark.parametrize(
    "error",
    [
        "fatal: could not read Username for 'https://example.invalid': terminal prompts disabled",
        "fatal: could not read Password for 'https://u@example.invalid': No such device or address",
        "Host key verification failed.",
        "git@example.invalid: Permission denied (publickey).",
    ],
)
def test_a_boxed_sync_that_failed_on_auth_says_how_to_allow_credential_prompts(tmp_path, error):
    r = drive_update(tmp_path, gauge=True, sync_rc=2, sync_extra=f'  echo "{error}" >&2\n')
    assert r["rc"] == 1 and PLAIN_VIEW_HINT in r["out"], r["out"]


@pytest.mark.parametrize("sync_rc", [1, 2, 3])
def test_a_boxed_sync_that_failed_on_anything_else_does_not_offer_the_plain_view(tmp_path, sync_rc):
    """rc 1 is a stash conflict: credential prompts have nothing to do with it."""
    r = drive_update(tmp_path, gauge=True, sync_rc=sync_rc, sync_extra='  echo "CONFLICT (content): a.txt"\n')
    assert r["rc"] == 1 and "[error]" in r["out"], r["out"]
    assert "Last lines of" in r["out"] and PLAIN_VIEW_HINT not in r["out"], r["out"]


def test_a_log_dir_that_cannot_be_created_keeps_the_rc_74_message(tmp_path):
    (tmp_path / "blocked").write_text("a file, not a directory")
    r = drive_update(tmp_path, gauge=True, real_logfile=True, log_dir="blocked/logs")
    assert r["rc"] == 1 and "The repository sync finished, but its log" in r["out"], r["out"]
    assert "continuation" not in r["calls"], r["calls"]


@pytest.mark.parametrize("gauge", [True, False])
def test_a_log_dir_that_cannot_be_created_keeps_the_failure_message(tmp_path, gauge):
    (tmp_path / "blocked").write_text("a file, not a directory")
    r = drive_update(tmp_path, gauge=gauge, sync_rc=2, real_logfile=True, log_dir="blocked/logs")
    assert r["rc"] == 1 and "[error] Failed to update" in r["out"], r["out"]
    assert PLAIN_VIEW_HINT not in r["out"], r["out"]


def test_a_sync_log_that_cannot_be_written_is_not_reported_as_a_git_failure(tmp_path):
    r = drive_update(tmp_path, gauge=True, tee_fails=True)
    assert r["rc"] == 1 and "END" not in r["out"], r["out"]
    assert "The repository sync finished, but its log" in r["out"], r["out"]
    assert "Review the git output" not in r["out"] and "Failed to update" not in r["out"], r["out"]
    assert "continuation" not in r["calls"], r["calls"]


# -- _playbook: the collection install ----------------------------------------


def drive_playbook(
    tmp_path: Path, *, gauge: bool, galaxy_rc: int = 0, override: str = "", previous_log: bool = False, tee_fails: bool = False
) -> dict:
    work = tmp_path
    bindir = make_bindir(work, DIALOG_STUB)
    (work / "home" / ".git").mkdir(parents=True)
    (work / "logs").mkdir()
    (work / "home" / "requirements.yml").write_text("")
    if previous_log:
        (work / "logs" / "previous-run.log").write_text("the last real run\n")
        (work / "logs" / "playbook-latest.log").symlink_to(work / "logs" / "previous-run.log")
    ansible_log = work / "ansible.log"
    # Passwordless sudo: no password question in this flow.
    (bindir / "sudo").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "ansible-playbook").write_text(
        "#!/bin/bash\n" f'echo "$*" >> "{ansible_log}"\n' 'echo "PLAY RECAP"\n'
    )
    if tee_fails:
        (bindir / "tee").write_text(TEE_FAILS)
    (bindir / "ansible-galaxy").write_text(
        "#!/bin/sh\n"
        'echo "galaxy: installing community.general"\n'
        'echo "galaxy: ERROR: Gateway Timeout" >&2\n'
        f"exit {galaxy_rc}\n"
    )
    for p in bindir.iterdir():
        p.chmod(0o755)
    program = work / "probe.sh"
    program.write_text(
        COMMON
        + f'NIKOS_HOME="{work}/home"\nNIKOS_LOG_DIR="{work}/logs"\n'
        'ANSIBLE_REQUIREMENTS="${NIKOS_HOME}/requirements.yml"\n'
        'BECOME_PASSWORD_FILE=""\nNIKOS_BECOME_MODE=""\nNIKOS_BECOME_ASK_REASON=""\nSUDO_KEEPALIVE_PID=""\n'
        '_get_default_skip_tags() { echo ""; }\n'
        '_get_saved_tools() { echo ""; }\n'
        "_playbook_summary() { :; }\n"
        "_leave_tui() { :; }\n"
        "_offer_dialog_install() { :; }\n"
        f"_can_use_gauge() {{ return {0 if gauge else 1}; }}\n"
        # Planning fails, so the playbook itself takes the plain view here.
        "nikos_progress_plan() { return 1; }\n"
        + "\n\n".join(extract(name) for name in BOX_FUNCTIONS + PLAYBOOK_FUNCTIONS)
        + "\n"
        + override
        + "\n\ntrap '_cleanup_run' EXIT\n"
        # As cmd_update calls it: errexit is suspended inside _playbook.
        '_playbook -e nikos_update_mode=true || { rc=$?; echo "LAST_LOG=${NIKOS_LAST_RUN_LOG:-none}"; echo "PLAYBOOK_FAILED rc=${rc}"; exit 9; }\n'
        'echo "END"\n',
        encoding="utf-8",
    )
    r = run_in_pty(work, program, bindir)
    # The log digest asks `ansible-playbook --version`; only runs count.
    r["ansible"] = [
        line for line in (ansible_log.read_text().splitlines() if ansible_log.exists() else [])
        if line != "--version"
    ]
    latest = work / "logs" / "playbook-latest.log"
    r["run_log"] = latest.resolve() if latest.exists() else None
    return r


def test_with_the_gauge_the_collection_install_runs_behind_a_box_into_the_run_log(tmp_path):
    r = drive_playbook(tmp_path, gauge=True)
    assert "END" in r["out"], r["out"]
    boxes = [line for line in r["dialog"] if "--progressbox" in line]
    assert len(boxes) == 1 and "--keep-tite" in boxes[0], r["dialog"]
    assert "Installing required Ansible collections..." in boxes[0], boxes
    assert "Installing required Ansible collections" not in r["out"], r["out"]
    assert "galaxy: installing" not in r["out"] and "Gateway Timeout" not in r["out"], r["out"]
    assert r["run_log"] is not None and "galaxy: installing community.general" in r["run_log"].read_text()
    assert len(r["ansible"]) == 1, r["ansible"]


def test_a_collection_install_that_fails_behind_the_box_is_shown_and_the_playbook_does_not_run(tmp_path):
    r = drive_playbook(tmp_path, gauge=True, galaxy_rc=5)
    assert "PLAYBOOK_FAILED rc=5" in r["out"], r["out"]
    assert r["ansible"] == [], "the playbook ran without the collections"
    assert "[error] Failed to install required Ansible collections (exit 5)" in r["out"], r["out"]
    assert "Last lines of" in r["out"] and "galaxy: ERROR: Gateway Timeout" in r["out"], r["out"]
    assert r["run_log"] is not None and f"Log: {r['run_log']}" in r["out"], r["out"]


def test_without_the_gauge_the_collection_install_prints_as_before(tmp_path):
    r = drive_playbook(tmp_path, gauge=False)
    assert "END" in r["out"], r["out"]
    assert not [line for line in r["dialog"] if "--progressbox" in line], r["dialog"]
    assert "[info] Installing required Ansible collections..." in r["out"], r["out"]
    assert "galaxy: installing community.general" in r["out"], r["out"]
    assert "galaxy: installing" not in r["run_log"].read_text()


def test_without_the_gauge_a_failed_collection_install_stops_the_run_with_its_code(tmp_path):
    """Called as `_playbook || rc=$?`, errexit is off inside: the failure has
    to be checked, or ansible runs without the collections."""
    r = drive_playbook(tmp_path, gauge=False, galaxy_rc=5)
    assert "PLAYBOOK_FAILED rc=5" in r["out"], r["out"]
    assert r["ansible"] == [], "the playbook ran without the collections"
    assert "Failed to install required Ansible collections (exit 5)" in r["out"], r["out"]


@pytest.mark.parametrize("gauge", [True, False])
def test_a_failed_collection_install_names_a_log_that_exists(tmp_path, gauge):
    r = drive_playbook(tmp_path, gauge=gauge, galaxy_rc=5)
    assert r["run_log"] is not None, "playbook-latest.log dangles"
    assert f"LAST_LOG={r['run_log']}" in r["out"], r["out"]
    assert "[FAILED] ansible collections install (rc=5)" in r["run_log"].read_text()


@pytest.mark.parametrize("gauge", [True, False])
@pytest.mark.parametrize("become_rc", [130, 7])
def test_a_cancel_or_early_become_failure_keeps_the_last_real_runs_log(tmp_path, gauge, become_rc):
    r = drive_playbook(
        tmp_path, gauge=gauge, previous_log=True,
        override=f"_ensure_become_password() {{ return {become_rc}; }}\n",
    )
    assert r["ansible"] == [], r["ansible"]
    assert r["run_log"] == tmp_path / "logs" / "previous-run.log", r["out"]


def test_the_latest_link_does_not_dangle_when_tee_writes_nothing(tmp_path):
    drive_playbook(tmp_path, gauge=False, tee_fails=True)
    latest = tmp_path / "logs" / "playbook-latest.log"
    assert latest.is_symlink() and latest.exists()


def test_a_collection_log_that_cannot_be_written_is_not_reported_as_a_failed_install(tmp_path):
    r = drive_playbook(tmp_path, gauge=True, tee_fails=True)
    assert "PLAYBOOK_FAILED rc=74" in r["out"], r["out"]
    assert "The Ansible collections installed, but the log" in r["out"], r["out"]
    assert "Failed to install" not in r["out"] and r["ansible"] == [], r["out"]
    assert "LAST_LOG=none" in r["out"], r["out"]


# -- the real dialog ----------------------------------------------------------


@pytest.mark.skipif(shutil.which("dialog") is None, reason="dialog is required")
def test_the_real_dialog_draws_the_box_on_the_alternate_screen_and_keeps_what_came_before(tmp_path):
    work = tmp_path
    bindir = make_bindir(work, None)
    program = work / "probe.sh"
    program.write_text(
        COMMON
        + "step() { echo 'git: line one'; echo 'git: line two'; return 3; }\n"
        + "\n\n".join(extract(name) for name in BOX_FUNCTIONS)
        + "\n\necho BEFORE\nrc=0\n"
        f'_boxed_step "Updating NikOS repo and submodules to 1.2.3..." "{work}/step.log" step || rc=$?\n'
        'echo "AFTER rc=${rc}"\n',
        encoding="utf-8",
    )
    r = run_in_pty(work, program, bindir, before="stty cols 80 rows 24; ")
    assert "AFTER rc=3" in r["out"], r["out"]
    assert (work / "step.log").read_text() == "git: line one\ngit: line two\n"
    raw = r["raw"]
    # Without --keep-tite dialog leaves the alternate screen again at once and
    # draws on the normal one, over the text that was there: the box text then
    # comes after the first rmcup, not before it.
    smcup = raw.find(b"\x1b[?1049h")
    assert smcup > 0, "no alternate screen"
    rmcup = raw.find(b"\x1b[?1049l", smcup)
    assert rmcup > smcup, "the alternate screen was never left"
    assert raw.find(b"BEFORE") < smcup, "the text before the box was drawn over"
    assert smcup < raw.find(b"Updating NikOS repo") < rmcup, "the box was drawn on the normal screen"
    assert raw.find(b"AFTER rc=3") > rmcup
