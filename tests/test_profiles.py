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
DESKTOP_ROLES = {"desktop", "theming", "editors", "music", "education"}

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
        "desktop,theming,editors,music,education",
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
    # Port 9 (discard) on loopback: nothing answers, so the endpoint check fails.
    (home / "vars" / "local.yml").write_text(
        f'---\nnikos_profile: "{profile}"\nnikos_ollama_host: "127.0.0.1:9"\n',
        encoding="utf-8",
    )
    return home


@pytest.mark.parametrize("profile", ["server", "desktop"])
def test_doctor_checks_desktop_items_only_on_a_desktop(tmp_path: Path, profile: str) -> None:
    home = _fake_home(tmp_path, profile)
    env = dict(os.environ, NIKOS_HOME=str(home), HOME=str(tmp_path))
    result = subprocess.run(
        ["bash", str(NIKOS_CLI), "doctor"], capture_output=True, text=True, env=env, timeout=60
    )
    out = result.stdout + result.stderr
    assert f"profile: {profile}" in out, out
    desktop_lines = [l for l in out.splitlines() if "VS Code installed" in l or "Nordic" in l]
    if profile == "server":
        assert not any(l.startswith("[error]") or "✗" in l for l in desktop_lines), out
        assert "Skipping desktop checks" in out
    else:
        assert desktop_lines, out
    # Nothing listens on the endpoint, so doctor must say so and fail.
    assert "does not answer at http://127.0.0.1:9" in out, out
    assert result.returncode != 0
