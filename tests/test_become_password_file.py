"""Guards on the sudo password file scripts/nikos hands to ansible.

The defect class is a failure path that reports success. `nikos setup` and
`nikos update` collect the become password before the progress gauge starts,
because ansible's own `--ask-become-pass` prompt reads /dev/tty and the gauge is
drawing on it at the same moment. The collected password goes into a temp file
passed as `--become-password-file`.

The caller reads a non-zero return as "fall back to --ask-become-pass", and it
calls the collector inside an `&&` condition - a context where bash suspends
errexit for the whole list. So an unchecked failure in there neither aborts nor
returns: it carries on. `chmod 600` failing was ignored outright, and the
function went on to write the password and report success, having never
confirmed the permissions it exists to guarantee. Measured on the unfixed
version with a failing `chmod` on PATH: `RESULT=ok`.

Every step is now checked on its own, and the path is published to
BECOME_PASSWORD_FILE the moment the file exists, so the INT/TERM traps can see
it - the guarantee is that every later failure cleans up that published path,
not that publication waits for the password. Holding it back until the write had
succeeded would leave a window in which an interrupt stranded a mode-600 file
containing the password on disk.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NIKOS = REPO_ROOT / "scripts" / "nikos"

HELPERS = ("_cleanup_become_password_file", "_collect_become_password")

SCRIPT = shutil.which("script")
pytestmark = pytest.mark.skipif(
    SCRIPT is None, reason="util-linux `script` is required to provide a /dev/tty"
)


def extract_helper(name: str) -> str:
    """Pull a bash function out of scripts/nikos so it can be run on its own."""
    text = NIKOS.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"scripts/nikos no longer defines {name}"
    return match.group(0)


def write_program(tmp_path: Path) -> Path:
    program = tmp_path / "probe.sh"
    program.write_text(
        "set -euo pipefail\n"
        + "\n\n".join(extract_helper(name) for name in HELPERS)
        + "\n\n"
        + 'BECOME_PASSWORD_FILE=""\n'
        + 'print_error() { echo "[error] $*" >&2; }\n'
        # The real call site: an `&&` condition, where errexit is suspended.
        + "if true && _collect_become_password; then\n"
        + '  echo "RESULT=ok mode=$(stat -c %a "${BECOME_PASSWORD_FILE}")"\n'
        + "else\n"
        + '  echo "RESULT=fallback published=[${BECOME_PASSWORD_FILE}]"\n'
        + "fi\n"
        + 'echo "REACHED_END=yes"\n',
        encoding="utf-8",
    )
    return program


def run(program: Path, tmp_path: Path, *, prefix: str = "", tmpdir: str = "") -> str:
    """Run the probe under a pty, so its /dev/tty read has somewhere to read from."""
    command = f"{prefix} TMPDIR={tmpdir or tmp_path} bash {program}".strip()
    result = subprocess.run(
        [SCRIPT, "-qec", command, "/dev/null"],
        input=b"hunter2\n",
        capture_output=True,
        timeout=60,
    )
    return result.stdout.decode(errors="replace").replace("\r", "")


def temp_files(tmp_path: Path) -> list[Path]:
    return sorted(tmp_path.glob("nikos-become.*"))


def test_password_file_is_private_and_holds_the_password(tmp_path):
    out = run(write_program(tmp_path), tmp_path)
    assert "RESULT=ok" in out, out
    assert "mode=600" in out, out

    written = temp_files(tmp_path)
    assert len(written) == 1, written
    assert written[0].read_text(encoding="utf-8") == "hunter2\n"
    assert os.stat(written[0]).st_mode & 0o077 == 0, "group/other can read the password"


def test_falls_back_and_leaves_nothing_when_permissions_cannot_be_set(tmp_path):
    """The regression: chmod failing used to be ignored and reported as success."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    failing_chmod = bindir / "chmod"
    failing_chmod.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failing_chmod.chmod(0o755)

    out = run(write_program(tmp_path), tmp_path, prefix=f"PATH={bindir}:$PATH")

    assert "RESULT=fallback" in out, out
    assert "published=[]" in out, out
    assert temp_files(tmp_path) == [], "a temp file survived a failed collection"


