"""install.sh's Ubuntu 22.04 / 24.04 / 26.04 check against the os-release shapes it meets."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parent.parent / "install.sh"


def _funcs() -> str:
    text = INSTALL_SH.read_text(encoding="utf-8")
    out = []
    for name in ("_os_release_value", "_is_supported_ubuntu_system"):
        m = re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.M | re.S)
        assert m, name
        out.append(m.group(0))
    return "\n".join(out)


@pytest.mark.parametrize(
    "content,supported",
    [
        ('NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\n', True),
        ("ID=ubuntu\nVERSION_ID='24.04'\n", True),          # single quotes
        ('ID=ubuntu\nVERSION_ID="24.04" \n', True),          # trailing space
        ('ID="ubuntu"\r\nVERSION_ID="24.04"\r\n', True),     # CRLF
        ('NAME=x\nID=ubuntu\nVERSION_ID="24.04"', True),     # no final newline
        ('ID=ubuntu\nVERSION_ID="22.04"\n', True),
        ('ID=ubuntu\nVERSION_ID="26.04"\n', True),
        ('ID=ubuntu\nVERSION_ID="20.04"\n', False),
        ('ID=ubuntu\nVERSION_ID="25.10"\n', False),
        ('ID=ubuntu\nVERSION_ID="24.04.1"\n', False),
        ('ID=debian\nVERSION_ID="12"\n', False),
        ('ID=debian\nVERSION_ID="24.04"\n', False),
        ("", False),
    ],
    ids=["plain", "single-quotes", "trailing-space", "crlf", "no-final-newline",
         "22.04", "26.04", "20.04", "25.10", "24.04.1", "debian", "debian-24.04", "empty"],
)
def test_supported_system(tmp_path, content, supported):
    osr = tmp_path / "os-release"
    osr.write_bytes(content.encode())
    result = subprocess.run(
        ["bash", "-c", _funcs() + "\n_is_supported_ubuntu_system && echo YES || echo NO"],
        capture_output=True, text=True, env={"NIKOS_OS_RELEASE_FILE": str(osr), "PATH": "/usr/bin:/bin"},
    )
    assert result.stdout.strip() == ("YES" if supported else "NO"), result.stderr


def test_the_error_says_what_it_found():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "found: ${_found_os}" in text


def _run_installer_to_the_os_check(tmp_path, content: str) -> tuple[int, str]:
    """install.sh up to the system check: a PATH with the tools the preamble
    uses and no apt-get, so the check refuses every release and the installer
    stops there, after it has written the log."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("bash", "date", "mkdir", "ln", "readlink", "dirname", "basename", "sed", "grep",
                 "cat", "tput", "id", "hostname", "head", "tail", "sort", "tr", "awk", "cut",
                 "rm", "mktemp", "chmod", "touch", "wc", "printf", "env"):
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    osr = tmp_path / "os-release"
    osr.write_text(content, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["bash", str(INSTALL_SH)], capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env={"HOME": str(home), "PATH": str(bindir), "TERM": "xterm", "NIKOS_USE_DIALOG": "0",
             "NIKOS_OS_RELEASE_FILE": str(osr)}, timeout=60,
    )
    log = (home / ".config/nikos/logs/install-latest.log").read_text(encoding="utf-8")
    return result.returncode, log


@pytest.mark.parametrize(
    "content,expected",
    [
        ('PRETTY_NAME="Ubuntu 26.04 LTS"\nID=ubuntu\nVERSION_ID="26.04"\nVERSION_CODENAME=resolute\n'
         "UBUNTU_CODENAME=resolute\n",
         "OS: ID=ubuntu VERSION_ID=26.04 VERSION_CODENAME=resolute PRETTY_NAME=Ubuntu 26.04 LTS"),
        # No VERSION_CODENAME: UBUNTU_CODENAME stands in.
        ('ID=ubuntu\nVERSION_ID="24.04"\nUBUNTU_CODENAME=noble\nPRETTY_NAME="Ubuntu 24.04.3 LTS"\n',
         "OS: ID=ubuntu VERSION_ID=24.04 VERSION_CODENAME=noble PRETTY_NAME=Ubuntu 24.04.3 LTS"),
        # A refused release is logged too, with ? for what is missing.
        ('ID=debian\nVERSION_ID="13"\n',
         "OS: ID=debian VERSION_ID=13 VERSION_CODENAME=? PRETTY_NAME=?"),
    ],
    ids=["26.04", "ubuntu-codename-fallback", "debian"],
)
def test_the_install_log_records_the_os_release_keys(tmp_path, content, expected):
    rc, log = _run_installer_to_the_os_check(tmp_path, content)
    assert rc == 1
    os_lines = [l for l in log.splitlines() if "] OS: " in l]
    assert len(os_lines) == 1, log
    assert os_lines[0].endswith(expected), log
    # Before the verdict, so a refused release has its line too.
    assert log.index("] OS: ") > log.index("Mode: "), log
