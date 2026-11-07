"""Real ansible, through ansible.cfg and plugins/become/nikos_sudo.py, against a
fake sudo on PATH that prints the sudo-rs password prompt:

    [sudo: [sudo via ansible, key=...] password:] Password:

sudo-rs is the default sudo on Ubuntu 26.04. The builtin sudo plugin waits for a
line that starts with its own prompt, never sends the password, and the task
times out; ansible-core fixes this in 2.20.11 and 2.21.6, not in 2.21.5. The fake also answers like
sudo-rs when the password is wrong or missing, and can print the classic sudo
prompt, so the plugin is checked against both.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("ansible") is None, reason="ansible is required")


@functools.lru_cache(maxsize=None)
def core_version() -> tuple[int, int]:
    output = subprocess.run(["ansible", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"core (\d+)\.(\d+)", output)
    assert match, output
    return int(match[1]), int(match[2])


def fails_fast() -> bool:
    """Core 2.19 reworked the local connection: a second prompt or a sudo error
    ends the wait at once. Older cores wait for the become timeout."""
    return core_version() >= (2, 19)


def old_core_env() -> dict:
    # Before core 2.19 the become wait is the connection timeout, 10 s by default;
    # ansible_local_become_success_timeout does not exist there.
    return {} if fails_fast() else {"ANSIBLE_TIMEOUT": "2"}


def sudo_gives_up_after() -> int:
    # A core before 2.19 waits on sudo with no timeout of its own, on a wrong
    # password and after the connection timeout. Real sudo ends that wait with its
    # password timeout, so the fake does too, in seconds. 0 means no limit.
    return 0 if fails_fast() else 4


# Argument parsing covers exactly what the sudo become plugin builds:
# -H -S [-n] [-p PROMPT] -u USER /bin/sh -c '...'.
FAKE_SUDO = """#!{python}
import os, signal, sys
args = sys.argv[1:]
prompt, user, noninteractive, i = None, "root", False, 0
while i < len(args):
    arg = args[i]
    if arg == "-p":
        prompt, i = args[i + 1], i + 2
    elif arg == "-u":
        user, i = args[i + 1], i + 2
    elif arg in ("-H", "-S"):
        i += 1
    elif arg in ("-n", "--non-interactive"):
        noninteractive, i = True, i + 1
    else:
        break
