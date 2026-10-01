"""Boot loader and kernel handling, on a dual-boot machine and in an image build.

The failures these guard against are silent until a reboot: Windows missing
from the GRUB menu, update-grub run inside an ISO chroot against the build
host, a GRUB theme written to a path the image leaves out, and a kernel
upgraded inside the squashfs so it no longer matches the live kernel.
"""

from __future__ import annotations

from pathlib import Path

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


def test_grub_theme_lives_outside_boot() -> None:
    theming = (REPO / "roles" / "theming" / "tasks" / "main.yml").read_text(encoding="utf-8")
    assert "/boot/grub/themes" not in theming
    assert 'GRUB_THEME="/usr/share/grub/themes/Nordic/theme.txt"' in theming


def test_kernel_is_held_for_the_upgrade_and_always_released() -> None:
    base = _tasks("roles/base/tasks/main.yml")
    upgrade = next(t for t in base if t.get("name") == "Upgrade all packages")
    holds = [t for t in upgrade["block"] if "ansible.builtin.dpkg_selections" in t]
    assert holds and holds[0]["ansible.builtin.dpkg_selections"]["selection"] == "hold"
    release = upgrade["always"][0]["ansible.builtin.dpkg_selections"]
    assert release["selection"] == "install"
    assert "linux-(image|generic" in upgrade["vars"]["base_kernel_packages"]
