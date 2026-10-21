"""Interactive `nikos` commands render the compact terminal header."""

import os
import pty
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts" / "nikos"


def run_on_terminal(
    *args: str, no_color: bool = False, term: str = "xterm-256color"
) -> tuple[int, bytes]:
    env = {**os.environ, "TERM": term, "NIKOS_HOME": str(ROOT)}
    if no_color:
        env["NO_COLOR"] = "1"
    else:
        env.pop("NO_COLOR", None)

    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("bash", ["bash", str(CLI), *args], env)

    output = b""
    try:
        while chunk := os.read(fd, 4096):
            output += chunk
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), output


def test_help_renders_the_exact_terminal_logo_palette():
    returncode, output = run_on_terminal("--help")

    assert returncode == 0
    assert b"NikOS" in output
    assert b"Neural Innovation for Knowledge OS" in output
    assert b"https://nikolareljin.github.io/nikos" in output
    assert b"Usage:" in output
    assert b"\x1b[38;2;144;164;174m" in output
    assert b"\x1b[38;2;255;255;255m" in output
    assert b"\x1b[1;38;2;33;150;243m" in output
    assert b"\x1b[1;38;2;144;164;174m" in output
    assert "┌".encode() in output
    assert "┃╲".encode() in output
    assert b"\x1b[0;34m" not in output
    assert b"\x1b[0;90m" not in output
    assert b"\x1b[0;37m" not in output


def test_no_color_keeps_the_interactive_logo_readable():
    returncode, output = run_on_terminal("--help", no_color=True)

    assert returncode == 0
    assert b"NikOS" in output
    header, _, _ = output.partition(b"Usage:")
    assert b"https://nikolareljin.github.io/nikos" in header
    assert b"\x1b[" not in header
    assert header.count("●".encode()) == 4
    assert "┌".encode() in header
    assert "└".encode() in header
    assert "┃".encode() in header
    assert "│".encode() in header
    assert "╲".encode() in header


def test_dumb_terminal_skips_the_logo():
    returncode, output = run_on_terminal("--help", term="dumb")

    assert returncode == 0
    assert output.startswith(b"nikos ")
    assert "●".encode() not in output


def test_command_errors_keep_the_terminal_header():
    returncode, output = run_on_terminal("not-a-command")

    assert returncode == 1
    assert b"Neural Innovation for Knowledge OS" in output
    assert b"Unknown command: not-a-command" in output


def test_piped_help_does_not_include_the_terminal_header():
    env = {**os.environ, "TERM": "xterm-256color", "NIKOS_HOME": str(ROOT)}
    result = subprocess.run(
        ["bash", str(CLI), "--help"], env=env, capture_output=True, text=True, check=True
    )

    assert result.stdout.startswith("nikos ")