cmd = args[i:]
with open({log!r}, "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if noninteractive:
    sys.stderr.write({missing!r} + "\\n")
    sys.exit(1)
signal.alarm({gives_up_after})
for attempt in range(3):
    sys.stderr.write({prompt_format!r} % prompt)
    sys.stderr.flush()
    if sys.stdin.readline().rstrip("\\n") == {password!r}:
        os.environ["FAKE_SUDO_USER"] = user
        signal.alarm(0)
        os.execvp(cmd[0], cmd)
    sys.stderr.write({fail!r} + "\\n")
sys.exit(1)
"""

SUDO_RS = {
    "prompt_format": "[sudo: %s] Password: ",
    "fail": "sudo: Authentication failed, try again.",
    "missing": "sudo: interactive authentication is required",
}
SUDO_WS = {
    "prompt_format": "%s",
    "fail": "Sorry, try again.",
    "missing": "sudo: a password is required",
}


@pytest.fixture
def fake_sudo(tmp_path: Path):
    """Returns a function that installs the fake sudo and runs ansible against it."""

    # The password the fake sudo accepts; new for every test.
    accepted = secrets.token_urlsafe(12)

    def run(*ansible_args: str, flavour: dict = SUDO_RS, password: str | None = "", env: dict | None = None):
        if password == "":
            password = accepted
        bindir = tmp_path / "bin"
        bindir.mkdir(exist_ok=True)
        log = tmp_path / "sudo.log"
        sudo = bindir / "sudo"
        sudo.write_text(FAKE_SUDO.format(python=sys.executable, log=str(log), password=accepted, gives_up_after=sudo_gives_up_after(), **flavour))
        sudo.chmod(0o755)
        args = ["ansible", "localhost", "-i", "localhost,", "-c", "local", "-b", *ansible_args]
        if password is not None:
            pwfile = tmp_path / "pw"
            pwfile.write_text(password + "\n")
            pwfile.chmod(0o600)
            args += ["--become-password-file", str(pwfile)]
        run_env = {
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "ANSIBLE_CONFIG": str(REPO_ROOT / "ansible.cfg"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_LOCAL_TEMP": str(tmp_path / "tmp"),
            **old_core_env(),
            **(env or {}),
        }
        proc = subprocess.run(args, cwd=tmp_path, env=run_env, capture_output=True, text=True, timeout=120)
        return proc, (log.read_text() if log.exists() else "")

    return run


def test_sudo_rs_prompt_gets_the_password(fake_sudo):
    proc, log = fake_sudo("-m", "ping")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '"ping": "pong"' in proc.stdout
    assert "-p [sudo via ansible, key=" in log
    assert "-n" not in log.split("-p")[0], "the password run must not keep -n"


def test_builtin_sudo_plugin_times_out_on_sudo_rs_prompt(fake_sudo):
    """The reason the plugin exists. Skipped once the installed ansible-core
    accepts the sudo-rs prompt itself (2.20.11, 2.21.6)."""
    proc, _ = fake_sudo(
        "-m", "ping", "-e", "ansible_local_become_success_timeout=2",
        env={"ANSIBLE_BECOME_METHOD": "sudo"},
    )
    if proc.returncode == 0:
        pytest.skip("this ansible-core understands the sudo-rs prompt on its own")
    out = proc.stdout + proc.stderr
    # The second form is core before 2.19.
    assert "Timed out waiting for become success" in out or "waiting for privilege escalation password prompt" in out, out


def test_classic_sudo_prompt_still_works(fake_sudo):
    proc, _ = fake_sudo("-m", "ping", flavour=SUDO_WS)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '"ping": "pong"' in proc.stdout


@pytest.mark.parametrize("flavour", [SUDO_RS, SUDO_WS], ids=["sudo-rs", "sudo"])
def test_wrong_password_fails_at_once_not_at_the_timeout(fake_sudo, flavour):
    """The local connection reports the second prompt, which is how sudo asks
    again, as soon as it is printed. The message is ansible's, not sudo's."""
    proc, _ = fake_sudo("-m", "ping", "-e", "ansible_local_become_success_timeout=30", flavour=flavour, password="not-it")
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    if fails_fast():
        assert "Duplicate become password prompt" in out, out
        assert "Timed out" not in out


def test_no_password_keeps_the_noninteractive_flag(fake_sudo):
    proc, log = fake_sudo("-m", "ping", "-e", "ansible_local_become_success_timeout=30", password=None)
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    if fails_fast():
        assert "interactive authentication is required" in out
        assert "Timed out" not in out
    assert "-n" in log.split()


def test_become_user_reaches_sudo(fake_sudo):
    proc, log = fake_sudo("--become-user", "alice", "-m", "raw", "-a", "true")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "-u alice" in log


def test_stderr_of_the_task_is_kept(fake_sudo):
    """The command's own stderr survives the prompt being stripped."""
    proc, _ = fake_sudo("-m", "command", "-a", "sh -c 'echo task-err >&2'")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "task-err" in proc.stdout


@pytest.fixture
def plugin():
    """The plugin itself, with a known prompt, as when a password is set."""
    pytest.importorskip("ansible")
    spec = importlib.util.spec_from_file_location("nikos_sudo", REPO_ROOT / "plugins/become/nikos_sudo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    become = module.BecomeModule()
    become.prompt = PROMPT
    become.expect_prompt = lambda: True
    return become


PROMPT = "[sudo via ansible, key=abc] password:"


@pytest.mark.parametrize("builtin_knows_sudo_rs", [True, False], ids=["core-builtin", "builtin-stubbed"])
@pytest.mark.parametrize(
    "line, expected",
    [
        (f"[sudo: {PROMPT}] Password: ", True),
        (f"[sudo: {PROMPT}] Passwort:", True),
        (f"other output\n  [sudo: {PROMPT}] Password:", True),
        ("[sudo: [sudo via ansible, key=wrong] password:] Password: ", False),
        (f"before [sudo: {PROMPT}] Password: ", False),
        (f"[sudo: {PROMPT}]", False),
    ],
    ids=["sudo-rs", "localized", "later-line", "wrong-key", "mid-line", "no-word"],
)
def test_check_password_prompt(plugin, monkeypatch, line, expected, builtin_knows_sudo_rs):
    """Stubbed builtin: core 2.20.11 and 2.21.6 accept this line themselves, which
    would hide a plugin that only calls super()."""
    if not builtin_knows_sudo_rs:
        monkeypatch.setattr(type(plugin).__mro__[1], "check_password_prompt", lambda self, b_output: False)
    assert plugin.check_password_prompt(line.encode()) is expected


def test_classic_prompt_goes_through_the_builtin(plugin):
    assert plugin.check_password_prompt(PROMPT.encode() + b" ") is True


@pytest.mark.parametrize(
    "data, expected",
    [
        (f"[sudo: {PROMPT}] Password: ****\ntask-err\n", "task-err\n"),
        (f"noise\n[sudo: {PROMPT}] Password: \ntask-err\n", "task-err\n"),
        (f"{PROMPT} task-err\n", "task-err\n"),
        ("no prompt\n", "no prompt\n"),
    ],
    ids=["sudo-rs-with-stars", "sudo-rs-with-preamble", "classic", "absent"],
)
def test_strip_become_prompt(plugin, data, expected):
    """Stars would show the length of the password."""
    if not fails_fast():
        pytest.skip("core before 2.19 has no strip_become_prompt and never calls it")
    assert plugin.strip_become_prompt(data.encode()) == expected.encode()
