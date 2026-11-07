"""`./test --show-config`: the release, VM and ISO settings the harness resolves
from NIKOS_TEST_* before it touches VirtualBox."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "test"

ISO_24 = "xubuntu-24.04.4-desktop-amd64.iso"
SERVER_24 = "ubuntu-24.04.5-live-server-amd64.iso"
ISO_26 = "xubuntu-26.04.1-desktop-amd64.iso"
SERVER_26 = "ubuntu-26.04.1-live-server-amd64.iso"


def _config(tmp_path: Path, *args: str, **env: str) -> dict[str, str]:
    # A PATH with no VBoxManage: --show-config exits before the preflight, so
    # a run that reaches it fails here.
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("NIKOS_TEST_")}
    full_env.update(HOME=str(tmp_path), PATH="/usr/bin:/bin", **env)
    r = subprocess.run(["bash", str(HARNESS), "--show-config", *args], capture_output=True,
                       text=True, env=full_env, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VirtualBox not found" not in r.stderr
    return dict(line.split("=", 1) for line in r.stdout.splitlines())


def test_the_default_is_the_24_04_run_as_before(tmp_path):
    cfg = _config(tmp_path)
    assert cfg == {
        "RELEASE": "24.04",
        "PROFILE": "desktop",
        "VM_NAME": "NikOS-test",
        "VM_RAM": "4096",
        "VM_CPUS": "2",
        "VM_DISK": "40960",
        "OS_LABEL": "Xubuntu 24.04",
        "OS_ISO": f"{tmp_path}/Downloads/{ISO_24}",
        "OS_ISO_URL": f"https://cdimage.ubuntu.com/xubuntu/releases/24.04/release/{ISO_24}",
    }


def test_the_24_04_server_run_is_as_before(tmp_path):
    cfg = _config(tmp_path, "--profile=server")
    assert cfg["VM_NAME"] == "NikOS-test-server"
    assert cfg["OS_LABEL"] == "Ubuntu Server 24.04"
    assert cfg["OS_ISO"] == f"{tmp_path}/Downloads/{SERVER_24}"
    assert cfg["OS_ISO_URL"] == f"https://releases.ubuntu.com/24.04/{SERVER_24}"


def test_26_04_selects_its_isos_more_ram_and_its_own_vm(tmp_path):
    cfg = _config(tmp_path, NIKOS_TEST_RELEASE="26.04")
    assert cfg["RELEASE"] == "26.04"
    assert cfg["VM_NAME"] == "NikOS-test-26.04"
    assert cfg["VM_RAM"] == "6144"
    assert cfg["VM_CPUS"] == "2"
    assert cfg["VM_DISK"] == "40960"
    assert cfg["OS_LABEL"] == "Xubuntu 26.04"
    assert cfg["OS_ISO"] == f"{tmp_path}/Downloads/{ISO_26}"
    assert cfg["OS_ISO_URL"] == f"https://cdimage.ubuntu.com/xubuntu/releases/26.04/release/{ISO_26}"


def test_26_04_server_run(tmp_path):
    cfg = _config(tmp_path, "--profile=server", NIKOS_TEST_RELEASE="26.04")
    assert cfg["VM_NAME"] == "NikOS-test-server-26.04"
    assert cfg["OS_LABEL"] == "Ubuntu Server 26.04"
    assert cfg["OS_ISO"] == f"{tmp_path}/Downloads/{SERVER_26}"
    assert cfg["OS_ISO_URL"] == f"https://releases.ubuntu.com/26.04/{SERVER_26}"


def test_the_vm_name_from_the_environment_or_flag_wins_on_either_release(tmp_path):
    assert _config(tmp_path, NIKOS_TEST_RELEASE="26.04", NIKOS_TEST_VM="mine")["VM_NAME"] == "mine"
    assert _config(tmp_path, "--vm-name=flag", "--profile=server",
                   NIKOS_TEST_RELEASE="26.04")["VM_NAME"] == "flag"


def test_the_resource_variables_override_the_release_defaults(tmp_path):
    cfg = _config(tmp_path, NIKOS_TEST_RELEASE="26.04", NIKOS_TEST_VM_RAM="8192",
                  NIKOS_TEST_VM_CPUS="4", NIKOS_TEST_VM_DISK="61440")
    assert (cfg["VM_RAM"], cfg["VM_CPUS"], cfg["VM_DISK"]) == ("8192", "4", "61440")


def test_an_explicit_iso_and_url_replace_the_defaults(tmp_path):
    cfg = _config(tmp_path, NIKOS_TEST_ISO="/isos/custom.iso",
                  NIKOS_TEST_ISO_URL="https://mirror.example/custom.iso")
    assert cfg["OS_ISO"] == "/isos/custom.iso"
    assert cfg["OS_ISO_URL"] == "https://mirror.example/custom.iso"
    assert cfg["RELEASE"] == "24.04"


@pytest.mark.parametrize("release", ["25.10", "22.04", "26.04.1", ""])
def test_any_other_release_is_refused(tmp_path, release):
    r = subprocess.run(["bash", str(HARNESS), "--show-config"], capture_output=True, text=True,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
                            "NIKOS_TEST_RELEASE": release}, timeout=30)
    if release == "":
        # Empty means unset: the default run.
        assert r.returncode == 0, r.stderr
        assert "RELEASE=24.04" in r.stdout
    else:
        assert r.returncode == 1
        assert "NIKOS_TEST_RELEASE must be 24.04 or 26.04" in r.stderr
        assert release in r.stderr


def test_an_unknown_argument_is_refused(tmp_path):
    r = subprocess.run(["bash", str(HARNESS), "--profile", "server"], capture_output=True,
                       text=True, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=30)
    assert r.returncode == 1
    assert "unknown argument: --profile" in r.stderr
