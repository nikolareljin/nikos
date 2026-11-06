"""`nikos update` runs the playbook twice. These tests run the real `_playbook`
from scripts/nikos twice, with its password helpers and its EXIT trap, against
stub sudo, ansible-playbook and ansible-galaxy on PATH. Nothing real starts.

The gauge is switched off (`_can_use_gauge` returns 1), so both runs take the
plain view, which gets the password file as well.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NIKOS = REPO_ROOT / "scripts" / "nikos"

pytestmark = pytest.mark.skipif(
    shutil.which("script") is None, reason="util-linux `script` is required to provide a /dev/tty"
)

FUNCTIONS = (
    "_restore_terminal_cursor",
    "_cleanup_become_password_file",
    "_start_sudo_keepalive",
    "_stop_sudo_keepalive",
    "_cleanup_run",
    "_plain_view_notice",
    "_become_password_box",
    "_collect_become_password",
    "_ensure_become_password",
    "_offer_dialog_install",
    "_playbook",
)


def extract(name: str) -> str:
    text = NIKOS.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"scripts/nikos no longer defines {name}"
    return match.group(0)


def drive(
    tmp_path: Path,
    typed: bytes,
    *,
    dialog_missing: bool = False,
    nopass: bool = False,
    box_answers: list[str] | None = None,
) -> dict:
    """box_answers: the gauge is available, and a stub dialog answers each
    password box in turn ("CANCEL" presses Cancel)."""
    work = tmp_path
    bindir = work / "bin"
    bindir.mkdir()
    for d in ("home/.git", "logs", "tmp"):
        (work / d).mkdir(parents=True)
    (work / "home" / "requirements.yml").write_text("")
    sudo_log, ansible_log = work / "sudo.log", work / "ansible.log"
    (bindir / "sudo").write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{sudo_log}"\n'
        'if [ "$*" = "-k" ]; then exit 0; fi\n'
        f'if [ "$*" = "-n true" ]; then exit {0 if nopass else 1}; fi\n'
        'if [ "$*" = "-n -v" ]; then exit 0; fi\n'
        'if [ "$*" = "-S -v" ]; then read pw; [ "$pw" = hunter2 ]; exit $?; fi\n'
        'if [ "$1" = "apt-get" ]; then exit 0; fi\n'
        "exit 1\n"
    )
    (bindir / "ansible-playbook").write_text(
        "#!/bin/bash\n"
        'pwfile=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--become-password-file" ] && pwfile="$a"; prev="$a"; done\n'
        'content=""; [ -n "$pwfile" ] && content="$(cat "$pwfile" 2>&1)"\n'
        f'echo "$* | file=[$pwfile] content=[$content]" >> "{ansible_log}"\n'
        'echo "PLAY RECAP"\n'
    )
    (bindir / "ansible-galaxy").write_text("#!/bin/sh\nexit 0\n")
    dialog_log = work / "dialog.log"
    if box_answers is not None:
        (work / "answers").write_text("".join(a + "\n" for a in box_answers))
        (bindir / "dialog").write_text(
            "#!/bin/bash\n"
            f'printf "%s\\n" "$*" >> "{dialog_log}"\n'
            'case " $* " in *" --passwordbox "*) ;; *) exit 0 ;; esac\n'
            f'answer="$(sed -n 1p "{work}/answers")"; sed -i 1d "{work}/answers"\n'
            '[ "$answer" = CANCEL ] && exit 1\n'
            '[ "$answer" = CANNOT_DRAW ] && exit "${DIALOG_ERROR:-255}"\n'
            'printf "%s" "$answer"\n'
        )
    for p in bindir.iterdir():
        p.chmod(0o755)

    program = work / "probe.sh"
    program.write_text(
        "set -euo pipefail\n"
        f'NIKOS_HOME="{work}/home"\n'
        'ANSIBLE_REQUIREMENTS="${NIKOS_HOME}/requirements.yml"\n'
        f'NIKOS_LOG_DIR="{work}/logs"\n'
        'NIKOS_VERSION="test"\nUSE_DIALOG=1\nPROGRESS_LIB="none"\n_PROGRESS_LIB_LOADED=true\n'
        'BECOME_PASSWORD_FILE=""\nNIKOS_BECOME_MODE=""\nNIKOS_BECOME_ASK_REASON=""\nSUDO_KEEPALIVE_PID=""\n'
        'print_error() { echo "[error] $*" >&2; }\n'
        'print_info() { echo "[info] $*"; }\n'
        'print_warn() { echo "[warn] $*"; }\n'
        "_logfile() { :; }\n"
        '_get_default_skip_tags() { echo ""; }\n'
        '_get_saved_tools() { echo ""; }\n'
        "_playbook_summary() { :; }\n"
        "_leave_tui() { :; }\n_leave_box() { :; }\n"
        + (
            # The gauge can draw, so the password is asked in a box; planning
            # fails, so the run itself still takes the plain view.
            "_can_use_gauge() { return 0; }\nnikos_progress_plan() { return 1; }\n"
            if box_answers is not None
            else "_can_use_gauge() { return 1; }\n"
        )
        +
        # The branch order of nikos_progress_why_not, without its dialog and tty checks.
        'nikos_progress_why_not() { [[ -z "${NIKOS_PROGRESS_SKIP_REASON:-}" ]] || echo "${NIKOS_PROGRESS_SKIP_REASON}"; }\n'
        + (
            # dialog reported as missing, so the real install offer runs.
            'command() { if [[ "${1:-}" == "-v" && "${2:-}" == "dialog" ]]; then return 1; fi; builtin command "$@"; }\n'
            if dialog_missing
            else ""
        )
        + "\n\n".join(extract(name) for name in FUNCTIONS)
        + "\n\n"
        + ("" if dialog_missing else "_offer_dialog_install() { :; }\n")
        + "trap '_cleanup_run' EXIT\n"
        # As cmd_update calls it: a failed playbook is reported by the caller.
        '_playbook -e nikos_update_mode=true || { echo "PLAYBOOK_FAILED rc=$?"; exit 9; }\n'
        'echo "BETWEEN mode=${NIKOS_BECOME_MODE} keepalive=${SUDO_KEEPALIVE_PID} file=${BECOME_PASSWORD_FILE}"\n'
        f'echo "${{SUDO_KEEPALIVE_PID}}" > "{work}/keepalive.pid"\n'
        "_playbook --no-saved-skip-tags -e nikos_update_mode=true --tags opt\n"
        'echo "END"\n',
        encoding="utf-8",
    )
    # Checked after the probe has exited and while the terminal is still open:
    # closing the pty would end a stray keepalive and hide a missing stop.
    after = (
        f'pid="$(cat {work}/keepalive.pid 2>/dev/null)"; '
        'if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then echo KEEPALIVE=alive; else echo KEEPALIVE=gone; fi'
    )
    result = subprocess.run(
        ["script", "-qec", f"PATH={bindir}:$PATH TMPDIR={work / 'tmp'} bash {program}; echo PROBE_RC=$?; {after}", "/dev/null"],
        input=typed,
        capture_output=True,
        timeout=120,
    )
    out = result.stdout.decode(errors="replace").replace("\r", "")
    return {
        "out": out,
        "rc": int(re.search(r"PROBE_RC=(\d+)", out).group(1)),
        "dialog": dialog_log.read_text().splitlines() if dialog_log.exists() else [],
        "sudo": sudo_log.read_text().splitlines() if sudo_log.exists() else [],
        "ansible": ansible_log.read_text().splitlines() if ansible_log.exists() else [],
        "left": sorted(p.name for p in (work / "tmp").glob("nikos-become.*")),
    }


def test_two_playbook_runs_ask_once_and_share_one_password_file(tmp_path):
    r = drive(tmp_path, b"hunter2\n")
    assert "END" in r["out"], r["out"]
    assert r["out"].count("Sudo password for") == 1, r["out"]
    assert len(r["ansible"]) == 2, r["ansible"]
    files = [re.search(r"file=\[(.*?)\]", line).group(1) for line in r["ansible"]]
    assert files[0] and files[0] == files[1], files
    assert all("content=[hunter2]" in line for line in r["ansible"]), r["ansible"]
    assert not any("--ask-become-pass" in line for line in r["ansible"])


def test_exit_removes_the_file_stops_the_keepalive_and_drops_the_sudo_timestamp(tmp_path):
    """The probe never cleans up itself: only the EXIT trap does."""
    r = drive(tmp_path, b"hunter2\n")
    between = re.search(r"BETWEEN mode=file keepalive=(\d+) file=(\S+)", r["out"])
    assert between, r["out"]
    assert r["left"] == [], "the password file outlived the command"
    assert "KEEPALIVE=gone" in r["out"], "the keepalive outlived the command"
    assert r["sudo"][-1] == "-k", r["sudo"]


def test_passwordless_sudo_asks_nothing_and_passes_no_password_option(tmp_path):
    r = drive(tmp_path, b"", nopass=True)
    assert "END" in r["out"], r["out"]
    assert "Sudo password for" not in r["out"]
    assert len(r["ansible"]) == 2
    assert not any("become-pass" in line for line in r["ansible"]), r["ansible"]
    assert r["sudo"] == ["-k", "-n true"], r["sudo"]


def test_an_empty_answer_leaves_both_runs_to_ansible_and_says_why_each_time(tmp_path):
    r = drive(tmp_path, b"\n")
    assert "END" in r["out"], r["out"]
    assert r["out"].count("Sudo password for") == 1, r["out"]
    assert len(r["ansible"]) == 2
    assert all("--ask-become-pass" in line for line in r["ansible"]), r["ansible"]
    assert r["out"].count("Plain progress view: empty sudo password") == 2, r["out"]


def test_the_dialog_install_offer_runs_on_the_checked_password(tmp_path):
    """Password first, then the offer: its sudo call must not be followed by a
    second `sudo -k` and a second prompt."""
    r = drive(tmp_path, b"hunter2\ny\n", dialog_missing=True)
    assert "END" in r["out"], r["out"]
    assert r["out"].count("Sudo password for") == 1, r["out"]
    install = r["sudo"].index("apt-get install -y dialog")
    assert r["sudo"][:install] == ["-k", "-n true", "-k", "-S -v"], r["sudo"]
    assert "-S -v" not in r["sudo"][install:], r["sudo"]


def test_with_the_gauge_the_password_is_asked_once_in_a_dialog_box(tmp_path):
    r = drive(tmp_path, b"", box_answers=["hunter2"])
    assert "END" in r["out"], r["out"]
    assert "Sudo password for" not in r["out"]          # the plain prompt did not run
    boxes = [line for line in r["dialog"] if "--passwordbox" in line]
    assert len(boxes) == 1, r["dialog"]
    assert len(r["ansible"]) == 2 and all("content=[hunter2]" in line for line in r["ansible"]), r["ansible"]
    assert r["left"] == []


def test_a_wrong_answer_in_the_box_is_asked_again_and_says_so(tmp_path):
    r = drive(tmp_path, b"", box_answers=["wrong", "hunter2"])
    assert "END" in r["out"], r["out"]
    boxes = [line for line in r["dialog"] if "--passwordbox" in line]
    assert len(boxes) == 2, r["dialog"]
    assert "Sorry, try again." not in boxes[0] and "Sorry, try again." in boxes[1]
    assert all("content=[hunter2]" in line for line in r["ansible"]), r["ansible"]


def test_cancel_in_the_box_runs_nothing_and_exits_130(tmp_path):
    r = drive(tmp_path, b"", box_answers=["CANCEL"])
    assert r["rc"] == 130, (r["rc"], r["out"])
    assert "Cancelled at the sudo password" in r["out"]
    assert "PLAYBOOK_FAILED" not in r["out"]      # a cancel is not reported as a failed playbook
    assert r["ansible"] == [] and "END" not in r["out"]
    assert r["left"] == []
    assert "-S -v" not in r["sudo"]


def test_a_box_that_cannot_draw_falls_back_to_the_plain_prompt(tmp_path):
    r = drive(tmp_path, b"hunter2\n", box_answers=["CANNOT_DRAW"])
    assert "END" in r["out"], r["out"]
    assert r["out"].count("Sudo password for") == 1, r["out"]
    assert len([line for line in r["dialog"] if "--passwordbox" in line]) == 1
    assert all("content=[hunter2]" in line for line in r["ansible"]), r["ansible"]


def test_three_wrong_answers_in_the_box_run_nothing(tmp_path):
    r = drive(tmp_path, b"", box_answers=["a", "b", "c"])
    assert len([line for line in r["dialog"] if "--passwordbox" in line]) == 3
    assert "Sudo rejected the password three times" in r["out"]
    assert "PLAYBOOK_FAILED rc=1" in r["out"] and r["ansible"] == []
    assert r["left"] == []


def test_an_empty_answer_in_the_box_leaves_the_prompt_to_ansible(tmp_path):
    r = drive(tmp_path, b"", box_answers=[""])
    assert "END" in r["out"], r["out"]
    assert len(r["ansible"]) == 2 and all("--ask-become-pass" in line for line in r["ansible"]), r["ansible"]
