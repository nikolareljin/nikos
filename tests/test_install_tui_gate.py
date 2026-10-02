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
BUNDLE_ANSWERS = ["n"] * 20
BUNDLE_ANSWERS[9] = "y"  # "Install BitNet.cpp?"
# Claude Code declined, Jev (default No) picked, rest defaulted.
AI_ANSWERS = ["", "", "n", "", "", "", "y"]

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
    # Jev is offered with the AI tools but is opt-in like a bundle: a `never`
    # tag that runs only when picked, never a skip tag an old machine lacks.
    assert field(out, "EXPLICIT") == "bitnet,jev"

    ai = field(out, "AI").split()
    assert "ai-claude" not in ai
    assert "ai-local" in ai and "ai-vscode" in ai

    skip = field(out, "SKIP").split(",")
    assert "ai-claude" in skip, skip
    # The bundles nobody asked for are skipped; the one that was asked for is not.
    assert {"network", "music", "education"} <= set(skip), skip
    assert "bitnet" not in skip, skip
    assert "jev" not in skip, skip


def test_jev_defaults_to_no_in_the_plain_picker():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert '[[ "${opt_jev,,}" == "y" ]] && SELECTED_AI_TOOLS+=("jev")' in text
    assert '"jev"             "Jev client (official TypeSafe SDK, your own API key)" off' in text


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


# ---------------------------------------------------------------------------
# Why the gauge falls back, and the causes behind the fallback.
#
# On some machines `nikos update` and the installer printed raw `TASK [...]`
# output with no explanation. Three causes: a passwordless-sudo user pressing
# Enter at the password prompt fell to --ask-become-pass; `--list-tasks`
# inherited a non-blocking tty as stdin, which ansible-core refuses ("requires
# blocking IO"), and its stderr was thrown away; and nothing said which.
# ---------------------------------------------------------------------------

PROGRESS_LIB = REPO_ROOT / "scripts" / "nikos-progress.sh"
NIKOS_CLI = REPO_ROOT / "scripts" / "nikos"


def stub(bindir: Path, name: str, body: str) -> None:
    bindir.mkdir(exist_ok=True)
    path = bindir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def progress_program(tmp_path: Path, body: str) -> Path:
    program = tmp_path / "progress.sh"
    program.write_text(f"source {PROGRESS_LIB}\n" + textwrap.dedent(body), encoding="utf-8")
    return program


WHY_BODY = """
    {setup}
    printf '\\nWHY=[%s]\\n' "$(nikos_progress_why_not)"
"""


@needs_pty
@pytest.mark.parametrize(
    "env,setup,expected",
    [
        ("NIKOS_USE_DIALOG=0 ", "", "NIKOS_USE_DIALOG=0"),
        ("", 'NIKOS_PROGRESS_SKIP_REASON="empty sudo password"', "empty sudo password"),
        ("", 'NIKOS_PROGRESS_PLAN_FAILED=1; NIKOS_PROGRESS_PLAN_ERR="ERROR: boom"',
         "task listing failed: ERROR: boom"),
    ],
    ids=["switched-off", "empty-password", "listing-failed"],
)
def test_why_not_names_the_reason(tmp_path, env, setup, expected):
    program = progress_program(tmp_path, WHY_BODY.format(setup=setup))
    bindir = stub_dialog(tmp_path)
    out = run(
        ["script", "-qec", f"{env}bash {program} < /dev/null", "/dev/null"],
        path=with_stub(bindir),
        home=tmp_path,
    )
    assert field(out, "WHY") == f"[{expected}]", out


@needs_pty
def test_why_not_says_dialog_is_missing(tmp_path):
    program = progress_program(tmp_path, WHY_BODY.format(setup=""))
    empty = tmp_path / "empty"
    empty.mkdir()
    out = run(
        [SCRIPT, "-qec", f"{BASH} {program} < /dev/null", "/dev/null"],
        path=str(empty),
        home=tmp_path,
    )
    assert field(out, "WHY") == "[dialog not installed]", out


@needs_setsid
def test_why_not_says_there_is_no_terminal(tmp_path):
    program = progress_program(tmp_path, WHY_BODY.format(setup=""))
    bindir = stub_dialog(tmp_path)
    out = run(["setsid", "bash", str(program)], path=with_stub(bindir), home=tmp_path)
    assert field(out, "WHY") == "[no controlling terminal /dev/tty]", out


PLAN_BODY = """
    if nikos_progress_plan "$HOME" /dev/null site.yml; then rc=0; else rc=1; fi
    printf '\\nRC=%s\\nTOTAL=%s\\n' "$rc" "$NIKOS_PROGRESS_TOTAL"
    printf 'ERR=[%s]\\n' "$NIKOS_PROGRESS_PLAN_ERR"
"""


