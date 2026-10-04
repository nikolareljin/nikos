"""Boot loader and kernel handling, on a dual-boot machine and in an image build.

The failures these guard against are silent until a reboot: Windows missing
from the GRUB menu, update-grub run inside an ISO chroot against the build
host, a GRUB theme written to a path the image leaves out, and a kernel
upgraded inside the squashfs so it no longer matches the live kernel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def _tasks(path: str) -> list[dict]:
    return yaml.safe_load((REPO / path).read_text(encoding="utf-8"))


def _walk(tasks: list[dict]):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _walk(task.get(key, []))


def test_os_prober_drop_in_is_shipped_on_installed_grub_systems_only() -> None:
    base = _tasks("roles/base/tasks/main.yml")
    block = next(t for t in base if t.get("name") == "Let GRUB list other operating systems")
    assert "nikos_grub_os_prober | bool" in block["when"]
    assert "not (nikos_image_build | default(false) | bool)" in block["when"]
    assert "base_grub_defaults.stat.exists" in block["when"]
    copy = next(t for t in block["block"] if "ansible.builtin.copy" in t)
    assert copy["ansible.builtin.copy"]["dest"] == "/etc/default/grub.d/60-nikos-os-prober.cfg"
    assert "GRUB_DISABLE_OS_PROBER=false" in copy["ansible.builtin.copy"]["content"]
    assert copy["notify"] == "Base_update_grub"
    names = [t.get("ansible.builtin.apt", {}).get("name") for t in block["block"]]
    assert "os-prober" in names


def test_os_prober_defaults_on() -> None:
    data = yaml.safe_load((REPO / "vars" / "main.yml").read_text(encoding="utf-8"))
    assert data["nikos_grub_os_prober"] is True


def test_update_grub_handlers_never_run_in_an_image_build() -> None:
    for path in ("roles/base/handlers/main.yml", "roles/theming/handlers/main.yml"):
        for handler in _tasks(path):
            if handler.get("ansible.builtin.command") == "update-grub":
                assert handler.get("when") == "not (nikos_image_build | default(false) | bool)", path


def test_image_build_is_detected_from_chroot_skel_or_isoforge() -> None:
    site = (REPO / "site.yml").read_text(encoding="utf-8")
    assert "ansible_facts.is_chroot" in site and "nikos_home == '/etc/skel'" in site
    iso = yaml.safe_load((REPO / "isoforge.yml").read_text(encoding="utf-8"))
    assert iso["provisioning"]["ansible"]["extra_vars"]["nikos_image_build"] is True


def test_grub_theme_is_pointed_at_the_chosen_root() -> None:
    theming = (REPO / "roles" / "theming" / "tasks" / "main.yml").read_text(encoding="utf-8")
    assert 'GRUB_THEME="{{ theming_grub_theme_root }}/NikOS/theme.txt"' in theming
    assert "dest: /usr/share/grub/themes/NikOS/" in theming
    assert "dest: /boot/grub/themes/NikOS/" in theming


def test_grub_theme_ships_with_nikos() -> None:
    # The Nordic GTK repo has no GRUB theme; looking for one there skipped the
    # theme on every install. NikOS ships its own, with no download.
    theme = (REPO / "roles" / "theming" / "files" / "grub" / "theme.txt").read_text(encoding="utf-8")
    assert 'desktop-color: "#2E3440"' in theme and "+ boot_menu" in theme
    # The logo is drawn by GRUB's image component: the file must be shipped
    # next to theme.txt as a non-interlaced PNG (GRUB's PNG reader refuses
    # interlaced files).
    assert 'file = "logo.png"' in theme
    logo = REPO / "roles" / "theming" / "files" / "grub" / "logo.png"
    head = logo.read_bytes()[:33]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    assert head[28] == 0, "logo.png must not be interlaced"
    theming = (REPO / "roles" / "theming" / "tasks" / "main.yml").read_text(encoding="utf-8")
    assert "EliverLara/Nordic.git" not in theming
    assert "not found in the cloned repo" not in theming


@pytest.mark.parametrize(
    "mounts,root_types,image,expected",
    [
        (["/"], ["part", "disk"], False, "/usr/share/grub/themes"),
        (["/", "/boot"], ["part", "disk"], False, "/boot/grub/themes"),
        (["/", "/boot/efi"], ["crypt", "part", "disk"], False, "/boot/grub/themes"),
        (["/", "/boot/efi"], ["part", "disk"], False, "/usr/share/grub/themes"),
        (["/", "/boot"], ["crypt", "part"], True, "/usr/share/grub/themes"),
    ],
    ids=["plain", "separate-boot", "luks-root", "efi-only", "image-build"],
)
def test_grub_theme_path_selection(tmp_path, mounts, root_types, image, expected) -> None:
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    theming = (REPO / "roles" / "theming" / "tasks" / "main.yml").read_text(encoding="utf-8")
    start = theming.index("- name: Choose where GRUB reads the theme from")
    end = theming.index("- name: Copy the NikOS GRUB theme to /boot")
    (tmp_path / "tasks.yml").write_text("---\n" + theming[start:end], encoding="utf-8")
    (tmp_path / "play.yml").write_text(
        "---\n- hosts: localhost\n  connection: local\n  gather_facts: false\n  tasks:\n"
        "    - ansible.builtin.include_tasks: tasks.yml\n"
        "    - ansible.builtin.debug:\n        msg: \"ROOT={{ theming_grub_theme_root }}\"\n",
        encoding="utf-8",
    )
    extra = json.dumps(
        {
            "theming_mount_points": mounts,
            "theming_root_types": root_types,
            "nikos_image_build": image,
        }
    )
    result = subprocess.run(
        ["ansible-playbook", "play.yml", "-i", "localhost,", "-e", extra],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ROOT={expected}" in result.stdout, result.stdout


def test_kernel_is_held_for_the_upgrade_and_always_released() -> None:
    base = _tasks("roles/base/tasks/main.yml")
    upgrade = next(t for t in base if t.get("name") == "Upgrade all packages")
    holds = [t for t in upgrade["block"] if "ansible.builtin.dpkg_selections" in t]
    assert holds and holds[0]["ansible.builtin.dpkg_selections"]["selection"] == "hold"
    release = upgrade["always"][0]["ansible.builtin.dpkg_selections"]
    assert release["selection"] == "install"
    assert "linux-(image|generic" in upgrade["vars"]["base_kernel_packages"]


def test_root_stack_probe_sees_luks_under_lvm_on_btrfs(tmp_path) -> None:
    # Real lsblk/findmnt shapes for btrfs on LVM on LUKS: findmnt without -v
    # appends the subvolume ("[/@]"), which lsblk rejects, and lsblk without -r
    # prefixes nested layers with tree glyphs, so "crypt" was never a line.
    task = next(
        t for t in _tasks("roles/theming/tasks/main.yml")
        if t.get("name") == "Find the block devices under the root filesystem"
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "findmnt").write_text(
        "#!/bin/bash\n"
        'case "$1" in *v*) echo /dev/mapper/vg-root;; *) echo "/dev/mapper/vg-root[/@]";; esac\n',
        encoding="utf-8",
    )
    (fake / "lsblk").write_text(
        "#!/bin/bash\n"
        'dev="${!#}"; [[ "$dev" == *"["* ]] && { echo "lsblk: $dev: not a block device" >&2; exit 32; }\n'
        'case "$1" in *r*) printf "lvm\\ncrypt\\npart\\ndisk\\n";;\n'
        '  *) printf "lvm\\n\\xe2\\x94\\x94\\xe2\\x94\\x80crypt\\n  \\xe2\\x94\\x94\\xe2\\x94\\x80part\\n";; esac\n',
        encoding="utf-8",
    )
    for tool in ("findmnt", "lsblk"):
        (fake / tool).chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", task["ansible.builtin.shell"]],
        capture_output=True, text=True, timeout=30,
        env={"PATH": f"{fake}:/usr/bin:/bin"},
    )
    assert "crypt" in result.stdout.splitlines(), result.stdout


@pytest.mark.parametrize(
    "versions,expected",
    [
        ([21, 17], "/usr/lib/jvm/java-21-openjdk-amd64/bin/java"),
        ([8, 21], "/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java"),
    ],
    ids=["21-first", "8-first"],
)
def test_java_alternative_matches_the_registered_path(tmp_path, versions, expected) -> None:
    # OpenJDK 8 registers its java alternative under jre/bin. A path the
    # alternatives system does not know is added as a new entry instead.
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    task = next(
        t for t in _tasks("roles/optional/java/tasks/main.yml")
        if "community.general.alternatives" in t
    )
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {**task["vars"], "ansible_architecture": "x86_64",
                 "nikos_java_versions": versions, "item": "java"},
        "tasks": [{"ansible.builtin.debug": {
            "msg": "PATH=" + task["community.general.alternatives"]["path"]}}],
    }]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play), encoding="utf-8")
    result = subprocess.run(
        ["ansible-playbook", "play.yml", "-i", "localhost,"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PATH={expected}" in result.stdout, result.stdout
