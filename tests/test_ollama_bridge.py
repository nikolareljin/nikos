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
TASKS = yaml.safe_load((ROOT / "roles/ai-stack/tasks/bridge.yml").read_text())


def task(name):
    return dict(next(t for t in TASKS if t["name"] == name))


PROBE = task("Find the Docker bridge address for the Ollama forwarder")
CHOOSE = task("Choose the Ollama forwarder address")
REFUSE = task("Refuse an Ollama forwarder address outside the Docker bridge range")
OVERLAP = task("Find networks outside Docker that use 172.16.0.0/12")
GUARD = task("Refuse the Ollama forwarder where another network shares Docker's range")
SOCKET = task("Write the Ollama forwarder socket")
NFT = task("Write the Ollama forwarder's interface filter")
FILTER_UNIT = task("Write the Ollama forwarder's filter service")
SERVICE = task("Write the Ollama forwarder service")


def _stub_docker(bindir: Path, rootless: bool, gateway: str, desktop: bool = False) -> None:
    """Answers the docker calls bridge.yml makes, as the real CLI does: two bridge
    networks, the default one named docker0 and a compose one left to br-<id>."""
    p = bindir / "docker"
    p.write_text(
        "#!/bin/bash\n"
        f'if [ "$1" = info ] && echo "$*" | grep -q OperatingSystem; then echo "{"Docker Desktop" if desktop else "Ubuntu 24.04 LTS"}"; exit 0; fi\n'
        f'if [ "$1" = info ]; then echo "[name=seccomp{",name=rootless" if rootless else ""}]"; exit 0; fi\n'
        'if [ "$2" = ls ]; then printf "%s\\n" aaaaaaaaaaaa 646c6b405144; exit 0; fi\n'
        f'if [ "$2" = inspect ] && [ "$3" = bridge ]; then echo "{gateway}"; exit 0; fi\n'
        'if [ "$2" = inspect ]; then [ "${@: -1}" = aaaaaaaaaaaa ] && echo docker0 || echo; exit 0; fi\n'
    )
    p.chmod(0o755)