@needs_pty
def test_planner_keeps_the_ansible_error(tmp_path):
    bindir = stub_dialog(tmp_path)
    stub(
        bindir,
        "ansible-playbook",
        'echo "[DEPRECATION WARNING]: old thing" >&2\n'
        'echo "ERROR: Ansible requires blocking IO on stdin/stdout/stderr." >&2\n'
        "exit 1\n",
    )
    program = progress_program(tmp_path, PLAN_BODY)
    out = run(
        ["script", "-qec", f"bash {program} < /dev/null", "/dev/null"],
        path=with_stub(bindir),
        home=tmp_path,
    )
    assert field(out, "RC") == "1", out
    assert field(out, "ERR") == "[ERROR: Ansible requires blocking IO on stdin/stdout/stderr.]", out


@needs_pty
def test_planner_does_not_hand_ansible_the_terminal(tmp_path):
    """The program itself runs with the pty on stdin; the planner must not pass it on."""
    bindir = stub_dialog(tmp_path)
    stub(
        bindir,
        "ansible-playbook",
        'if [ -t 0 ]; then echo "ERROR: stdin is a terminal" >&2; exit 1; fi\n'
        "printf '  play #1 (localhost): x\\tTAGS: []\\n    tasks:\\n"
        "      base : one\\tTAGS: []\\n      base : two\\tTAGS: []\\n'\n",
    )
    program = progress_program(tmp_path, PLAN_BODY)
    out = run(
        ["script", "-qec", f"bash {program}", "/dev/null"],
        path=with_stub(bindir),
        home=tmp_path,
    )
    assert field(out, "RC") == "0", out
    assert field(out, "TOTAL") == "2", out


def extract_cli_block(start: str, end: str) -> str:
    text = NIKOS_CLI.read_text(encoding="utf-8")
    i = text.index(start)
    return text[i : text.index(end, i) + len(end)]


def extract_cli_helper(name: str) -> str:
    text = NIKOS_CLI.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"scripts/nikos no longer defines {name}"
    return match.group(0)


GAUGE_CHOICE_BODY = """
    USE_DIALOG=1
    _PROGRESS_LIB_LOADED=true
    BECOME_PASSWORD_FILE=""
    use_gauge=false
    playbook_args=(-i inv site.yml)
    _can_use_gauge() {{ return 0; }}
    _offer_dialog_install() {{ :; }}
    _logfile() {{ :; }}
    print_info() {{ echo "$*"; }}
    nikos_progress_why_not() {{ echo "${{NIKOS_PROGRESS_SKIP_REASON}}"; }}
    _collect_become_password() {{ echo COLLECTED; {collect}; }}
    {block}
    printf '\\nGAUGE=%s\\nARGS=%s\\nASK=%s\\n' "$use_gauge" "${{playbook_args[*]}}" "$ask_pass"
"""


@pytest.mark.parametrize("sudo_rc", [0, 1], ids=["passwordless", "needs-password"])
def test_update_gauge_choice(tmp_path, sudo_rc):
    """Passwordless sudo goes straight to the gauge, no prompt, no --ask-become-pass."""
    block = extract_cli_block("  local ask_pass=false", "    _plain_view_notice\n  fi\n")
    body = GAUGE_CHOICE_BODY.format(
        block=block,
        collect='NIKOS_PROGRESS_SKIP_REASON="empty sudo password"; return 1',
    )
    program = tmp_path / "choice.sh"
    program.write_text(
        extract_cli_helper("_plain_view_notice") + "\n" + textwrap.dedent(body)
        .replace("local ask_pass", "ask_pass"),
        encoding="utf-8",
    )
    bindir = tmp_path / "bin"
    stub(bindir, "sudo", f'echo "SUDO $*" >> {tmp_path}/sudo.log\nexit {sudo_rc}\n')
    out = run(["bash", str(program)], path=with_stub(bindir), home=tmp_path)
    if sudo_rc == 0:
        assert field(out, "GAUGE") == "true", out
        assert "--ask-become-pass" not in field(out, "ARGS"), out
        assert "--become-password-file" not in field(out, "ARGS"), out
        assert "COLLECTED" not in out, out
        # Without -k a cached timestamp from an earlier sudo passes the probe
        # for a user who does need a password.
        assert (tmp_path / "sudo.log").read_text().split("\n")[0] == "SUDO -n -k true"
    else:
        assert field(out, "GAUGE") == "false", out
        assert "--ask-become-pass" in field(out, "ARGS"), out
        assert "Plain progress view: empty sudo password" in out, out


