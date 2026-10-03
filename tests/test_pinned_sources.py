"""NikOS installs only from verified sources, and every pin lives in vars/versions.yml.

Allowed: distro packages, vendor apt repositories whose key fingerprint is
checked before apt trusts it, release files pinned to a version and a sha256,
registry installs at an exact version, git checkouts at a pinned commit.
Not allowed: `curl | sh`, downloaded install scripts run unchecked,
`releases/latest`, `@latest`, branch heads, unchecked downloads.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
VERSIONS = REPO / "vars" / "versions.yml"
TASK_FILES = sorted((REPO / "roles").glob("**/tasks/*.yml"))
# scripts/script-helpers is a vendored submodule of another repository.
SHELL_FILES = [REPO / "install.sh", REPO / "update"] + sorted(
    p for p in (REPO / "scripts").iterdir() if p.is_file()
)

FORBIDDEN = [
    (r"\|\s*(sudo\s+)?(ba)?sh\b", "pipes a download into a shell"),
    (r"releases/latest", "follows the newest release instead of a pin"),
    (r"@latest\b", "installs whatever is newest"),
    (r"state:\s*latest", "installs whatever is newest"),
    (r":latest\b", "an unpinned container image"),
    (r"ollama\.com/install\.sh|bun\.sh/install|get\.netdata\.cloud|get-helm|claude\.ai/install\.sh",
     "runs a vendor install script"),
    (r"\bcargo install\b", "builds an unpinned crate"),
    (r"gh extension install", "installs an unchecked release binary"),
]


def _versions() -> dict:
    return yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))


def _code_lines(path: Path) -> Iterator[tuple[int, str]]:
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.lstrip().startswith("#"):
            yield n, line


def _tasks(items) -> Iterator[dict]:
    """Every task in a task list, including those nested in blocks."""
    for task in items or []:
        if not isinstance(task, dict):
            continue
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key))


def _all_tasks() -> Iterator[tuple[Path, dict]]:
    for path in TASK_FILES:
        for task in _tasks(yaml.safe_load(path.read_text(encoding="utf-8"))):
            yield path, task


def _bare(value) -> str:
    return re.sub(r"[{}'~\s]", "", str(value or ""))


def _module(task: dict, name: str):
    return task.get(f"ansible.builtin.{name}", task.get(name))


@pytest.mark.parametrize("pattern,why", FORBIDDEN, ids=[w for _, w in FORBIDDEN])
def test_no_forbidden_install_pattern(pattern: str, why: str) -> None:
    hits = [f"{p.relative_to(REPO)}:{n}: {line.strip()}"
            for p in TASK_FILES + SHELL_FILES for n, line in _code_lines(p)
            if re.search(pattern, line)]
    assert hits == [], f"{why}:\n" + "\n".join(hits)


def test_every_download_is_checked() -> None:
    # A release file needs a sha256; an apt key needs the fingerprint check
    # on the file it was downloaded to, in the same task file.
    bad = []
    for path in TASK_FILES:
        text = path.read_text(encoding="utf-8")
        for task in _tasks(yaml.safe_load(text)):
            get_url = _module(task, "get_url")
            if not get_url:
                continue
            checksum = str(get_url.get("checksum", ""))
            if re.fullmatch(r"sha256:\{\{ \w+ \}\}", checksum):
                continue
            # Compare with the Jinja punctuation removed: the dest is a
            # templated string, the check's argv a Jinja expression.
            dest = _bare(get_url.get("dest", ""))
            checks = [_bare(_module(t, "command")) for t in _tasks(yaml.safe_load(text))
                      if "verify-key-fingerprint.sh" in str(_module(t, "command") or "")]
            if not dest or not any(dest in c for c in checks):
                bad.append(f"{path.relative_to(REPO)}: {task.get('name')}")
    assert bad == [], bad


def test_every_apt_repository_key_is_fingerprint_checked() -> None:
    bad = []
    for path in TASK_FILES:
        text = path.read_text(encoding="utf-8")
        tasks = list(_tasks(yaml.safe_load(text)))
        if any(_module(t, "apt_repository") or _module(t, "deb822_repository") for t in tasks):
            names = [t.get("name", "") for t in tasks]
            verify = [i for i, t in enumerate(tasks)
                      if "verify-key-fingerprint.sh" in str(_module(t, "command") or "")]
            repo = [i for i, t in enumerate(tasks)
                    if _module(t, "apt_repository") or _module(t, "deb822_repository")]
            if not verify or min(verify) > min(repo):
                bad.append(f"{path.relative_to(REPO)}: {names}")
    assert bad == [], bad


def test_no_git_checkout_follows_a_branch() -> None:
    bad = []
    for path, task in _all_tasks():
        git = _module(task, "git")
        if not git:
            continue
        version = str(git.get("version", "HEAD"))
        if version in ("main", "master", "HEAD") or not version.startswith("{{"):
            bad.append(f"{path.relative_to(REPO)}: {task.get('name')} at {version}")
    assert bad == [], bad


def test_registry_installs_are_exact_versions() -> None:
    bad = []
    for path, task in _all_tasks():
        npm = _module(task, "npm") or task.get("community.general.npm")
        if npm and not str(npm.get("version", "")).startswith("{{"):
            bad.append(f"{path.relative_to(REPO)}: {task.get('name')} (npm without a version)")
        cmd = str(_module(task, "command") or _module(task, "shell") or "")
        if re.search(r"\bpip3?\b.*\binstall\b", cmd) and "requirements.lock" not in cmd:
            bad.append(f"{path.relative_to(REPO)}: {task.get('name')} (pip outside roles/pin-gate)")
        if re.search(r"pipx install", cmd) and not re.search(r"pipx install \S* ?[\w-]+==\{\{ \w+ \}\}", cmd):
            bad.append(f"{path.relative_to(REPO)}: {task.get('name')} (pipx without ==)")
        if re.search(r"npm (i|install)\b.*-g", cmd):
            bad.append(f"{path.relative_to(REPO)}: {task.get('name')} (npm -g by command)")
    # The one pip install is the pin gate, and it only ever passes name==pin.
    gate = (REPO / "roles/pin-gate/tasks/pip.yml").read_text(encoding="utf-8")
    assert "out.append(name ~ '==' ~ pin)" in gate
    assert bad == [], bad


def test_no_hash_or_version_literal_outside_versions_yml() -> None:
    hits = [f"{p.relative_to(REPO)}:{n}" for p in TASK_FILES for n, line in _code_lines(p)
            if re.search(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b|\b[0-9A-F]{40}\b", line)]
    assert hits == [], hits


PIN_SUFFIX = re.compile(r"_(version|sha256|commit|digest|fingerprints?|series)$")
# Not pins: a minimum the CLIs need, a conda range, and NikOS's own version.
NOT_PINS = {"nikos_node_min_version", "nikos_python_version", "nikos_version"}


def test_every_pin_is_defined_only_in_versions_yml() -> None:
    pins = set(_versions())
    others = [REPO / "vars" / "main.yml"] + sorted((REPO / "roles").glob("**/defaults/*.yml")) + sorted(
        (REPO / "roles").glob("**/vars/*.yml"))
    bad = []
    for path in others:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in data:
            if key in pins or (PIN_SUFFIX.search(key) and key not in NOT_PINS):
                bad.append(f"{path.relative_to(REPO)}: {key}")
    for path, task in _all_tasks():
        for key in (task.get("vars") or {}):
            if key in pins:
                bad.append(f"{path.relative_to(REPO)}: {task.get('name')} sets {key}")
    assert bad == [], bad


def test_every_pin_has_a_source_entry_and_is_used() -> None:
    versions = _versions()
    sources = versions["nikos_pin_sources"]
    covered = set()
    for name, src in sources.items():
        assert src["type"] in {
            "github-release", "github-tag", "github-commit", "npm", "pypi", "pypi-map",
            "go-module", "nodejs", "docker-image", "apt-key",
        }, name
        for key in ("version_var", "commit_var", "digest_var", "fingerprints_var"):
            if key in src:
                assert src[key] in versions, (name, key)
                covered.add(src[key])
        for art in src.get("artifacts", []):
            assert art["sha256_var"] in versions, name
            assert re.fullmatch(r"[0-9a-f]{64}", versions[art["sha256_var"]]), name
            covered.add(art["sha256_var"])
    # Derived values and repository series are not pins of their own.
    derived = {"miniforge_url", "nordic_gtk_url", "kubernetes_apt_version", "mongodb_series",
               "mongodb_key_series", "nikos_pin_sources"}
    assert set(versions) - covered - derived == set()
    # Each pin is read somewhere: a task, install.sh, or another pin's value
    # (miniforge_url uses miniforge_version).
    used = "\n".join(p.read_text(encoding="utf-8")
                     for p in TASK_FILES + [REPO / "install.sh", REPO / "scripts" / "bump-versions.py"])
    head = VERSIONS.read_text(encoding="utf-8").split("nikos_pin_sources:")[0]
    used += "\n".join(line.split(":", 1)[1] for line in head.splitlines()
                      if re.match(r"^\w+:", line) and ":" in line)
    unused = [k for k in versions if k != "nikos_pin_sources" and not re.search(rf"\b{k}\b", used)]
    assert unused == [], unused


def test_install_sh_carries_the_same_ansible_ppa_fingerprint() -> None:
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    value = re.search(r'^ANSIBLE_PPA_KEY_FINGERPRINT="([0-9A-F]{40})"$', text, re.M).group(1)
    assert _versions()["ansible_ppa_key_fingerprints"] == [value]


def test_site_loads_versions_after_main_and_local_overrides_it(tmp_path: Path) -> None:
    # The real site.yml play header and its vars/local.yml pre_tasks, with
    # the roles swapped for a debug of two pins.
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    site = yaml.safe_load((REPO / "site.yml").read_text(encoding="utf-8"))[0]
    assert site["vars_files"] == ["vars/main.yml", "vars/versions.yml"]
    local = [t for t in site["pre_tasks"] if "local" in t.get("name", "").lower() and "vars" in t.get("name", "")]
    assert len(local) == 2, [t.get("name") for t in site["pre_tasks"]]
    (tmp_path / "vars").mkdir()
    for name in ("main.yml", "versions.yml"):
        shutil.copy(REPO / "vars" / name, tmp_path / "vars" / name)
    (tmp_path / "VERSION").write_text("0.0.0\n", encoding="utf-8")
    (tmp_path / "vars" / "local.yml").write_text('ollama_version: "v9.9.9"\n', encoding="utf-8")
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": site["vars_files"], "pre_tasks": local,
        "tasks": [{"ansible.builtin.debug": {"msg": "PINS {{ ollama_version }} {{ act_version }}"}}],
    }]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play), encoding="utf-8")
    result = subprocess.run(
        ["ansible-playbook", "play.yml", "-i", "localhost,"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PINS v9.9.9 {_versions()['act_version']}" in result.stdout, result.stdout


# -- The pin gate: install when missing or older, never downgrade ------------


def _gate_play(tmp_path: Path, tasks: list[dict], extra: dict) -> subprocess.CompletedProcess:
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False, "tasks": tasks}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play), encoding="utf-8")
    return subprocess.run(
        ["ansible-playbook", "play.yml", "-i", "localhost,", "-e", json.dumps(extra)],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        env={**os.environ, "ANSIBLE_ROLES_PATH": str(REPO / "roles")},
    )


def _role_tasks(role: str) -> list[dict]:
    return yaml.safe_load((REPO / "roles" / role / "tasks" / "main.yml").read_text(encoding="utf-8"))


def _fake_tool(path: Path, output: str | None) -> None:
    if output is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    path.chmod(0o755)


GATE_TABLE = [
    (None, True, None),
    ("{old}", True, None),
    ("{pin}", False, None),
    ("{new}", False, "is newer than the pin"),
    ("garbled", False, "Could not read the installed"),
]
GATE_IDS = ["none", "older", "equal", "newer", "unparseable"]


@pytest.mark.parametrize("installed,expected,message", GATE_TABLE, ids=GATE_IDS)
def test_fabric_installs_only_when_missing_or_older(tmp_path: Path, installed, expected, message) -> None:
    # roles/optional/fabric up to its install task, against a fake ~/go/bin/fabric.
    tasks = _role_tasks("optional/fabric")
    upto = [t for t in tasks if not t["name"].startswith("Install Fabric")]
    pin = _versions()["fabric_version"]
    out = None if installed is None else installed.format(old="v1.0.0", pin=pin, new="v9.0.0")
    _fake_tool(tmp_path / "go" / "bin" / "fabric", out)
    result = _gate_play(tmp_path, upto + [{"ansible.builtin.debug": {"msg": "INSTALL={{ pin_gate_install }}"}}],
                        {"nikos_home": str(tmp_path), "fabric_version": pin})
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"INSTALL={expected}" in result.stdout, result.stdout
    if message:
        assert message in result.stdout
    install = next(t for t in tasks if t["name"].startswith("Install Fabric"))
    assert "pin_gate_install | bool" in install["when"]


@pytest.mark.parametrize("installed,expected,message", GATE_TABLE, ids=GATE_IDS)
def test_act_installs_only_when_missing_or_older(tmp_path: Path, installed, expected, message) -> None:
    tasks = _role_tasks("optional/act")
    upto = [t for t in tasks if not t["name"].startswith("Install act")]
    pin = _versions()["act_version"]
    out = None if installed is None else installed.format(
        old="act version 0.1.0", pin=f"act version {pin.lstrip('v')}", new="act version 9.0.0")
    _fake_tool(tmp_path / ".local" / "bin" / "act", out)
    result = _gate_play(tmp_path, upto + [{"ansible.builtin.debug": {"msg": "INSTALL={{ pin_gate_install }}"}}],
                        {"nikos_home": str(tmp_path), "act_version": pin,
                         "nikos_user_download_dir": str(tmp_path / "dl")})
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"INSTALL={expected}" in result.stdout, result.stdout
    if message:
        assert message in result.stdout
    install = next(t for t in tasks if t["name"].startswith("Install act"))
    assert "pin_gate_install | bool" in install["when"]


def test_every_version_checked_tool_goes_through_the_gate() -> None:
    gated = {}
    for path, task in _all_tasks():
        inc = _module(task, "include_role")
        if inc and inc.get("name") == "pin-gate":
            gated.setdefault(inc["tasks_from"], []).append(str(path.relative_to(REPO)))
    for role in ("optional/fabric", "optional/act", "optional/zsh", "optional/bun", "optional/k8s-tools",
                 "optional/mistral-rs", "optional/openclaw", "agent-dev", "ai-stack", "dev-tools",
                 "cloud-ai-cli"):
        assert f"roles/{role}/tasks/main.yml" in gated["version"], role
    for role in ("dev-tools", "optional/bitnet"):
        assert f"roles/{role}/tasks/main.yml" in gated["git"], role
    for role in ("ai-stack", "agent-dev", "optional/postgres", "optional/mongodb", "optional/redis"):
        assert f"roles/{role}/tasks/main.yml" in gated["pip"], role


@pytest.mark.parametrize(
    "installed,expected",
    [
        ([], ["torch==2.14.1", "numpy==2.5.3", "extra"]),
        ([("torch", "2.0.0"), ("numpy", "2.5.3"), ("extra", "1.0")], ["torch==2.14.1"]),
        ([("torch", "2.14.1+cpu"), ("numpy", "9.0.0"), ("extra", "1.0")], []),
    ],
    ids=["fresh", "one-older", "all-current-or-newer"],
)
def test_pip_gate_installs_pins_and_never_downgrades(tmp_path: Path, installed, expected) -> None:
    pip = tmp_path / "pip"
    listing = json.dumps([{"name": n, "version": v} for n, v in installed])
    pip.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = list ]; then printf '%s\\n' '{listing}'; exit 0; fi\n"
        f"echo \"$@\" > {tmp_path}/calls\n",
        encoding="utf-8",
    )
    pip.chmod(0o755)
    task = {"ansible.builtin.include_role": {"name": "pin-gate", "tasks_from": "pip"},
            "vars": {"pin_gate_pip": str(pip), "pin_gate_names": ["torch", "numpy", "extra"]}}
    result = _gate_play(tmp_path, [task], {"nikos_pip_pins": {"torch": "2.14.1", "numpy": "2.5.3"}})
    assert result.returncode == 0, result.stdout + result.stderr
    calls = tmp_path / "calls"
    if expected:
        assert calls.read_text(encoding="utf-8").split() == ["install"] + expected
    else:
        assert not calls.exists(), calls.read_text(encoding="utf-8")


def _git(*args: str, cwd: Path) -> str:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("at,expected", [("ahead", True), ("pin", True), ("behind", False), ("none", False)])
def test_git_gate_leaves_a_checkout_that_already_contains_the_pin(tmp_path: Path, at: str, expected: bool) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "main", cwd=origin)
    commits = []
    for i in range(3):
        (origin / "f").write_text(str(i), encoding="utf-8")
        _git("add", "f", cwd=origin)
        _git("commit", "-qm", str(i), cwd=origin)
        commits.append(_git("rev-parse", "HEAD", cwd=origin))
    dest = tmp_path / "clone"
    if at != "none":
        _git("clone", "-q", str(origin), str(dest), cwd=tmp_path)
        _git("checkout", "-q", {"ahead": commits[2], "pin": commits[1], "behind": commits[0]}[at], cwd=dest)
    task = {"ansible.builtin.include_role": {"name": "pin-gate", "tasks_from": "git"},
            "vars": {"pin_gate_dest": str(dest), "pin_gate_commit": commits[1]}}
    result = _gate_play(tmp_path, [task, {"ansible.builtin.debug": {"msg": "CURRENT={{ pin_gate_clone_current }}"}}], {})
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"CURRENT={expected}" in result.stdout, result.stdout


# -- The fingerprint check used before any apt key is trusted -----------------


def _key(tmp_path: Path, name: str) -> tuple[Path, str]:
    home = tmp_path / f"gnupg-{name}"
    home.mkdir(mode=0o700)
    env = {**os.environ, "GNUPGHOME": str(home)}
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", f"{name} <{name}@example.invalid>",
                    "ed25519", "sign", "never"], env=env, check=True, capture_output=True)
    out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], env=env, check=True,
                         capture_output=True, text=True).stdout
    fpr = next(line.split(":")[9] for line in out.splitlines() if line.startswith("fpr"))
    key = tmp_path / f"{name}.asc"
    key.write_bytes(subprocess.run(["gpg", "--batch", "--armor", "--export", fpr], env=env, check=True,
                                   capture_output=True).stdout)
    return key, fpr


@pytest.mark.skipif(not shutil.which("gpg"), reason="gpg is required")
def test_fingerprint_check_accepts_the_pinned_key_and_refuses_others(tmp_path: Path) -> None:
    script = str(REPO / "scripts" / "verify-key-fingerprint.sh")
    good, good_fpr = _key(tmp_path, "good")
    other, other_fpr = _key(tmp_path, "other")
    assert subprocess.run(["bash", script, str(good), good_fpr]).returncode == 0
    assert subprocess.run(["bash", script, str(good), good_fpr.lower()]).returncode == 0
    assert subprocess.run(["bash", script, str(other), good_fpr], capture_output=True).returncode == 1
    both = tmp_path / "both.asc"
    both.write_bytes(good.read_bytes() + other.read_bytes())
    # An extra key in the file is refused too: apt would trust it.
    assert subprocess.run(["bash", script, str(both), good_fpr], capture_output=True).returncode == 1
    assert subprocess.run(["bash", script, str(both), good_fpr, other_fpr]).returncode == 0
    junk = tmp_path / "junk.asc"
    junk.write_text("not a key\n", encoding="utf-8")
    assert subprocess.run(["bash", script, str(junk), good_fpr], capture_output=True).returncode == 1
    assert subprocess.run(["bash", script, str(good)], capture_output=True).returncode == 2


@pytest.mark.skipif(not shutil.which("gpg"), reason="gpg is required")
@pytest.mark.parametrize("right", [True, False], ids=["pinned-key", "other-key"])
def test_install_sh_trusts_the_ansible_ppa_only_with_the_pinned_key(tmp_path: Path, right: bool) -> None:
    # install.sh's own _upgrade_ansible, with sudo, apt-get and curl stubbed:
    # curl serves a generated key, and the pin is that key's fingerprint or not.
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    func = re.search(r"^_upgrade_ansible\(\) \{.*?^\}", text, re.M | re.S).group(0)
    key, fpr = _key(tmp_path, "ppa")
    pin = fpr if right else "0" * 40
    script = f"""
