"""The command table in scripts/nikos, the usage it prints and the menu bare
`nikos` opens on a terminal.

The menu test runs the real CLI in a pty with a stub `dialog` on PATH that
picks `status` once, then Exit.
"""

import os
import pty
import re
import select
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "nikos"
TEXT = SCRIPT.read_text(encoding="utf-8")


def table_commands() -> set[str]:
    block = TEXT[TEXT.index("NIKOS_COMMANDS=(") : TEXT.index("\n)\n", TEXT.index("NIKOS_COMMANDS=("))]
    return set(re.findall(r'^\s+"([^;"]+);', block, re.M))


def dispatch_commands() -> set[str]:
    start = TEXT.index('case "${1}" in\n')
    block = TEXT[start : TEXT.index("\nesac\n", start)]
    names = set()
    for labels in re.findall(r"^  ([^\s(][^)]*)\)", block, re.M):
        names.update(label.strip() for label in labels.split("|"))
    return names - {"*", "--help", "-h"}


def test_every_dispatched_command_is_in_the_table():
    dispatched = dispatch_commands()
    assert {"setup", "update", "status", "hooks", "help"} <= dispatched
    assert dispatched - table_commands() == set()


def test_every_table_command_is_dispatched():
    assert table_commands() - dispatch_commands() == set()


def test_piped_stdin_prints_usage_and_exits_0():
    r = subprocess.run(["bash", str(SCRIPT)], input="", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "Usage:" in r.stdout
    assert "nikos update --ref <r>" in r.stdout
    assert "nikos hooks export|import DIR" in r.stdout


def test_dialog_off_prints_usage_on_a_terminal(tmp_path):
    out, rc = run_in_pty(tmp_path, {"NIKOS_USE_DIALOG": "0"}, menu_script="exit 1")
    assert rc == 0
    assert "Usage:" in out
    assert not (tmp_path / "dialog.log").exists()


def run_in_pty(tmp_path, extra_env, menu_script):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "dialog.log"
    fake = bindir / "dialog"
    fake.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'case " $* " in\n'
        f"  *' --menu '*) {menu_script} ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "TERM": "xterm",
        "NO_COLOR": "1",
        "OLLAMA_HOST": "http://127.0.0.1:9",
        **extra_env,
    }
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("bash", ["bash", str(SCRIPT)], env)
    out = b""
    deadline = time.time() + 60
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if b"Press Enter to return to the menu" in chunk or out.endswith(b"menu. "):
            os.write(fd, b"\n")
    _, status = os.waitpid(pid, 0)
    return out.decode(errors="replace"), os.waitstatus_to_exitcode(status)


def test_bare_nikos_on_a_terminal_opens_the_menu_and_runs_status(tmp_path):
    # First menu call picks the item labelled "status: ...", the second exits.
    pick = (
        f'if [[ -e "{tmp_path}/picked" ]]; then exit 1; fi; touch "{tmp_path}/picked"; '
        'prev=""; for a in "$@"; do if [[ "$a" == status:* ]]; then echo "$prev"; exit 0; fi; prev="$a"; done; exit 1'
    )
    out, rc = run_in_pty(tmp_path, {}, menu_script=pick)
    assert rc == 0, out
    calls = (tmp_path / "dialog.log").read_text().splitlines()
    assert sum(" --menu " in f" {c} " for c in calls) == 2
    assert not any("--yesno" in c for c in calls)  # status changes nothing
    assert "Ollama models:" in out
    assert "[nikos status finished, exit 0]" in out
