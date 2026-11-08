"""The desktop/server profile and the inference endpoint settings.

A profile is a machine-level fact read from vars/local.yml by the playbook and
by the `nikos` CLI. Each check here is one way that fact could be lost:

* a default that changes what an existing install gets,
* a typo that silently turns a server into a desktop or the reverse,
* a desktop role that runs anyway on a server,
* a desktop-only package left in the core role,
* the installer prompt returning prose instead of the answer,
* `nikos doctor` failing a correct server install on desktop checks.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO / "install.sh"
NIKOS_CLI = REPO / "scripts" / "nikos"
DESKTOP_ROLES = {"desktop", "theming", "editors", "music", "education", "antigravity"}

needs_pty = pytest.mark.skipif(
    shutil.which("script") is None, reason="util-linux `script` is required"
)


def _main_vars() -> dict:
    return yaml.safe_load((REPO / "vars" / "main.yml").read_text(encoding="utf-8"))


def _site_roles() -> list[dict]:
    play = yaml.safe_load((REPO / "site.yml").read_text(encoding="utf-8"))[0]
    return play["roles"]


def test_default_profile_is_desktop() -> None:
    assert _main_vars()["nikos_profile"] == "desktop"


def test_default_inference_endpoint_is_loopback() -> None:
    data = _main_vars()
    assert data["nikos_ollama_mode"] == "local"
    assert data["nikos_ollama_host"] == "127.0.0.1:11434"


def test_desktop_roles_are_gated_on_the_profile_and_core_roles_are_not() -> None:
    gated = set()
    for role in _site_roles():
        when = role.get("when")
        if when is not None:
            assert when == "nikos_profile == 'desktop'", role
            gated.add(role["role"])
    assert gated == DESKTOP_ROLES


def test_every_desktop_role_can_be_named_by_tag() -> None:
    tagged = {r["role"] for r in _site_roles() if r["role"] in r.get("tags", [])}
    assert DESKTOP_ROLES <= tagged


def test_base_installs_no_desktop_package() -> None:
    base = (REPO / "roles" / "base" / "tasks" / "main.yml").read_text(encoding="utf-8")
    for package in ("inkscape", "xfconf", "xfce", "lightdm"):
        assert not re.search(rf"^\s*-\s*{package}\b", base, re.M), package


def _ansible(*extra: str) -> subprocess.CompletedProcess:
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    return subprocess.run(
        [
            "ansible-playbook",
            "site.yml",
            "-i",
            "inventory/local",
            "--check",
            "-e",
            "ansible_become=false",
            *extra,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize(
    "setting",
    [
        "nikos_profile=laptop",
        "nikos_ollama_host=0.0.0.0:11434",
        "nikos_ollama_mode=pair",
        "nikos_ollama_mode=remote",  # no remote URL given
    ],
)
def test_invalid_settings_stop_the_run_and_name_the_file(setting: str) -> None:
    result = _ansible("--tags", "always", "-e", setting)
    assert result.returncode != 0, result.stdout
    assert "vars/local.yml" in result.stdout + result.stderr


def test_a_server_run_skips_every_desktop_role() -> None:
    """Named by tag, on a server profile, the desktop roles still do nothing."""
    result = _ansible(
        "--tags",
        "desktop,theming,editors,music,education,antigravity",
        "-e",
        "nikos_profile=server",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    recap = re.search(r"localhost\s*:\s*ok=(\d+)\s+changed=(\d+).*?failed=(\d+)", result.stdout)
    assert recap, result.stdout
    assert recap.group(2) == "0" and recap.group(3) == "0", result.stdout
    assert "Install Xubuntu desktop packages" in result.stdout
    for line in result.stdout.splitlines():
        assert not line.startswith(("changed:", "ok: [localhost] => (item")), line


def _extract(name: str) -> str:
    text = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"install.sh no longer defines {name}"
    return match.group(0)


def test_profile_is_persisted_next_to_the_timezone(tmp_path: Path) -> None:
    (tmp_path / "vars").mkdir()
    local = tmp_path / "vars" / "local.yml"
    local.write_text('---\nnikos_timezone: "Asia/Tokyo"\n', encoding="utf-8")
    script = "\n".join(
        [
            _extract("_set_profile_in_local_vars"),
            _extract("_get_configured_profile"),
            f'NIKOS_HOME="{tmp_path}"; LOCAL_VARS_REL=vars/local.yml',
            "_set_profile_in_local_vars server",
            "_set_profile_in_local_vars server",
            "_get_configured_profile",
        ]
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "server"
    data = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert data == {"nikos_timezone": "Asia/Tokyo", "nikos_profile": "server"}


@needs_pty
@pytest.mark.parametrize(
    "answers,expected",
    [("\n", "desktop"), ("server\n", "server"), ("laptop\ns\n", "server")],
    ids=["enter-keeps-desktop", "server", "retry-after-typo"],
)
def test_plain_profile_prompt_returns_only_the_answer(tmp_path, answers, expected):
    program = tmp_path / "probe.sh"
    program.write_text(
        "\n\n".join(
            [
                _extract("_say_tty"),
                _extract("_ask_tty"),
                _extract("_select_profile_plain"),
                textwrap.dedent(
                    """
                    _safe_logfile() { :; }
                    _chosen_profile=""
                    _select_profile_plain desktop "No display manager found on this machine."
                    printf '\\nPROFILE=[%s]\\n' "${_chosen_profile}"
                    """
                ),
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["script", "-qec", f"bash {program} < /dev/null", "/dev/null"],
        input=answers.encode(),
        capture_output=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "TERM": "xterm", "HOME": str(tmp_path)},
    )
    out = result.stdout.decode(errors="replace").replace("\r", "")
    assert f"PROFILE=[{expected}]" in out, out


def _fake_home(tmp_path: Path, profile: str) -> Path:
    home = tmp_path / "nikos"
    (home / "vars").mkdir(parents=True)
    shutil.copy(REPO / "vars" / "main.yml", home / "vars" / "main.yml")
    # The real helpers, so the doctor output goes through script-helpers'
    # print functions exactly as on an installed machine.
    (home / "scripts").mkdir()
    (home / "scripts" / "script-helpers").symlink_to(REPO / "scripts" / "script-helpers")
    # Port 9 (discard) on loopback: nothing answers, so the endpoint check fails.
    (home / "vars" / "local.yml").write_text(
        f'---\nnikos_profile: "{profile}"\nnikos_ollama_host: "127.0.0.1:9"\n',
        encoding="utf-8",
    )
    return home


@pytest.mark.parametrize("profile", ["server", "desktop"])
def test_doctor_checks_desktop_items_only_on_a_desktop(tmp_path: Path, profile: str) -> None:
    home = _fake_home(tmp_path, profile)
    # A PATH with none of the optional tools, so optional checks take their
    # warning branch.
    env = dict(os.environ, NIKOS_HOME=str(home), HOME=str(tmp_path), PATH="/usr/bin:/bin")
    result = subprocess.run(
        ["bash", str(NIKOS_CLI), "doctor"], capture_output=True, text=True, env=env, timeout=60
    )
    out = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
    assert "command not found" not in out, out
    assert "All checks passed" in out or "issue(s) found" in out, out
    assert f"profile: {profile}" in out, out
    desktop_lines = [
        l for l in out.splitlines() if "VS Code installed" in l or "Nordic GTK theme" in l
    ]
    # Opt-in on a desktop, so a warning there and no line at all on a server.
    antigravity_lines = [l for l in out.splitlines() if "Antigravity IDE installed" in l]
    if profile == "server":
        assert not desktop_lines, out
        assert not antigravity_lines, out
        assert "Skipping desktop checks" in out
    else:
        assert desktop_lines, out
        assert antigravity_lines, out
        assert "issue(s) found" in out
    # Nothing listens on the endpoint, so doctor must say so and fail.
    assert "does not answer at http://127.0.0.1:9" in out, out
    assert result.returncode != 0


@pytest.mark.parametrize("bundle", ["music", "education", "antigravity"])
def test_nikos_add_refuses_a_desktop_bundle_on_a_server(tmp_path: Path, bundle: str) -> None:
    """site.yml would skip it and the run would report success anyway."""
    home = _fake_home(tmp_path, "server")
    env = dict(os.environ, NIKOS_HOME=str(home), HOME=str(tmp_path), PATH="/usr/bin:/bin")
    result = subprocess.run(
        ["bash", str(NIKOS_CLI), "add", bundle], capture_output=True, text=True, env=env, timeout=60
    )
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "desktop bundle" in out and "vars/local.yml" in out, out
    assert "Installing optional bundle" not in out, out


def _ci_check_runs() -> list[str]:
    """Every `ansible-playbook site.yml ... --check` line in the CI workflow."""
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    )
    lines: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            for line in node.splitlines():
                line = line.strip()
                # A commented-out run is not a run.
                if line.startswith("#"):
                    continue
                if "ansible-playbook site.yml" in line and "--check" in line:
                    lines.append(line)

    walk(workflow)
    return lines


def test_ci_check_runs_the_playbook_as_a_desktop_and_as_a_server() -> None:
    """Without the server run the core roles are never checked under that profile."""
    runs = _ci_check_runs()
    server = [r for r in runs if "nikos_profile=server" in r]
    desktop = [r for r in runs if "nikos_profile=" not in r]
    assert len(server) == 1, runs
    assert len(desktop) == 1, runs
    skip = re.compile(r"--skip-tags\s+(\S+)")
    assert skip.search(server[0]).group(1) == skip.search(desktop[0]).group(1), runs


def test_installer_asks_the_profile_before_the_bundles() -> None:
    """The pickers need the profile to know what not to offer, so it comes first."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    profile = text.index("_select_profile_plain \"${_default_profile}\"")
    bundles = text.index("_raw=$(_select_bundles_dialog)")
    ai_tools = text.index("_raw=$(_select_ai_tools_dialog)")
    timezone = text.index("_select_timezone_plain \"${_detected_tz}\"")
    assert profile < bundles < ai_tools < timezone
    # The after-the-fact warning for a bundle chosen before the profile is gone;
    # what stays is a drop guard that runs right after the pickers.
    assert "The bundles were chosen before the profile" not in text
    assert text.index("_drop_desktop_only_selections\n") < timezone


