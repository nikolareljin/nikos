"""`nikos doctor` names the release it runs on and warns, without failing,
outside the supported Ubuntu list."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_profiles import NIKOS_CLI, _fake_home

REPO = Path(__file__).resolve().parent.parent


def _doctor(tmp_path: Path, os_release: str | None) -> str:
    home = _fake_home(tmp_path, "server")
    env = dict(os.environ, NIKOS_HOME=str(home), HOME=str(tmp_path), PATH="/usr/bin:/bin")
    if os_release is None:
        env["NIKOS_OS_RELEASE_FILE"] = str(tmp_path / "missing")
    else:
        (tmp_path / "os-release").write_text(os_release, encoding="utf-8")
        env["NIKOS_OS_RELEASE_FILE"] = str(tmp_path / "os-release")
    r = subprocess.run(["bash", str(NIKOS_CLI), "doctor"], capture_output=True, text=True,
                       env=env, timeout=60)
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)


def _os_lines(out: str) -> list[str]:
    return [l for l in out.splitlines() if "OS:" in l or "supported release" in l]


@pytest.mark.parametrize(
    "version,codename",
    [("24.04", "noble"), ("26.04", "resolute")],
)
def test_a_supported_release_is_named_and_passes(tmp_path, version, codename):
    out = _doctor(tmp_path, (
        f'PRETTY_NAME="Ubuntu {version} LTS"\nNAME="Ubuntu"\nVERSION_ID="{version}"\n'
        f"ID=ubuntu\nID_LIKE=debian\nVERSION_CODENAME={codename}\nUBUNTU_CODENAME={codename}\n"
    ))
    lines = _os_lines(out)
    assert lines, out
    assert f"[Info]: OS: Ubuntu {version} LTS (ID=ubuntu VERSION_ID={version} codename={codename})" in lines[0]
    assert f"Success [OK]: Ubuntu {version} is a supported release" in lines[1]
    assert not any("not a supported release" in l for l in out.splitlines()), out


def test_an_interim_ubuntu_release_warns_and_does_not_count_as_an_issue(tmp_path):
    out = _doctor(tmp_path, 'ID=ubuntu\nVERSION_ID="25.10"\nVERSION_CODENAME=questing\n')
    lines = _os_lines(out)
    # No PRETTY_NAME: the id and version stand in for it.
    assert "[Info]: OS: ubuntu 25.10 (ID=ubuntu VERSION_ID=25.10 codename=questing)" in lines[0]
    assert "[Warning!]: ubuntu 25.10 is not a supported release" in lines[1]
    assert "22.04, 24.04 or 26.04" in lines[1]
    assert not any("[Error!]" in l and "25.10" in l for l in out.splitlines()), out


def test_another_distribution_warns(tmp_path):
    out = _doctor(tmp_path, (
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n'
        "VERSION_CODENAME=trixie\n"
    ))
    lines = _os_lines(out)
    assert "OS: Debian GNU/Linux 13 (trixie) (ID=debian VERSION_ID=13 codename=trixie)" in lines[0]
    assert "[Warning!]: debian 13 is not a supported release" in lines[1]


def test_ubuntu_codename_is_the_fallback(tmp_path):
    out = _doctor(tmp_path, 'ID=ubuntu\nVERSION_ID="24.04"\nUBUNTU_CODENAME=noble\n')
    assert "codename=noble" in _os_lines(out)[0]


def test_a_missing_os_release_is_one_warning(tmp_path):
    out = _doctor(tmp_path, None)
    line = next(l for l in out.splitlines() if "OS:" in l)
    assert line.startswith("[Warning!]"), line
    assert "could not be checked" in line
    assert not any("supported release" in l for l in out.splitlines()), out


def test_the_warning_does_not_change_the_issue_count(tmp_path):
    """The same fake home with a supported and an unsupported release: the
    count of issues doctor reports is the same, so the OS line never fails it."""
    def count(os_release: str) -> int:
        out = _doctor(tmp_path / os_release.split('"')[1], os_release)
        m = re.search(r"(\d+) issue\(s\) found", out)
        assert m, out
        return int(m.group(1))

    assert count('ID=ubuntu\nVERSION_ID="24.04"\n') == count('ID=ubuntu\nVERSION_ID="25.10"\n')