@needs_pty
@pytest.mark.parametrize(
    "answers,expected",
    [
        ("wrong\nright\n", "OK"),
        ("wrong\nwrong\nwrong\n", "FAIL sudo password rejected 3 times"),
        ("\n", "FAIL empty sudo password"),
    ],
    ids=["second-try", "three-strikes", "empty"],
)
def test_sudo_password_is_validated_on_stdin(tmp_path, answers, expected):
    bindir = stub_dialog(tmp_path)
    log = tmp_path / "sudo.log"
    # Accepts "right" on stdin; records argv so a password there would show.
    stub(bindir, "sudo", f'echo "ARGV $*" >> {log}\nread pw; [ "$pw" = right ]\n')
    program = tmp_path / "collect.sh"
    program.write_text(
        "\n".join(
            extract_cli_helper(n)
            for n in ("_cleanup_become_password_file", "_collect_become_password")
        )
        + textwrap.dedent(
            """
            print_error() { echo "$*" >&2; }
            BECOME_PASSWORD_FILE=""
            NIKOS_PROGRESS_SKIP_REASON=""
            if _collect_become_password; then
              printf '\\nRESULT=OK\\nFILE=%s\\n' "$(cat "$BECOME_PASSWORD_FILE")"
              _cleanup_become_password_file
            else
              printf '\\nRESULT=FAIL %s\\n' "$NIKOS_PROGRESS_SKIP_REASON"
            fi
            """
        ),
        encoding="utf-8",
    )
    out = run(
        ["script", "-qec", f"bash {program} < /dev/null", "/dev/null"],
        path=with_stub(bindir),
        stdin=answers.encode(),
        home=tmp_path,
    )
    assert field(out, "RESULT") == expected, out
    if expected == "OK":
        assert field(out, "FILE") == "right", out
    if log.exists():
        assert "right" not in log.read_text() and "wrong" not in log.read_text()


# install.sh checks the sudo password before the playbook starts. A wrong one
# used to surface only when the first become task failed, minutes in.
CHECKED_PW_BODY = """
    NIKOS_VERSION=test
    # Runs in $(...), so the answer index lives in a file, not a variable.
    _collect_become_password_dialog() {
      echo x >>"$HOME/asked"
      printf '%s\\n' "$(printf '%s' "$PW_ANSWERS" | cut -d, -f"$(wc -l <"$HOME/asked")")"
    }
    rc=0
    _collect_checked_become_password || rc=$?
    echo "RC=${rc} PW=${_become_pass}"
    echo "ASKED=$(wc -l <"$HOME/asked" 2>/dev/null || echo 0)"
"""

# Stub sudo: "-n" succeeds only when NOPASSWD=1; "-S" accepts the password "good".
SUDO_STUB = """
echo "$*" >>"$HOME/sudo-args"
case " $* " in
  *" -n "*) [ "${NOPASSWD:-0}" = 1 ] ;;
  *" -S "*) read -r pw; [ "$pw" = good ] ;;
  *) exit 1 ;;
esac
"""


def _checked_pw(tmp_path, answers, nopasswd="0"):
    bindir = stub_dialog(tmp_path)
    stub(bindir, "sudo", SUDO_STUB)
    program = write_program(tmp_path, ("_collect_checked_become_password",), CHECKED_PW_BODY)
    result = subprocess.run(
        [BASH, str(program)], capture_output=True, timeout=60,
        env={"PATH": with_stub(bindir), "HOME": str(tmp_path), "PW_ANSWERS": answers,
             "NOPASSWD": nopasswd},
    )
    out = result.stdout.decode()
    args = (tmp_path / "sudo-args").read_text() if (tmp_path / "sudo-args").exists() else ""
    return out, args


def test_install_skips_the_prompt_for_passwordless_sudo(tmp_path):
    out, args = _checked_pw(tmp_path, "unused,", nopasswd="1")
    assert "RC=0 PW=" in out and "ASKED=0" in out, out
    assert "-n -k true" in args


def test_install_retries_a_rejected_password(tmp_path):
    out, args = _checked_pw(tmp_path, "bad,good,")
    assert "RC=0 PW=good" in out and "ASKED=2" in out, out
    assert "good" not in args and "bad" not in args


def test_install_stops_after_three_rejections(tmp_path):
    out, _ = _checked_pw(tmp_path, "a,b,c,good,")
    assert "RC=1 PW=" in out and "ASKED=3" in out, out


def test_the_progressbox_caption_names_the_fallback_reason():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert '--progressbox "Running Ansible playbook (plain view: ${_PLAIN_REASON})..."' in text


def test_update_stops_after_three_rejected_passwords(tmp_path):
    """A fourth try through --ask-become-pass would only repeat the rejection."""
    block = extract_cli_block("  local ask_pass=false", "    _plain_view_notice\n  fi\n")
    body = GAUGE_CHOICE_BODY.format(
        block="choose() {\n" + block + "\n  echo REACHED_PLAY\n}\nchoose; echo \"RC=$?\"",
        collect='NIKOS_PROGRESS_SKIP_REASON="sudo password rejected 3 times"; return 2',
    )
    program = tmp_path / "choice.sh"
    program.write_text(
        extract_cli_helper("_plain_view_notice") + "\n"
        + textwrap.dedent(body).replace(
            "print_info() {", "print_error() { echo \"ERR $*\"; }\nprint_info() {", 1),
        encoding="utf-8",
    )
    bindir = tmp_path / "bin"
    stub(bindir, "sudo", "exit 1\n")
    out = run(["bash", str(program)], path=with_stub(bindir), home=tmp_path)
    assert "RC=1" in out and "REACHED_PLAY" not in out, out
    assert "ERR Sudo rejected the password three times" in out, out
    assert "--ask-become-pass" not in field(out, "ARGS"), out
