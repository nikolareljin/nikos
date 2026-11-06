"""`nikos update` on a terminal with `dialog` runs the repository sync and the
Ansible collection install behind a progressbox, so nothing is printed between
the boxes; their output goes to a log. These tests run the real `cmd_update`,
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

BOX_FUNCTIONS = ("_leave_box", "_boxed_step", "_boxed_step_tail")
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


def drive_update(
    tmp_path: Path, *, gauge: bool, sync_rc: int = 0, sync_lines: int = 2, dialog_stub: str | None = DIALOG_STUB
) -> dict:
    work = tmp_path
    bindir = make_bindir(work, dialog_stub)
    (work / "home" / ".git").mkdir(parents=True)
    (work / "logs").mkdir()
    calls = work / "calls.log"
    program = work / "probe.sh"
    program.write_text(
        COMMON
        + f'NIKOS_HOME="{work}/home"\nNIKOS_LOG_DIR="{work}/logs"\n'
        'REPO_URL="https://example.invalid/nikos"\nREPO_SYNC_HELPERS="/nonexistent"\n'
        f'CALLS="{calls}"\n'
        f"_can_use_gauge() {{ return {0 if gauge else 1}; }}\n"
        '_resolve_update_ref() { printf "0.6.5\\n"; }\n'
        # The sync prints what git would, coloured, and ends with its own status.
        "_sync_repo_to_ref() {\n"
        '  echo "sync:$* prompt=${GIT_TERMINAL_PROMPT:-unset}" >> "${CALLS}"\n'
        f'  seq -f "git: line %g" {sync_lines}\n'
        '  printf "\\033[31mgit: fatal: could not fetch\\033[0m\\n"\n'
        f"  return {sync_rc}\n"
        "}\n"
        '_playbook() { echo "playbook:$*" >> "${CALLS}"; NIKOS_LAST_RUN_LOG=/logs/run.log; }\n'
        '_models_offer_removal() { echo "models:offer-removal" >> "${CALLS}"; }\n'
        '_exec_update_continuation() { echo "continuation" >> "${CALLS}"; }\n'
        '_get_saved_optional_tags() { printf "\\n"; }\n'
        + "\n\n".join(extract(name) for name in BOX_FUNCTIONS + ("cmd_update",))
        + '\n\necho BEFORE\ncmd_update\necho "END"\n',
        encoding="utf-8",
    )
    r = run_in_pty(work, program, bindir)
    r["calls"] = calls.read_text().splitlines() if calls.exists() else []
    logs = sorted((work / "logs").glob("nikos-*-sync.log"))
    r["sync_log"] = logs[0] if logs else None
    return r


def test_with_the_gauge_the_sync_runs_behind_a_box_with_its_output_in_a_log(tmp_path):
    r = drive_update(tmp_path, gauge=True)
    assert "END" in r["out"], r["out"]
    boxes = [line for line in r["dialog"] if "--progressbox" in line]
    assert len(boxes) == 1, r["dialog"]
    assert "--keep-tite" in boxes[0] and "Updating NikOS repo and submodules to 0.6.5..." in boxes[0], boxes
    # Nothing between the boxes: neither the step's caption nor git's output.
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


# -- _playbook: the collection install ----------------------------------------


def drive_playbook(tmp_path: Path, *, gauge: bool, galaxy_rc: int = 0) -> dict:
    work = tmp_path
    bindir = make_bindir(work, DIALOG_STUB)
    (work / "home" / ".git").mkdir(parents=True)
    (work / "logs").mkdir()
    (work / "home" / "requirements.yml").write_text("")
    ansible_log = work / "ansible.log"
    # Passwordless sudo: no password question in this flow.
    (bindir / "sudo").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "ansible-playbook").write_text(
        "#!/bin/bash\n" f'echo "$*" >> "{ansible_log}"\n' 'echo "PLAY RECAP"\n'
    )
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
        + "\n\ntrap '_cleanup_run' EXIT\n"
        # As cmd_update calls it: errexit is suspended inside _playbook.
        '_playbook -e nikos_update_mode=true || { echo "PLAYBOOK_FAILED rc=$?"; exit 9; }\n'
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