set -uo pipefail
log={tmp_path}/calls
sudo() {{ case "$1" in
  install) shift; echo "install $*" >> "$log";;
  tee) cat > {tmp_path}/sources.list;;
  *) echo "$*" >> "$log";;
esac; }}
curl() {{ local out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && {{ out="$2"; shift; }}; shift; done; cp {key} "$out"; }}
ANSIBLE_PPA_KEY_FINGERPRINT={pin}
{func}
_upgrade_ansible
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    calls = (tmp_path / "calls").read_text(encoding="utf-8")
    if right:
        assert result.returncode == 0, result.stderr
        assert "apt-get install -y ansible" in calls
        assert "signed-by=/etc/apt/keyrings/ansible-ppa.gpg" in (tmp_path / "sources.list").read_text()
    else:
        assert result.returncode == 1
        assert "not the pinned" in result.stderr
        assert "apt-get install -y ansible" not in calls and "ansible-ppa.gpg" not in calls


def test_apt_keys_are_staged_root_only_not_in_tmp():
    # /tmp is writable by every local user; a key verified there and trusted
    # in a later step is not the same guarantee as one in a 0700 root dir.
    import re as _re
    for path in sorted((REPO / "roles").glob("**/tasks/*.yml")):
        text = path.read_text(encoding="utf-8")
        if "verify-key-fingerprint.sh" not in text:
            continue
        assert not _re.search(r"/tmp/[\w.-]*(\.asc|\.gpg|\.key|Release\.key)\b", text), path
        assert "nikos_key_staging_dir" in text, path


def test_no_role_downloads_to_a_fixed_tmp_path():
    # get_url skips a file whose checksum already matches; at a fixed /tmp path
    # another local user could plant that file and swap it after the check,
    # before it is executed or unpacked (by root, for Ollama and Nordic).
    hits = []
    for path in sorted((REPO / "roles").glob("**/tasks/*.yml")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "/tmp" in line and not line.lstrip().startswith("#"):
                hits.append(f"{path.relative_to(REPO)}:{n}")
    assert hits == [], hits
