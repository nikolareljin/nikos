"""Guards on the installer's terminal test and on the plain selection path.

Two defect classes, both invisible on an interactive machine and both reported
against the install path the README leads with, `curl ... | bash`.

**A terminal test that asks about stdin.** `_can_use_dialog` required
`[[ -t 0 ]]`. Under `curl ... | bash` bash reads the script itself from stdin,
so that is false by construction - there is no machine on which the documented
one-liner could pass it. Everything behind the gate was skipped, including the
playbook, and the install fell back to raw Ansible output (#52). What decides
whether curses can draw is the controlling terminal, `/dev/tty`, not whatever
stdin happens to be attached to.

**A function that returns its answer on the channel it prints its prose to.**
`_select_bundles_plain` echoed its section headers to stdout and returned the
selection there too; the caller captured the lot with
`read -ra ... <<< "$(...)"`, which reads one line of a multi-line here-string.
The array was filled with the words of a header, so a selected bundle never
reached the tag list and the role never ran - while the install exited 0 and
logged the corrupted array as if it were the answer (#53).

Note on the harness. `script -qec 'bash prog'` gives the child a pty on *all*
three descriptors, so `-t 0` is true there and the unfixed gate passes: that
shape proves nothing. The pipe has to be on bash's own stdin, which is what
`script -qec 'cat prog | bash'` reproduces - literally `curl ... | bash`.
`tests/` had no coverage of any of this, and `./test` cannot provide it: it
drives the installer over `ssh -tt`, so a pty is always allocated and only the
clone-and-run path is ever exercised.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"

GATE_HELPERS = ("_have_tty", "_can_use_dialog")
SELECTION_HELPERS = (
    "_have_tty",
    "_say_tty",
    "_ask_tty",
    "_require_tty_for_selection",
    "_select_bundles_plain",
    "_select_ai_tools_plain",
    "_build_tag_args",
)

needs_pty = pytest.mark.skipif(
    shutil.which("script") is None, reason="util-linux `script` is required"
)
needs_setsid = pytest.mark.skipif(
    shutil.which("setsid") is None, reason="util-linux `setsid` is required"
)


def extract_helper(name: str) -> str:
    """Pull a bash function out of install.sh so it can be run on its own."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"install.sh no longer defines {name}"
    return match.group(0)


def extract_selection_dispatch() -> str:
    """Pull the branch that actually calls the plain selectors.

    The defect lived in the wiring, not in either half on its own: the function
    printed prose and result to one channel, and the caller captured it with a
    single-line read. A test that only drove the functions would pass while the
    caller threw the answers away, so the real dispatch is what runs here.
    """
    text = INSTALL_SH.read_text(encoding="utf-8")
    start = text.index("if _can_use_dialog; then", text.index("_select_ai_tools_plain() {"))
    end = text.index("\n# Timezone", start)
    return text[start:end]


def write_program(tmp_path: Path, helpers: tuple[str, ...], body: str) -> Path:
    program = tmp_path / "probe.sh"
    program.write_text(
        "\n\n".join(extract_helper(name) for name in helpers)
        + "\n\n"
        + textwrap.dedent(body),
        encoding="utf-8",
    )
    return program


def stub_dialog(tmp_path: Path) -> Path:
    """A `dialog` on PATH, so the suite needs no package installed."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "dialog"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    return bindir


BASH = shutil.which("bash") or "/bin/bash"
SCRIPT = shutil.which("script") or "/usr/bin/script"


def run(argv: list[str], *, path: str, stdin: bytes = b"", home: Path) -> str:
    result = subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        timeout=60,
        env={"PATH": path, "TERM": "xterm", "HOME": str(home)},
    )
    return result.stdout.decode(errors="replace").replace("\r", "")


def with_stub(bindir: Path) -> str:
    return f"{bindir}:/usr/bin:/bin"


GATE_BODY = """
    USE_DIALOG="${NIKOS_USE_DIALOG:-1}"
    if _can_use_dialog; then echo GATE=pass; else echo GATE=fail; fi