def run(tmp_path, tasks, path_dirs, system_path=True, **vars_):
    # The probe and the check run as root on a machine; here, as the test user.
    tasks = [{k: v for k, v in t.items() if k != "become"} for t in tasks]
    dirs = [*map(str, path_dirs), *(["/usr/bin", "/bin"] if system_path else [])]
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {"PATH": ":".join(dirs)},
        "vars": {"nikos_ollama_mode": "local", "nikos_ollama_host": "127.0.0.1:11434",
                 "role_path": str(ROOT / "roles/ai-stack"), **vars_},
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
    for t, name in ((SOCKET, "nikos-ollama-bridge.socket"), (SERVICE, "nikos-ollama-bridge.service"),
                    (FILTER_UNIT, "nikos-ollama-bridge-filter.service"), (NFT, "ollama-bridge.nft")):
        t = {k: v for k, v in t.items() if k not in ("become", "register")}
        t["ansible.builtin.copy"] = {**t["ansible.builtin.copy"], "dest": str(units / name)}
        tasks.append(t)
    decided = {"ansible.builtin.set_fact": {"ai_stack_bridge_wanted": True}}
    out = run(tmp_path, [CHOOSE, decided, *tasks], [bindir], nikos_ollama_bridge="172.17.0.1",
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
    assert "ExecStart=/usr/lib/systemd/systemd-socket-proxyd --exit-idle-time=60 127.0.0.1:11500" in svc
    # Checked before every start, as root, so a network that joined the range
    # after the play stops the forwarder; idle exit makes every start recheck.
    assert "ExecCondition=+/usr/local/libexec/nikos-ollama-bridge-check" in svc


@pytest.mark.skipif(not shutil.which("systemd-analyze") or not Path("/usr/lib/systemd/systemd-socket-proxyd").exists(),
                    reason="needs systemd-analyze and systemd-socket-proxyd")
def test_the_units_pass_systemd_analyze_verify(tmp_path, bindir):
    units = _write_units(tmp_path, bindir)
    # The check is installed under /usr/local/libexec by the play; verify the
    # unit against the repository's copy of the same file.
    svc = units / "nikos-ollama-bridge.service"
    svc.write_text(svc.read_text().replace("/usr/local/libexec/nikos-ollama-bridge-check",
                                           str(ROOT / "roles/ai-stack/files/nikos-ollama-bridge-check")))
    out = subprocess.run(["systemd-analyze", "verify", "--man=no",
                          str(units / "nikos-ollama-bridge.socket"), str(units / "nikos-ollama-bridge.service"),
                          str(units / "nikos-ollama-bridge-filter.service")],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "nikos-ollama-bridge" not in out.stderr, out.stderr


# --- nikos doctor ---------------------------------------------------------
import http.server
import re
import socketserver
import threading

from tests.test_profiles import NIKOS_CLI, _fake_home


def _is_error(line: str) -> bool:
    """script-helpers prints "[Error!]: "; the CLI's fallback, when the
    submodule is absent, prints "[error] ". Either is an error line."""
    return line.startswith(("[error]", "[Error!]"))


def _doctor(tmp_path, units, path, extra_vars="", ufw_conf=None):
    home = _fake_home(tmp_path, "server")
    (home / "roles").symlink_to(ROOT / "roles")
    if extra_vars:
        with open(home / "vars" / "local.yml", "a", encoding="utf-8") as fh:
            fh.write(extra_vars)
    env = dict(os.environ, NIKOS_HOME=str(home), HOME=str(tmp_path), PATH=path,
               NIKOS_SYSTEMD_DIR=str(units),
               NIKOS_UFW_CONF=str(ufw_conf or tmp_path / "no-ufw.conf"))
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
    assert not _is_error(line), out


def test_doctor_reports_a_forwarder_that_does_not_answer(tmp_path):
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, "/usr/bin:/bin")
    line = next(l for l in out.splitlines() if "Ollama forwarder answers" in l)
    assert _is_error(line), line


def test_doctor_warns_when_docker_has_no_forwarder(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    out = _doctor(tmp_path, tmp_path / "none", f"{bindir}:/usr/bin:/bin")
    assert "No Ollama forwarder on the Docker bridge" in out, out
    out = _doctor(tmp_path / "off", tmp_path / "none", f"{bindir}:/usr/bin:/bin",
                  extra_vars='nikos_ollama_bridge: "off"\n')
    assert "No Ollama forwarder" not in out, out



# --- another network in Docker's range ---------------------------------------
DOCKER_ROUTES = ("default via 192.168.1.1 dev wlan0 proto dhcp\n"
                 "172.17.0.0/16 dev docker0 proto kernel scope link src 172.17.0.1\n"
                 "172.18.0.0/16 dev br-646c6b405144 proto kernel scope link src 172.18.0.1\n"
                 "local 172.17.0.1 dev docker0 table local proto kernel scope host src 172.17.0.1\n"
                 "192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.162\n")


def _stub_ip(bindir: Path, lines: str, routes: str = DOCKER_ROUTES, extra_links: str = "") -> None:
    """`ip ... addr` prints the addresses, `ip ... route` the routes, and
    `ip ... link` every interface named in the addresses, plus extra_links."""
    names = list(dict.fromkeys(l.split()[1] for l in lines.splitlines() if l.strip()))
    links = "".join(f"{i}: {n}: <UP> mtu 1500 state UP\n" for i, n in enumerate(names, 1)) + extra_links
    p = bindir / "ip"
    p.write_text("#!/bin/sh\ncase \"$*\" in *route*) cat <<'EOF'\n" + routes + "EOF\n;;"
                 " *link*) cat <<'EOF'\n" + links + "EOF\n;;"
                 " *) cat <<'EOF'\n" + lines + "EOF\n;; esac\n")
    p.chmod(0o755)


DOCKER_ONLY = ("1: lo    inet 127.0.0.1/8 scope host lo\n"
               "2: wlan0    inet 192.168.1.162/24 brd 192.168.1.255 scope global wlan0\n"
               "3: docker0    inet 172.17.0.1/16 scope global docker0\n"
               "4: br-646c6b405144    inet 172.18.0.1/16 scope global br-646c6b405144\n")


DECIDE = task("Decide whether the Ollama forwarder may run")


def guard_run(tmp_path, bindir, **vars_):
    """CHOOSE, the checks and the decision, then the refusal; the decision is printed."""
    tasks = [CHOOSE, REFUSE, OVERLAP, DECIDE,
             {"ansible.builtin.debug": {"msg": "WANTED=[{{ ai_stack_bridge_wanted }}]"}}, GUARD]
    return run(tmp_path, tasks, [bindir], **vars_)


def test_docker_networks_alone_pass(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    out = guard_run(tmp_path, bindir, nikos_ollama_bridge="172.17.0.1")
    assert out.returncode == 0, out.stdout
    assert "WANTED=[True]" in out.stdout, out.stdout


def test_an_interface_is_trusted_because_docker_names_it_not_because_of_its_name(tmp_path, bindir):
    """br-* not created by Docker is somebody else's network."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + "5: br-lan    inet 172.16.9.1/24 scope global br-lan\n")
    out = guard_run(tmp_path, bindir, nikos_ollama_bridge="172.17.0.1")
    assert out.returncode != 0
    assert "br-lan (named like a Docker bridge, not Docker's)" in out.stdout, out.stdout


def test_interfaces_that_cannot_be_read_refuse_the_forwarder(tmp_path, bindir):
    """Fail closed: no answer from ip is not "no overlap"."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    (bindir / "ip").write_text("#!/bin/sh\necho 'ip: cannot open netlink socket' >&2\nexit 1\n")
    (bindir / "ip").chmod(0o755)
    out = guard_run(tmp_path, bindir, nikos_ollama_bridge="172.17.0.1")
    assert out.returncode != 0
    assert "WANTED=[True]" not in out.stdout, out.stdout


def test_remote_mode_wants_no_forwarder_so_an_installed_one_is_removed(tmp_path, bindir):
    out = guard_run(tmp_path, bindir, nikos_ollama_bridge="auto", nikos_ollama_mode="remote")
    assert out.returncode == 0, out.stdout
    assert "WANTED=[False]" in out.stdout, out.stdout


def test_the_forwarder_is_removed_before_a_refusal_ends_the_play():
    names = [t["name"] for t in TASKS]
    assert names.index("Remove the Ollama forwarder that must not run") < \
        names.index("Refuse the Ollama forwarder where another network shares Docker's range")
    removal = next(t for t in TASKS if t["name"] == "Remove the Ollama forwarder that must not run")
    assert "not (ai_stack_bridge_wanted | bool)" in removal["when"]


def test_bridge_yml_is_included_in_every_mode():
    main = yaml.safe_load((ROOT / "roles/ai-stack/tasks/main.yml").read_text())
    inc = next(t for t in main if t.get("ansible.builtin.include_tasks") == "bridge.yml")
    assert "when" not in inc
    play = yaml.safe_load((ROOT / "site.yml").read_text())[0]
    post = next(t for t in play["post_tasks"]
                if (t.get("ansible.builtin.include_role") or {}).get("tasks_from") == "bridge.yml")
    assert "when" not in post


@pytest.mark.parametrize("iface,addr", [("eth0", "172.16.4.20/24"), ("tun0", "172.31.0.7/16"), ("wg0", "172.20.1.1/24")])
def test_a_lan_or_vpn_in_dockers_range_refuses_the_forwarder(tmp_path, bindir, iface, addr):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + f"5: {iface}    inet {addr} scope global {iface}\n")
    out = guard_run(tmp_path, bindir, nikos_ollama_bridge="172.17.0.1")
    assert out.returncode != 0
    assert f"{iface} {addr}" in out.stdout and "could reach Ollama" in out.stdout, out.stdout


def test_no_forwarder_means_no_overlap_check(tmp_path, bindir):
    _stub_ip(bindir, DOCKER_ONLY + "5: eth0    inet 172.16.4.20/24 scope global eth0\n")
    out = guard_run(tmp_path, bindir, nikos_ollama_bridge="off")
    assert out.returncode == 0, out.stdout



def test_the_forwarder_also_runs_after_every_role():
    """Docker is installed by dev-tools, after ai-stack: a first install would
    find no bridge if the forwarder ran only inside ai-stack."""
    play = yaml.safe_load((ROOT / "site.yml").read_text())[0]
    roles = [r["role"] if isinstance(r, dict) else r for r in play["roles"]]
    assert roles.index("dev-tools") > roles.index("ai-stack")
    post = [t for t in play["post_tasks"]
            if (t.get("ansible.builtin.include_role") or {}).get("tasks_from") == "bridge.yml"]
    assert post and post[0]["ansible.builtin.include_role"]["name"] == "ai-stack"
    main = yaml.safe_load((ROOT / "roles/ai-stack/tasks/main.yml").read_text())
    assert any(t.get("ansible.builtin.include_tasks") == "bridge.yml" for t in main)



def test_doctor_reports_a_network_that_joined_dockers_range_after_the_play(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + "5: tun0    inet 172.20.8.2/24 scope global tun0\n")
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin")
    line = next(l for l in out.splitlines() if "shares 172.16.0.0/12" in l)
    assert _is_error(line) and "tun0 172.20.8.2/24" in line, line


def test_doctor_is_quiet_about_dockers_own_networks(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin")
    assert "shares 172.16.0.0/12" not in out, out



# --- the check the forwarder runs before every start ---------------------------
CHECK = ROOT / "roles/ai-stack/files/nikos-ollama-bridge-check"


def _check(bindir, path_extra=True):
    env = {"PATH": f"{bindir}:/usr/bin:/bin" if path_extra else str(bindir)}
    return subprocess.run([str(CHECK)], capture_output=True, text=True, env=env, timeout=30)


def test_check_passes_dockers_own_networks(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    r = _check(bindir)
    assert (r.returncode, r.stdout) == (0, ""), r


def test_check_names_another_network_in_the_range(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + "5: tun0    inet 172.20.8.2/24 scope global tun0\n")
    r = _check(bindir)
    assert r.returncode == 1 and r.stdout.strip() == "tun0 172.20.8.2/24", r


def test_check_fails_closed_when_interfaces_cannot_be_read(bindir):
    (bindir / "ip").write_text("#!/bin/sh\nexit 1\n")
    (bindir / "ip").chmod(0o755)
    assert _check(bindir).returncode == 2


def test_check_fails_closed_when_docker_cannot_list_its_networks(bindir):
    """Without Docker's names every bridge would look foreign, or be skipped."""
    _stub_ip(bindir, DOCKER_ONLY)
    (bindir / "docker").write_text("#!/bin/sh\nexit 1\n")
    (bindir / "docker").chmod(0o755)
    assert _check(bindir).returncode == 2


def test_doctor_reports_a_check_that_cannot_run(tmp_path, bindir):
    (bindir / "ip").write_text("#!/bin/sh\nexit 1\n")
    (bindir / "ip").chmod(0o755)
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin")
    line = next(l for l in out.splitlines() if "could not be checked" in l)
    assert _is_error(line), line



def test_check_names_a_vpn_route_into_the_range_without_an_address_there(bindir):
    """A VPN can route 172.20.0.0/16 while its own address is elsewhere."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + "5: tun0    inet 10.8.0.2/24 scope global tun0\n",
             DOCKER_ROUTES + "172.20.0.0/16 via 10.8.0.1 dev tun0\n")
    r = _check(bindir)
    assert r.returncode == 1 and r.stdout.strip() == "tun0 route 172.20.0.0/16", r


def test_check_names_a_route_that_covers_the_whole_range(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY, DOCKER_ROUTES + "172.0.0.0/8 via 10.8.0.1 dev tun0\n")
    r = _check(bindir)
    assert r.returncode == 1 and "tun0 route 172.0.0.0/8" in r.stdout, r


def test_check_ignores_the_default_route_and_dockers_own(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    assert _check(bindir).returncode == 0


def test_check_fails_closed_when_routes_cannot_be_read(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    p = bindir / "ip"
    p.write_text("#!/bin/sh\ncase \"$*\" in *route*) exit 1 ;; *) echo '1: lo    inet 127.0.0.1/8 scope host lo' ;; esac\n")
    p.chmod(0o755)
    assert _check(bindir).returncode == 2


# --- the parser fails closed ---------------------------------------------------
def test_check_reads_a_route_with_a_type_keyword(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY, DOCKER_ROUTES + "unicast 172.20.0.0/16 via 10.8.0.1 dev tun0\n")
    r = _check(bindir)
    assert r.returncode == 1 and "tun0 route 172.20.0.0/16" in r.stdout, r


def test_check_counts_a_route_without_a_device(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY, DOCKER_ROUTES + "172.20.0.0/16 nhid 12 proto static\n")
    r = _check(bindir)
    assert r.returncode == 1 and "(no device) route 172.20.0.0/16" in r.stdout, r


def test_check_counts_a_point_to_point_peer_in_the_range(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + "5: tun0    inet 10.8.0.2 peer 172.20.0.1/32 scope global tun0\n")
    r = _check(bindir)
    assert r.returncode == 1 and "tun0 172.20.0.1/32" in r.stdout, r


@pytest.mark.parametrize("routes", ["garbage-destination dev tun0\n", "unicast\n"])
def test_check_refuses_a_route_it_cannot_read(bindir, routes):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY, DOCKER_ROUTES + routes)
    assert _check(bindir).returncode == 2


def test_check_refuses_an_address_line_it_cannot_read(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + "5: odd0    something-else\n")
    assert _check(bindir).returncode == 2



# --- the interface filter ---------------------------------------------------------
def test_the_socket_requires_the_interface_filter(tmp_path, bindir):
    units = _write_units(tmp_path, bindir)
    sock = (units / "nikos-ollama-bridge.socket").read_text()
    assert "Requires=nikos-ollama-bridge-filter.service" in sock
    nft = (units / "ollama-bridge.nft").read_text()
    assert "ip daddr 172.17.0.1 tcp dport 11500 jump from_docker_only" in nft
    # Its own table, replaced whole: never a flush of Docker's rules.
    assert "flush ruleset" not in nft and "delete table inet nikos_ollama_bridge" in nft
    for allowed in ('iifname "lo" return', 'iifname "docker0" return', 'iifname "br-*" return'):
        assert allowed in nft
    assert nft.rstrip().splitlines()[-3].strip() == "drop"


@pytest.mark.skipif(os.environ.get("NIKOS_MACHINE_TESTS") != "1",
                    reason="machine check: needs Docker with privileged containers; NIKOS_MACHINE_TESTS=1")
def test_the_interface_filter_lets_docker_in_and_a_lan_in_the_same_range_not(tmp_path, bindir):
    units = _write_units(tmp_path, bindir)
    nft = units / "ollama-bridge.nft"
    nft.write_text(nft.read_text().replace("tcp dport 11500", "tcp dport 11434"))
    r = subprocess.run(["bash", str(ROOT / "tests/machine/ollama_bridge_filter.sh"), str(nft)],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok: only the Docker side reaches the bridge address" in r.stdout


def _stub_systemctl(bindir: Path, failed_socket: bool, filter_active: bool) -> None:
    p = bindir / "systemctl"
    p.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *is-failed*nikos-ollama-bridge.socket*) exit {0 if failed_socket else 1} ;;\n'
        f' *is-active*nikos-ollama-bridge-filter*) exit {0 if filter_active else 3} ;; esac\nexit 3\n'
    )
    p.chmod(0o755)


def test_doctor_names_a_failed_socket_and_how_to_clear_it(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    _stub_systemctl(bindir, failed_socket=True, filter_active=True)
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin")
    line = next(l for l in out.splitlines() if "socket has failed" in l)
    assert _is_error(line) and "systemctl reset-failed nikos-ollama-bridge.socket" in line, line


def test_doctor_reports_a_filter_that_is_not_loaded(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    _stub_systemctl(bindir, failed_socket=False, filter_active=False)
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin")
    line = next(l for l in out.splitlines() if "interface filter loaded" in l)
    assert _is_error(line), line


def test_doctor_without_docker_access_warns_instead_of_failing(tmp_path, bindir):
    p = bindir / "docker"
    p.write_text("#!/bin/sh\necho 'permission denied while trying to connect to the Docker daemon socket' >&2\nexit 1\n")
    p.chmod(0o755)
    _stub_ip(bindir, DOCKER_ONLY)
    _stub_systemctl(bindir, failed_socket=False, filter_active=True)
    units = tmp_path / "units"
    _socket_unit(units, "127.0.0.1:9")
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin")
    line = next(l for l in out.splitlines() if "networks not checked here" in l)
    assert not _is_error(line), line
    assert "could not be checked" not in out, out


def test_any_leftover_piece_counts_as_an_installed_forwarder(tmp_path, bindir):
    """A partial install (only the filter, say) must be removed, not kept."""
    look = task("Look for an Ollama forwarder that must not run")
    decide = task("Decide whether an Ollama forwarder is installed")
    leftover = tmp_path / "ollama-bridge.nft"
    leftover.write_text("")
    look = {**look, "loop": [str(tmp_path / "no.socket"), str(leftover)]}
    play_tasks = [{"ansible.builtin.set_fact": {"ai_stack_bridge_wanted": False, "ai_stack_bridge_addr": ""}}, look, decide,
                  {"ansible.builtin.debug": {"msg": "ADDR=[{{ ai_stack_bridge_installed.stat.exists }}]"}}]
    out = run(tmp_path, play_tasks, [bindir])
    assert out.returncode == 0, out.stdout
    assert addr(out) == "True"



def test_check_refuses_a_bridge_named_like_dockers_whatever_its_address(bindir):
    """The interface filter trusts br-*: a VM bridge called br-vms must not exist
    beside it, even on 192.168.x where the address filter would not care."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY + "5: br-vms    inet 192.168.50.1/24 scope global br-vms\n")
    r = _check(bindir)
    assert r.returncode == 1 and "br-vms (named like a Docker bridge, not Docker's)" in r.stdout, r


def test_the_forwarder_is_not_deleted_while_a_unit_still_runs(tmp_path, bindir):
    """Deleting the files of a socket that would not stop hides a listener."""
    block = next(t for t in TASKS if t["name"] == "Remove the Ollama forwarder that must not run")
    stop = next(t for t in block["block"] if t["name"] == "Stop the Ollama forwarder's units")
    stop = {k: v for k, v in stop.items() if k != "become"}
    p = bindir / "systemctl"
    p.write_text('#!/bin/sh\ncase "$*" in *is-active*nikos-ollama-bridge.socket*) exit 0 ;; *is-active*) exit 3 ;; esac\nexit 0\n')
    p.chmod(0o755)
    out = run(tmp_path, [{"ansible.builtin.set_fact": {"ai_stack_bridge_addr": ""}}, stop], [bindir])
    assert out.returncode != 0
    assert "still running: nikos-ollama-bridge.socket" in out.stdout, out.stdout
    names = [t["name"] for t in block["block"]]
    assert names.index("Stop the Ollama forwarder's units") < names.index("Delete the Ollama forwarder units")



def test_check_refuses_a_foreign_br_interface_with_no_ipv4_address(bindir):
    """The br-* rule is about names: an interface with no IPv4 address is
    still trusted by the interface filter by its name."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY, extra_links="9: br-ghost: <BROADCAST,UP> mtu 1500 state UP\n")
    r = _check(bindir)
    assert r.returncode == 1 and "br-ghost (named like a Docker bridge, not Docker's)" in r.stdout, r


def test_check_fails_closed_when_interface_names_cannot_be_read(bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    p = bindir / "ip"
    p.write_text("#!/bin/sh\ncase \"$*\" in *link*) exit 1 ;; *route*) echo ;; *) echo '1: lo    inet 127.0.0.1/8 scope host lo' ;; esac\n")
    p.chmod(0o755)
    assert _check(bindir).returncode == 2



# --- third round: the rest of the system -------------------------------------------
def test_auto_skips_docker_desktop(tmp_path, bindir):
    """Docker Desktop's engine runs in a VM: its bridge is not on this host."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1", desktop=True)
    out = run(tmp_path, [PROBE, CHOOSE, REFUSE], [bindir], nikos_ollama_bridge="auto")
    assert out.returncode == 0, out.stdout
    assert addr(out) == ""


def _units_for_host(tmp_path, bindir, host):
    units = tmp_path / "units"
    units.mkdir()
    tasks = []
    for t, name in ((SERVICE, "nikos-ollama-bridge.service"), (FILTER_UNIT, "nikos-ollama-bridge-filter.service")):
        t = {k: v for k, v in t.items() if k not in ("become", "register")}
        t["ansible.builtin.copy"] = {**t["ansible.builtin.copy"], "dest": str(units / name)}
        tasks.append(t)
    decided = {"ansible.builtin.set_fact": {"ai_stack_bridge_wanted": True}}
    out = run(tmp_path, [CHOOSE, decided, *tasks], [bindir], nikos_ollama_bridge="172.17.0.1", nikos_ollama_host=host)
    assert out.returncode == 0, out.stdout
    return units


@pytest.mark.parametrize("host", ["127.0.0.1:11434", "localhost:11434", "[::1]:11434", "127.0.0.2:11500"])
def test_the_proxy_forwards_to_the_engine_address_as_configured(tmp_path, bindir, host):
    svc = (_units_for_host(tmp_path, bindir, host) / "nikos-ollama-bridge.service").read_text()
    assert f"ExecStart=/usr/lib/systemd/systemd-socket-proxyd --exit-idle-time=60 {host}" in svc


def test_the_forwarder_will_not_start_without_its_interface_filter_loaded(tmp_path, bindir):
    units = _units_for_host(tmp_path, bindir, "127.0.0.1:11434")
    svc = (units / "nikos-ollama-bridge.service").read_text()
    assert "ExecCondition=+/usr/sbin/nft list table inet nikos_ollama_bridge" in svc
    flt = (units / "nikos-ollama-bridge-filter.service").read_text()
    # nftables.service's stock config flushes the ruleset: load after it, and again with it.
    assert "After=nftables.service" in flt and "PartOf=nftables.service" in flt


def test_doctor_warns_that_ufw_may_block_containers(tmp_path, bindir):
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    p = bindir / "systemctl"
    p.write_text('#!/bin/sh\ncase "$*" in *is-active*nikos-ollama-bridge-filter*) exit 0 ;; esac\nexit 3\n')
    p.chmod(0o755)
    units = tmp_path / "units"
    _socket_unit(units, "172.17.0.1:11434")
    conf = tmp_path / "ufw.conf"
    conf.write_text("ENABLED=yes\n")
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin", ufw_conf=conf)
    line = next(l for l in out.splitlines() if "ufw is active" in l)
    assert not _is_error(line) and "ufw allow in on docker0 to any port 11434" in line, line


@pytest.mark.parametrize("conf_text", ["ENABLED=no\n", None])
def test_doctor_says_nothing_of_ufw_when_it_is_off(tmp_path, bindir, conf_text):
    """ufw.service reads active with ENABLED=no: it is a oneshot that stays up."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    p = bindir / "systemctl"
    p.write_text('#!/bin/sh\ncase "$*" in *is-active*ufw*) exit 0 ;; *is-active*nikos-ollama-bridge-filter*) exit 0 ;; esac\nexit 3\n')
    p.chmod(0o755)
    units = tmp_path / "units"
    _socket_unit(units, "172.17.0.1:11434")
    conf = tmp_path / "ufw.conf"
    if conf_text is not None:
        conf.write_text(conf_text)
    out = _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin", ufw_conf=conf)
    # The network check runs after the ufw check: doctor got past it.
    assert "no network outside Docker uses 172.16.0.0/12" in out, out
    assert "ufw is active" not in out, out


def test_doctor_probes_the_forwarder_from_loopback(tmp_path, bindir):
    """A host request to its own bridge address carries that address as source
    and was dropped on a real machine; from 127.0.0.1 it is answered."""
    _stub_docker(bindir, rootless=False, gateway="172.17.0.1")
    _stub_ip(bindir, DOCKER_ONLY)
    args = tmp_path / "curl-args"
    p = bindir / "curl"
    p.write_text(f'#!/bin/sh\necho "$*" >> {args}\nexit 0\n')
    p.chmod(0o755)
    units = tmp_path / "units"
    _socket_unit(units, "172.17.0.1:11434")
    _doctor(tmp_path, units, f"{bindir}:/usr/bin:/bin")
    probe = next(l for l in args.read_text().splitlines() if "172.17.0.1:11434" in l)
    assert "--interface 127.0.0.1" in probe, probe



def test_the_post_tasks_include_hands_its_tag_to_the_included_tasks():
    """include_role does not pass its tags on: under --tags ai-local the
    included tasks were skipped unless the include applies the tag."""
    play = yaml.safe_load((ROOT / "site.yml").read_text())[0]
    post = next(t for t in play["post_tasks"]
                if (t.get("ansible.builtin.include_role") or {}).get("tasks_from") == "bridge.yml")
    assert post["ansible.builtin.include_role"]["apply"]["tags"] == ["ai-local"]
    assert post["tags"] == ["ai-local"]



# Directories every Ubuntu install has; anything else a task writes into must be
# created by an earlier task. /usr/local/libexec is not one: Ubuntu does not ship it.
SHIPPED_DIRS = {"/etc/systemd/system"}


def test_every_file_the_forwarder_installs_has_its_directory():
    created = set()
    for t in TASKS:
        f = t.get("ansible.builtin.file") or {}
        if f.get("state") == "directory":
            created.add(f["path"])
        dest = (t.get("ansible.builtin.copy") or {}).get("dest")
        if dest:
            parent = str(Path(dest).parent)
            assert parent in SHIPPED_DIRS or parent in created, \
                f"{t['name']}: {parent} is neither shipped by Ubuntu nor created before it"


@pytest.mark.skipif(os.environ.get("NIKOS_MACHINE_TESTS") != "1",
                    reason="machine check: needs Docker; NIKOS_MACHINE_TESTS=1")
def test_every_forwarder_file_is_written_on_a_stock_ubuntu():
    r = subprocess.run(["bash", str(ROOT / "tests/machine/ollama_bridge_files.sh")],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok: every forwarder file written on a stock image" in r.stdout


@pytest.mark.skipif(os.environ.get("NIKOS_MACHINE_TESTS") != "1",
                    reason="machine check: needs Docker with privileged containers; NIKOS_MACHINE_TESTS=1")
def test_the_forwarder_under_systemd_on_a_stock_ubuntu():
    """The real tasks under systemd: refuse a shared range, install, answer a
    container, refuse a LAN machine, change nothing on a second run, remove on off."""
    r = subprocess.run(["bash", str(ROOT / "tests/machine/ollama_bridge_systemd.sh")],
                       capture_output=True, text=True, timeout=1200)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "ok: refused a shared range, installed, answered a container" in r.stdout
