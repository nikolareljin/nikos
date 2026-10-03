"""The NVIDIA driver step that replaced the one Ollama's install.sh did."""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TASKS = yaml.safe_load((ROOT / "roles/ai-stack/tasks/main.yml").read_text())
PROBE = next(t for t in TASKS if t["name"] == "Look for an NVIDIA GPU without a loaded driver")
INSTALL = next(t for t in TASKS if t["name"] == "Install the recommended NVIDIA driver from Ubuntu")


def _stub(bindir: Path, name: str, body: str) -> None:
    p = bindir / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(0o755)


@pytest.mark.parametrize(
    "lspci,has_driver,extra,needs",
    [
        ("01:00.0 VGA compatible controller: NVIDIA Corporation GA106", False, {}, True),
        ("01:00.0 VGA compatible controller: NVIDIA Corporation GA106", True, {}, False),
        ("", False, {}, False),
        ("01:00.0 3D controller: NVIDIA Corporation", False, {"nikos_nvidia_drivers": False}, False),
        ("01:00.0 3D controller: NVIDIA Corporation", False, {"nikos_image_build": True}, False),
    ],
    ids=["nvidia-no-driver", "nvidia-driver-loaded", "no-nvidia", "switched-off", "image-build"],
)
def test_probe_runs_the_real_task(tmp_path, lspci, has_driver, extra, needs):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir, "lspci", f"printf '%s\\n' '{lspci}'\n" if lspci else "exit 0\n")
    if has_driver:
        _stub(bindir, "nvidia-smi", "echo 'GPU 0: NVIDIA'\n")
    probe = dict(PROBE)
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {"PATH": f"{bindir}:/usr/bin:/bin"},
        "vars": {"nikos_ollama_mode": "local", **extra},
        "tasks": [probe, {"ansible.builtin.debug": {
            "msg": "NEEDS={{ (ai_stack_nvidia_needs_driver.rc | default(1)) == 0 }}"}}],
    }]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    out = subprocess.run(["ansible-playbook", "-i", "localhost,", "play.yml"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=120,
                         env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, stdin=subprocess.DEVNULL)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"NEEDS={needs}" in out.stdout, out.stdout


def test_driver_comes_from_ubuntu_not_a_download():
    body = json.dumps(INSTALL)
    assert "ubuntu-drivers install" in body
    assert "get_url" not in body and "curl" not in body