"""


@needs_pty
def test_gate_passes_with_piped_stdin_and_a_real_terminal(tmp_path):
    """The regression: `curl ... | bash` has a terminal, just not on stdin."""
    program = write_program(tmp_path, GATE_HELPERS, GATE_BODY)
    bindir = stub_dialog(tmp_path)
    out = run(
        ["script", "-qec", f"cat {program} | bash", "/dev/null"],
        path=with_stub(bindir),
        home=tmp_path,
    )
    assert "GATE=pass" in out, out


@needs_setsid
def test_gate_fails_without_a_controlling_terminal(tmp_path):
    program = write_program(tmp_path, GATE_HELPERS, GATE_BODY)
    bindir = stub_dialog(tmp_path)
    out = run(
        ["setsid", "bash", str(program)], path=with_stub(bindir), home=tmp_path
    )
    assert "GATE=fail" in out, out


@needs_pty
def test_gate_fails_when_dialog_is_switched_off(tmp_path):
    program = write_program(tmp_path, GATE_HELPERS, GATE_BODY)
    bindir = stub_dialog(tmp_path)
    out = run(
        [
            "script",
            "-qec",
            f"NIKOS_USE_DIALOG=0 bash {program}",
            "/dev/null",
        ],
        path=with_stub(bindir),
        home=tmp_path,
    )
    assert "GATE=fail" in out, out


@needs_pty
def test_gate_fails_when_dialog_is_absent(tmp_path):
    """PATH holds no dialog at all, so bash is named absolutely."""
    program = write_program(tmp_path, GATE_HELPERS, GATE_BODY)
    empty = tmp_path / "empty"
    empty.mkdir()
    out = run(
        [SCRIPT, "-qec", f"{BASH} {program}", "/dev/null"],
        path=str(empty),
        home=tmp_path,
    )
    assert "GATE=fail" in out, out


# One `y` per bundle prompt, in the order _select_bundles_plain asks them, then
# the AI-tool prompts. Only BitNet is wanted, and only Claude Code is declined.
BUNDLE_ANSWERS = ["n"] * 19
BUNDLE_ANSWERS[9] = "y"  # "Install BitNet.cpp?"
AI_ANSWERS = ["", "", "n", "", "", ""]  # Claude Code declined, rest defaulted

SELECTION_BODY = """
    _safe_logfile() { :; }
    # Force the branch a machine without `dialog` takes.
    _can_use_dialog() { return 1; }

__SELECTION_DISPATCH__

    _build_tag_args
    printf '\\nBUNDLES=%s\\n' "${SELECTED_BUNDLES[*]}"
    printf 'AI=%s\\n' "${SELECTED_AI_TOOLS[*]}"
    printf 'EXPLICIT=%s\\n' "${EXPLICIT_OPTIONAL_TAGS#,}"
    printf 'SKIP=%s\\n' "${SKIP_TAGS#,}"
"""


def field(out: str, name: str) -> str:
    match = re.search(rf"^{name}=(.*)$", out, re.M)
    assert match, f"{name} missing from:\n{out}"
    return match.group(1).strip()


@needs_pty
def test_plain_selection_round_trips_the_answers(tmp_path):
    """What was answered is what reaches the tags - the whole of #53."""
    body = SELECTION_BODY.replace(
        "__SELECTION_DISPATCH__", extract_selection_dispatch()
    )
    program = write_program(tmp_path, SELECTION_HELPERS, body)
    bindir = stub_dialog(tmp_path)
    answers = "\n".join(BUNDLE_ANSWERS + AI_ANSWERS) + "\n"
    out = run(
        ["script", "-qec", f"bash {program} < /dev/null", "/dev/null"],
        path=with_stub(bindir),
        stdin=answers.encode(),
        home=tmp_path,
    )

    assert field(out, "BUNDLES") == "bitnet"
    assert field(out, "EXPLICIT") == "bitnet"

    ai = field(out, "AI").split()
    assert "ai-claude" not in ai
    assert "ai-local" in ai and "ai-vscode" in ai

    skip = field(out, "SKIP").split(",")
    assert "ai-claude" in skip, skip
    # The bundles nobody asked for are skipped; the one that was asked for is not.
    assert {"network", "music", "education"} <= set(skip), skip
    assert "bitnet" not in skip, skip


TIMEZONE_HELPERS = ("_say_tty", "_ask_tty", "_select_timezone_plain")