def test_the_gauge_is_planned_before_it_is_run():
    """A gauge that was never planned reports 0% for the whole run.

    `nikos_progress_run` renders against the role list and task total that
    `nikos_progress_plan` produces. Called without the planner,
    `NIKOS_PROGRESS_TOTAL` stays zero, the percentage is never computed, and the
    bar sits at 0% until `PLAY RECAP` jumps it to 100 - a progress bar that does
    not report progress. This is a static check because the alternative is
    running a real playbook; what it guards is the ordering, which is the part
    that was wrong.
    """
    # Comments name both functions, so only real code lines are considered.
    code = [
        line
        for line in NIKOS.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    planned = [i for i, line in enumerate(code) if "nikos_progress_plan" in line]
    ran = [i for i, line in enumerate(code) if "nikos_progress_run" in line]

    assert planned, "the gauge is run without being planned"
    assert ran, "scripts/nikos no longer runs the gauge"
    assert min(planned) < min(ran), (
        "nikos_progress_run is reached before nikos_progress_plan"
    )
    # Planning that fails must drop to the plain view rather than draw an empty
    # gauge. Match the standalone assignment: `local use_gauge=false` is the
    # initializer and would satisfy a substring check even with the fallback gone.
    assert any(line.strip() == "use_gauge=false" for line in code), (
        "a failed plan no longer falls back to the plain view"
    )


def test_the_trap_can_see_the_file_before_the_password_is_written():
    """An interrupt must never strand a file holding the sudo password.

    The INT/TERM trap removes what BECOME_PASSWORD_FILE names, and nothing else.
    Holding the path in a local until the write had succeeded left a window in
    which Ctrl-C stranded a mode-600 file containing the password on disk. The
    ordering is the whole guarantee, so it is what this asserts.
    """
    body = re.search(
        r"^_collect_become_password\(\) \{.*?^\}",
        NIKOS.read_text(encoding="utf-8"),
        re.M | re.S,
    )
    assert body, "scripts/nikos no longer defines _collect_become_password"
    code = [
        line
        for line in body.group(0).splitlines()
        if not line.lstrip().startswith("#")
    ]

    registered = next(
        i for i, line in enumerate(code) if 'BECOME_PASSWORD_FILE="$(mktemp' in line
    )
    written = next(i for i, line in enumerate(code) if "> \"${BECOME_PASSWORD_FILE}\"" in line)
    assert registered < written, (
        "the password is written before the trap can see the file"
    )


def test_falls_back_without_aborting_when_the_file_cannot_be_created(tmp_path):
    """errexit is suspended in the caller's `&&`, so this must return, not drift on."""
    out = run(
        write_program(tmp_path), tmp_path, tmpdir="/nonexistent-nikos-tmpdir"
    )

    assert "RESULT=fallback" in out, out
    assert "published=[]" in out, out
    assert "REACHED_END=yes" in out, out


def test_an_interrupt_restores_the_cursor(tmp_path):
    """Ctrl-C during the gauge must not leave an invisible prompt behind.

    `dialog` hides the cursor while the mixedgauge is drawing. The traps cleaned
    up the password file and nothing else, so interrupting `nikos update`
    returned a terminal with no visible cursor. install.sh's _cleanup_install
    pairs the two for this reason; scripts/nikos now does too.
    """
    program = tmp_path / "probe.sh"
    program.write_text(
        "\n\n".join(
            extract_helper(name)
            for name in (
                "_restore_terminal_cursor",
                "_cleanup_become_password_file",
                "_cleanup_run",
            )
        )
        + "\n\n"
        + 'BECOME_PASSWORD_FILE=""\n'
        + "trap '_cleanup_run; exit 130' INT\n"
        # Hide the cursor the way dialog does, then interrupt mid-run.
        + "tput civis 2>/dev/null >/dev/tty\n"
        + "kill -INT $$\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [SCRIPT, "-qec", f"bash {program}", "/dev/null"],
        capture_output=True,
        timeout=60,
    )
    out = result.stdout.decode(errors="replace")

    assert "\x1b[?25l" in out, "the probe never hid the cursor, so it proves nothing"
    assert out.rindex("\x1b[?25h") > out.rindex("\x1b[?25l"), (
        "the interrupt left the cursor hidden"
    )