def _next_step(profile: str, **env: str) -> str:
    script = "\n".join([_extract("_session_next_step"), f"_session_next_step {profile}"])
    out = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", **env},
    )
    return out.stdout


def test_server_next_step_points_at_ssh_not_the_display_manager() -> None:
    out = _next_step("server", XDG_CURRENT_DESKTOP="ubuntu:GNOME")
    assert "LightDM" not in out
    assert "Xubuntu" not in out
    assert "ssh" in out.lower()
    assert "nikos doctor" in out


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"XDG_CURRENT_DESKTOP": "XFCE"}, "Log out and back in"),
        ({"DESKTOP_SESSION": "xubuntu"}, "Log out and back in"),
        ({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, "Reboot to finish switching to LightDM"),
        ({}, "Reboot to finish switching to LightDM"),
    ],
    ids=["xfce", "xubuntu-session", "gnome", "no-session"],
)
def test_desktop_next_step_is_unchanged(env: dict, expected: str) -> None:
    assert expected in _next_step("desktop", **env)
    assert expected in _next_step("", **env)


# The network bundle runs on both profiles. Its GUI packages (the Wireshark Qt
# front end, the OpenVPN NetworkManager GUI plugin) are useless on a server,
# so two tasks inside the role split by profile; the role itself stays
# ungated so the installer keeps offering the tag on a server.
NETWORK_TASKS = REPO / "roles" / "optional" / "network" / "tasks" / "main.yml"
NETWORK_GUI = {"wireshark", "network-manager-openvpn-gnome"}
NETWORK_SHARED = {"nmap", "tcpdump", "traceroute", "netcat-openbsd", "network-manager-openvpn"}


