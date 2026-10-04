"""install.sh's Ubuntu 22.04 / 24.04 / 26.04 check against the os-release shapes it meets."""
import re
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