TIMEZONE_BODY = """
    _chosen_tz=""
    _select_timezone_plain "America/New_York" ""
    printf '\nTZ=[%s]\n' "${_chosen_tz}"
    printf 'TZ_LINES=%s\n' "$(printf %s "${_chosen_tz}" | grep -c '' )"
"""


@needs_pty
@pytest.mark.parametrize(
    "answer,expected",
    [("1", "America/New_York"), ("", "America/New_York"), ("2\nAsia/Tokyo", "Asia/Tokyo")],
    ids=["explicit-auto", "defaulted", "custom"],
)
def test_plain_timezone_returns_only_the_timezone(tmp_path, answer, expected):
    """The same class again: the menu and the answer must not share a channel.

    `_select_timezone_plain` printed its menu to stdout and the caller captured
    the lot with `_chosen_tz=$(...)`, so `NIKOS_USE_DIALOG=0` wrote five lines of
    menu text into vars/local.yml as the timezone. Measured on the unfixed
    version: the capture was 5 lines long.
    """
    program = write_program(tmp_path, TIMEZONE_HELPERS, TIMEZONE_BODY)
    bindir = stub_dialog(tmp_path)
    out = run(
        ["script", "-qec", f"bash {program} < /dev/null", "/dev/null"],
        path=with_stub(bindir),
        stdin=(answer + "\n").encode(),
        home=tmp_path,
    )

    assert field(out, "TZ") == f"[{expected}]", out
    assert field(out, "TZ_LINES") == "1", "the menu leaked into the captured value"


DIALOG_CANCEL_HELPERS = {
    "_collect_become_password_dialog": "_collect_become_password_dialog",
    "_select_timezone_dialog": '_select_timezone_dialog "America/New_York" ""',
}


@needs_pty
@pytest.mark.parametrize("helper,call", DIALOG_CANCEL_HELPERS.items())
def test_a_cancelled_dialog_is_not_reported_as_success(tmp_path, helper, call):
    """Cancel and Esc must reach the caller as a failure.

    `if ! var=$(dialog ...); then return $?; fi` returns the status of the `!`,
    which is 0 - so a cancelled dialog reported success. The caller then took the
    empty output for an answer: an empty sudo password handed to ansible, or an
    empty timezone written to vars/local.yml. Measured on the unfixed version:
    `f(){ if ! x=$(exit 3); then return $?; fi; }` returns 0.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    cancelled = bindir / "dialog"
    # dialog exits 1 on Cancel, 255 on Esc; 1 is enough to show the shape.
    cancelled.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    cancelled.chmod(0o755)

    program = write_program(
        tmp_path,
        (helper,),
        f"""
    DIALOG_HEIGHT=20
    DIALOG_WIDTH=72
    NIKOS_VERSION=test
    if out=$({call}); then
      echo "STATUS=success out=[${{out}}]"
    else
      echo "STATUS=cancelled rc=$?"
    fi
""",
    )
    out = run(
        ["script", "-qec", f"bash {program} < /dev/null", "/dev/null"],
        path=f"{bindir}:/usr/bin:/bin",
        home=tmp_path,
    )
    assert "STATUS=cancelled" in out, out


@needs_pty
def test_input_ending_mid_prompt_is_not_treated_as_an_answer(tmp_path):
    """EOF is not a 'no'.

    `read ... || __ask_answer=""` turned a failed read into an empty answer,
    which silently declines the bundle being asked about and accepts any
    default-enabled AI tool - the exact behaviour this path was changed to stop.
    """
    program = write_program(
        tmp_path,
        ("_say_tty", "_ask_tty"),
        """
    _safe_logfile() { :; }
    NIKOS_HOME="${HOME}/.local/share/nikos"
    answer="unset"
    _ask_tty answer "  Install something? [y/N] "
    echo "REACHED=yes answer=[${answer}]"
""",
    )
    bindir = stub_dialog(tmp_path)
    # No answers at all: the read hits EOF immediately.
    out = run(
        ["script", "-qec", f"bash {program} < /dev/null", "/dev/null"],
        path=with_stub(bindir),
        stdin=b"",
        home=tmp_path,
    )
    assert "REACHED=yes" not in out, out
    assert "input ended while NikOS was waiting" in out, out
    # The message must not overstate what was undone: by this point the
    # bootstrap packages, the checkout and the collections are already in place.
    assert "Nothing was installed" not in out, out
    assert "The playbook was not run" in out, out