def _network_tasks() -> list[dict]:
    return yaml.safe_load(NETWORK_TASKS.read_text(encoding="utf-8"))


def _apt_names(task: dict) -> set[str]:
    name = task.get("ansible.builtin.apt", {}).get("name", [])
    return {name} if isinstance(name, str) else set(name)


def test_network_bundle_installs_gui_packages_only_on_a_desktop() -> None:
    ungated, desktop, server = set(), set(), set()
    for task in _network_tasks():
        if "ansible.builtin.apt" not in task:
            continue
        names = _apt_names(task)
        when = task.get("when")
        if when is None:
            ungated |= names
        elif when == "nikos_profile == 'desktop'":
            desktop |= names
        elif when == "nikos_profile == 'server'":
            server |= names
        else:
            pytest.fail(f"unexpected gate {when!r} on {task.get('name')}")
    assert desktop == NETWORK_GUI
    assert server == {"tshark"}
    assert ungated == NETWORK_SHARED
    assert not ungated & (desktop | server)


def test_wireshark_capture_answer_is_seeded_before_the_install() -> None:
    """apt runs non-interactive, so an unseeded wireshark-common/install-setuid
    takes its default (false) and the wireshark group grants nothing."""
    tasks = _network_tasks()
    seeds = [i for i, t in enumerate(tasks) if "ansible.builtin.debconf" in t]
    assert len(seeds) == 1, tasks
    seed = tasks[seeds[0]]
    assert seed["ansible.builtin.debconf"] == {
        "name": "wireshark-common",
        "question": "wireshark-common/install-setuid",
        "vtype": "boolean",
        "value": "true",
    }
    assert seed.get("when") is None, "seeded on both profiles"
    installs = [i for i, t in enumerate(tasks) if _apt_names(t) & (NETWORK_GUI | {"tshark"})]
    assert installs and seeds[0] < min(installs)
    # An install that already has wireshark-common never re-reads the answer
    # through apt; a changed seed notifies a handler that reconfigures it.
    handlers = yaml.safe_load(
        (NETWORK_TASKS.parent.parent / "handlers" / "main.yml").read_text(encoding="utf-8")
    )
    handler = next(h for h in handlers if h["name"] == seed["notify"])
    assert handler["ansible.builtin.command"]["cmd"].startswith("dpkg-reconfigure -f noninteractive")
    assert handler["become"] is True


