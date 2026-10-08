"""The forwarder that lets containers reach the local Ollama on the Docker bridge.

The tasks are taken from roles/ai-stack/tasks/main.yml and run for real against
stand-in `docker` commands; the unit files are written to a temporary directory
and checked with `systemd-analyze verify`. Nothing is installed.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TASKS = yaml.safe_load((ROOT / "roles/ai-stack/tasks/main.yml").read_text())


def task(name):
    return dict(next(t for t in TASKS if t["name"] == name))


PROBE = task("Find the Docker bridge address for the Ollama forwarder")
CHOOSE = task("Choose the Ollama forwarder address")
REFUSE = task("Refuse an Ollama forwarder address outside the Docker bridge range")
SOCKET = task("Write the Ollama forwarder socket")
SERVICE = task("Write the Ollama forwarder service")


def _stub_docker(bindir: Path, rootless: bool, gateway: str) -> None:
    p = bindir / "docker"
    p.write_text(
        "#!/bin/sh\n"
        f'case "$1" in info) echo "[name=seccomp{",name=rootless" if rootless else ""}]" ;;'
        f' network) echo "{gateway}" ;; esac\n'
    )
    p.chmod(0o755)


def run(tmp_path, tasks, path_dirs, system_path=True, **vars_):
    dirs = [*map(str, path_dirs), *(["/usr/bin", "/bin"] if system_path else [])]
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {"PATH": ":".join(dirs)},
        "vars": {"nikos_ollama_mode": "local", "nikos_ollama_host": "127.0.0.1:11434", **vars_},
        "tasks": [*tasks, {"ansible.builtin.debug": {"msg": "ADDR=[{{ ai_stack_bridge_addr }}]"}}],
    }]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    return subprocess.run(["ansible-playbook", "-i", "localhost,", "play.yml"], cwd=tmp_path,
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, stdin=subprocess.DEVNULL)


def addr(out):
    line = next(line for line in out.stdout.splitlines() if "ADDR=[" in line)
    return line.split("ADDR=[", 1)[1].split("]", 1)[0]


@pytest.fixture()
def bindir(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    return d


def test_auto_takes_the_bridge_of_a_rootful_docker(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    out = run(tmp_path, [PROBE, CHOOSE, REFUSE], [bindir], nikos_ollama_bridge="auto")
    assert out.returncode == 0, out.stdout
    assert addr(out) == "172.17.0.1"


def test_auto_skips_rootless_docker(tmp_path, bindir):
    _stub_docker(bindir, rootless=True, gateway="172.17.0.1")
    out = run(tmp_path, [PROBE, CHOOSE, REFUSE], [bindir], nikos_ollama_bridge="auto")
    assert out.returncode == 0, out.stdout
    assert addr(out) == ""


def test_auto_without_docker_installs_nothing(tmp_path, bindir):
    # Only grep on PATH: a real docker in /usr/bin must not be found.
    (bindir / "grep").symlink_to(shutil.which("grep"))
    out = run(tmp_path, [PROBE, CHOOSE, REFUSE], [bindir], system_path=False, nikos_ollama_bridge="auto")
    assert out.returncode == 0, out.stdout
    assert addr(out) == ""


def test_off_installs_nothing(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    out = run(tmp_path, [PROBE, CHOOSE, REFUSE], [bindir], nikos_ollama_bridge="off")
    assert addr(out) == ""


def test_remote_mode_installs_nothing(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    out = run(tmp_path, [PROBE, CHOOSE, REFUSE], [bindir], nikos_ollama_bridge="auto",
              nikos_ollama_mode="remote")
    assert addr(out) == ""


def test_an_explicit_bridge_address_is_used(tmp_path, bindir):
    out = run(tmp_path, [CHOOSE, REFUSE], [bindir], nikos_ollama_bridge="172.20.0.1")
    assert out.returncode == 0, out.stdout
    assert addr(out) == "172.20.0.1"


@pytest.mark.parametrize("bad", ["192.168.1.5", "0.0.0.0", "10.0.0.1", "172.32.0.1", "172.17.0.1; rm -rf /"])
def test_an_address_outside_the_bridge_range_is_refused(tmp_path, bindir, bad):
    out = run(tmp_path, [CHOOSE, REFUSE], [bindir], nikos_ollama_bridge=bad)
    assert out.returncode != 0
    assert "not a Docker bridge address" in out.stdout


def test_a_docker_gateway_outside_the_range_is_refused_too(tmp_path, bindir):
    """A daemon configured with another bridge network must not widen the listener."""
    _stub_docker(bindir, rootless=False, gateway="192.168.5.1")
    out = run(tmp_path, [PROBE, CHOOSE, REFUSE], [bindir], nikos_ollama_bridge="auto")
    assert out.returncode != 0
    assert "not a Docker bridge address" in out.stdout


def _write_units(tmp_path, bindir):
    units = tmp_path / "units"
    units.mkdir()
    tasks = []
    for t, name in ((SOCKET, "nikos-ollama-bridge.socket"), (SERVICE, "nikos-ollama-bridge.service")):
        t = {k: v for k, v in t.items() if k not in ("become", "register")}
        t["ansible.builtin.copy"] = {**t["ansible.builtin.copy"], "dest": str(units / name)}
        tasks.append(t)
    out = run(tmp_path, [CHOOSE, *tasks], [bindir], nikos_ollama_bridge="172.17.0.1",
              nikos_ollama_host="127.0.0.1:11500")
    assert out.returncode == 0, out.stdout
    return units


def test_the_units_listen_on_the_bridge_and_forward_to_loopback(tmp_path, bindir):
    units = _write_units(tmp_path, bindir)
    sock = (units / "nikos-ollama-bridge.socket").read_text()
    svc = (units / "nikos-ollama-bridge.service").read_text()
    assert "ListenStream=172.17.0.1:11500" in sock
    assert "FreeBind=yes" in sock
    assert "IPAddressDeny=any" in sock
    assert "IPAddressAllow=localhost 172.16.0.0/12" in sock
    assert "ExecStart=/usr/lib/systemd/systemd-socket-proxyd 127.0.0.1:11500" in svc


@pytest.mark.skipif(not shutil.which("systemd-analyze") or not Path("/usr/lib/systemd/systemd-socket-proxyd").exists(),
                    reason="needs systemd-analyze and systemd-socket-proxyd")
def test_the_units_pass_systemd_analyze_verify(tmp_path, bindir):
    units = _write_units(tmp_path, bindir)
    out = subprocess.run(["systemd-analyze", "verify", "--man=no",
                          str(units / "nikos-ollama-bridge.socket"), str(units / "nikos-ollama-bridge.service")],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "nikos-ollama-bridge" not in out.stderr, out.stderr


# --- nikos doctor ---------------------------------------------------------
import http.server
import re
import socketserver
import threading

from tests.test_profiles import NIKOS_CLI, _fake_home


def _doctor(tmp_path, units, path, extra_vars=""):
    home = _fake_home(tmp_path, "server")
    if extra_vars:
        with open(home / "vars" / "local.yml", "a", encoding="utf-8") as fh:
            fh.write(extra_vars)
    env = dict(os.environ, NIKOS_HOME=str(home), HOME=str(tmp_path), PATH=path,
               NIKOS_SYSTEMD_DIR=str(units))
    r = subprocess.run(["bash", str(NIKOS_CLI), "doctor"], capture_output=True, text=True, env=env, timeout=60)
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)


def _socket_unit(units, listen):
    units.mkdir(exist_ok=True)
    (units / "nikos-ollama-bridge.socket").write_text(f"[Socket]\nListenStream={listen}\n")


def test_doctor_asks_the_forwarder_and_reports_an_answer(tmp_path):
    class Version(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"version":"x"}')
        def log_message(self, *a):
            pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), Version)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        units = tmp_path / "units"
        _socket_unit(units, f"127.0.0.1:{srv.server_address[1]}")
        out = _doctor(tmp_path, units, "/usr/bin:/bin")
    finally:
        srv.shutdown()
    line = next(l for l in out.splitlines() if "Ollama forwarder answers" in l)
    assert not line.startswith("[error]"), out


def test_doctor_reports_a_forwarder_that_does_not_answer(tmp_path):
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, "/usr/bin:/bin")
    line = next(l for l in out.splitlines() if "Ollama forwarder answers" in l)
    assert line.startswith("[error]"), line


def test_doctor_warns_when_docker_has_no_forwarder(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    out = _doctor(tmp_path, tmp_path / "none", f"{bindir}:/usr/bin:/bin")
    assert "No Ollama forwarder on the Docker bridge" in out, out
    out = _doctor(tmp_path / "off", tmp_path / "none", f"{bindir}:/usr/bin:/bin",
                  extra_vars='nikos_ollama_bridge: "off"\n')
    assert "No Ollama forwarder" not in out, out
