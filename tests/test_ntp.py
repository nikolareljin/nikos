"""NTP in the base role and in `nikos doctor`.

`timedatectl set-ntp true` answers "Failed to set ntp: NTP not supported" on a
host where no time sync unit is loaded: a minimal Ubuntu 22.04 or 24.04
without systemd-timesyncd, a 25.10 or later without chrony, or a container.
The base role used to stop the whole playbook on that line.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_profiles import NIKOS_CLI, _fake_home

ROOT = Path(__file__).resolve().parent.parent
TASKS = yaml.safe_load((ROOT / "roles/base/tasks/main.yml").read_text(encoding="utf-8"))
NTP = next(t for t in TASKS if t["name"] == "Enable NTP time synchronization")

TIMEDATECTL = """#!/bin/sh
printf '%s\\n' "$*" >> "${CALLS}"
case "$*" in
  "show --property=CanNTP --value") echo "${CAN_NTP}" ;;
  "set-ntp true")
    if [ -n "${SET_NTP_ERROR}" ]; then
      echo "Failed to set ntp: ${SET_NTP_ERROR}" >&2
      exit 1
    fi ;;
  "show --property=NTP --value") echo "${NTP_ON}" ;;
  *) echo "unexpected: $*" >&2; exit 2 ;;
esac
"""

# Two installed packages and one removed; only ntpsec provides time-daemon.
DPKG_QUERY = """#!/bin/sh
printf 'bash install ok installed\\t\\n'
printf 'chrony deinstall ok config-files\\ttime-daemon\\n'
printf 'ntpsec install ok installed\\ttime-daemon\\n'
"""


def _stub_timedatectl(tmp_path: Path) -> tuple[Path, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls"
    stub = bindir / "timedatectl"
    stub.write_text(TIMEDATECTL)
    stub.chmod(0o755)
    return bindir, calls


def _stub_dpkg_query(bindir: Path, body: str = "#!/bin/sh\nexit 0\n") -> None:
    stub = bindir / "dpkg-query"
    stub.write_text(body)
    stub.chmod(0o755)


def _run_role(tmp_path: Path, *, can_ntp: str, set_error: str = "", version: str = "24.04",
              container: bool = False, extra: dict | None = None,
              dpkg: str = "#!/bin/sh\nexit 0\n") -> tuple[int, str, Path]:
    """Run the real NTP block; apt and systemd become debug lines that keep their `when`."""
    bindir, calls = _stub_timedatectl(tmp_path)
    _stub_dpkg_query(bindir, dpkg)
    block = dict(NTP)
    block["block"] = []
    for task in NTP["block"]:
        task = dict(task)
        if "ansible.builtin.apt" in task:
            task.pop("ansible.builtin.apt")
            task["ansible.builtin.debug"] = {"msg": "INSTALL={{ base_time_daemon }}"}
        if "ansible.builtin.systemd" in task:
            task.pop("ansible.builtin.systemd")
            task["ansible.builtin.debug"] = {"msg": "RESTART=timedated"}
        block["block"].append(task)
    facts = {"distribution_version": version,
             "virtualization_tech_guest": ["docker", "container"] if container else []}
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {"PATH": f"{bindir}:/usr/bin:/bin", "CALLS": str(calls),
                        "CAN_NTP": can_ntp, "SET_NTP_ERROR": set_error},
        "vars": {"ansible_facts": facts, **(extra or {})},
        "tasks": [block],
    }]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    out = subprocess.run(["ansible-playbook", "-i", "localhost,", "play.yml"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=120,
                         env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, stdin=subprocess.DEVNULL)
    return out.returncode, out.stdout + out.stderr, calls


def test_a_host_with_a_time_service_just_turns_ntp_on(tmp_path):
    rc, out, calls = _run_role(tmp_path, can_ntp="yes")
    assert rc == 0, out
    assert "INSTALL=" not in out
    assert "NTP stays off" not in out
    assert "RESTART=" not in out, out
    assert calls.read_text().splitlines() == ["show --property=CanNTP --value", "set-ntp true"]


@pytest.mark.parametrize("version,package", [
    ("22.04", "systemd-timesyncd"),
    ("24.04", "systemd-timesyncd"),
    ("26.04", "chrony"),
])
def test_a_host_without_one_gets_the_daemon_its_release_ships(tmp_path, version, package):
    rc, out, calls = _run_role(tmp_path, can_ntp="no", version=version)
    assert rc == 0, out
    assert f"INSTALL={package}" in out, out
    # timedated lists ntp-units.d once at start: a fresh one must answer set-ntp.
    assert out.index(f"INSTALL={package}") < out.index("RESTART=timedated"), out
    assert calls.read_text().splitlines()[-1] == "set-ntp true"


def test_another_time_daemon_is_left_alone(tmp_path):
    """ntpsec provides time-daemon without an ntp-units.d entry; installing
    systemd-timesyncd next to it would remove it (Conflicts: time-daemon)."""
    rc, out, _ = _run_role(tmp_path, can_ntp="no", set_error="NTP not supported", dpkg=DPKG_QUERY)
    assert rc == 0, out
    assert "INSTALL=" not in out, out
    assert "RESTART=" not in out, out
    assert "ntpsec is installed" in out, out
    assert "chrony" not in out, out


def test_a_container_gets_no_package_and_one_note(tmp_path):
    """The failing line from the issue, on a host where nothing can fix it."""
    rc, out, calls = _run_role(tmp_path, can_ntp="no", set_error="NTP not supported", container=True)
    assert rc == 0, out
    assert "INSTALL=" not in out, out
    assert out.count("NTP stays off") == 1, out
    assert "NTP not supported" in out
    assert "set-ntp true" in calls.read_text()


def test_ntp_not_supported_after_the_install_is_a_note_not_a_failure(tmp_path):
    rc, out, _ = _run_role(tmp_path, can_ntp="no", set_error="NTP not supported")
    assert rc == 0, out
    assert "INSTALL=systemd-timesyncd" in out
    assert out.count("NTP stays off") == 1, out


def test_any_other_set_ntp_error_still_fails(tmp_path):
    rc, out, _ = _run_role(tmp_path, can_ntp="yes", set_error="Failed to connect to bus")
    assert rc != 0, out
    assert "NTP stays off" not in out


def test_an_image_build_leaves_the_clock_alone(tmp_path):
    rc, out, calls = _run_role(tmp_path, can_ntp="yes", extra={"nikos_image_build": True})
    assert rc == 0, out
    assert not calls.exists(), calls.read_text()


def test_the_probe_runs_in_check_mode_and_set_ntp_does_not():
    probe = next(t for t in NTP["block"] if "CanNTP" in t.get("ansible.builtin.command", ""))
    assert probe["check_mode"] is False
    assert probe["failed_when"] is False
    turn_on = next(t for t in NTP["block"] if "set-ntp" in t.get("ansible.builtin.command", ""))
    assert "check_mode" not in turn_on


# --- nikos doctor -----------------------------------------------------------

def _doctor(tmp_path: Path, can_ntp: str, ntp_on: str) -> str:
    home = _fake_home(tmp_path, "server")
    (home / "roles").symlink_to(ROOT / "roles")
    bindir, _ = _stub_timedatectl(tmp_path)
    env = dict(os.environ, NIKOS_HOME=str(home), HOME=str(tmp_path),
               PATH=f"{bindir}:/usr/bin:/bin", CALLS=str(tmp_path / "calls"),
               CAN_NTP=can_ntp, NTP_ON=ntp_on, SET_NTP_ERROR="")
    r = subprocess.run(["bash", str(NIKOS_CLI), "doctor"], capture_output=True, text=True,
                       env=env, timeout=60)
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)


def _line(out: str, text: str) -> str:
    return next(l for l in out.splitlines() if text in l)


def test_doctor_passes_a_host_with_ntp_on(tmp_path):
    line = _line(_doctor(tmp_path, "yes", "yes"), "NTP time sync enabled")
    assert not line.startswith(("[error]", "[Error!]")), line


def test_doctor_flags_a_host_that_could_sync_but_does_not(tmp_path):
    line = _line(_doctor(tmp_path, "yes", "no"), "NTP time sync enabled")
    assert line.startswith(("[error]", "[Error!]")), line


def test_doctor_warns_not_fails_without_a_time_service(tmp_path):
    out = _doctor(tmp_path, "no", "no")
    assert "No time sync service on this host" in out, out
    assert "NTP time sync enabled" not in out