def _task_status(stdout: str) -> dict[str, str]:
    """Task name -> the first status word printed under it (ok, changed, skipping)."""
    status: dict[str, str] = {}
    current = None
    for line in stdout.splitlines():
        match = re.match(r"TASK \[(?:[\w-]+ : )?(.+?)\] \*+", line)
        if match:
            current = match.group(1)
            continue
        match = re.match(r"(ok|changed|skipping|failed|fatal): \[localhost\]", line)
        if match and current and current not in status:
            status[current] = match.group(1)
    return status


@pytest.mark.parametrize("profile", ["server", "desktop"])
def test_network_run_installs_the_capture_tool_for_the_profile(profile: str) -> None:
    result = _ansible("--tags", "network", "-e", f"nikos_profile={profile}")
    assert result.returncode == 0, result.stdout + result.stderr
    status = _task_status(result.stdout)
    gui = status["Install the Wireshark GUI and the OpenVPN NetworkManager GUI plugin"]
    tshark = status["Install tshark"]
    assert status["Install network tools"] != "skipping", status
    if profile == "server":
        assert gui == "skipping" and tshark != "skipping", status
    else:
        assert gui != "skipping" and tshark == "skipping", status


@pytest.mark.parametrize(
    "profile,expected",
    [("server", "nmap, tshark, OpenVPN"), ("desktop", "nmap, wireshark, OpenVPN"), ("", "nmap, wireshark, OpenVPN")],
    ids=["server", "desktop", "unset-is-desktop"],
)
def test_installer_names_the_capture_tool_the_profile_gets(profile: str, expected: str) -> None:
    script = "\n".join(
        [_extract("_network_bundle_tools"), f'_chosen_profile="{profile}"', "_network_bundle_tools"]
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert out.stdout == expected
    text = INSTALL_SH.read_text(encoding="utf-8")
    # Both pickers read it; a literal tool list in either one goes stale.
    assert text.count("$(_network_bundle_tools)") == 2, text.count("$(_network_bundle_tools)")
    assert "(nmap, wireshark, OpenVPN)" not in text
