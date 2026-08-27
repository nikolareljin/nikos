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

Every step is now checked on its own, and the file is only published to
BECOME_PASSWORD_FILE once it actually holds the password.
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


def test_falls_back_without_aborting_when_the_file_cannot_be_created(tmp_path):
    """errexit is suspended in the caller's `&&`, so this must return, not drift on."""
    out = run(
        write_program(tmp_path), tmp_path, tmpdir="/nonexistent-nikos-tmpdir"
    )

    assert "RESULT=fallback" in out, out
    assert "published=[]" in out, out
    assert "REACHED_END=yes" in out, out
