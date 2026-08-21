"""Guards on the menu entries NikOS configures.

Every entry the Whisker Menu shows runs something. NikOS installs
xubuntu-desktop-minimal, so anything the full xubuntu-desktop merely
Recommends is absent unless NikOS asks for it by name. That gap has now
produced the same user-visible failure twice: "Edit Profile" reported
`Failed to execute child process "mugshot"`, and the menu editor entry
pointed at menulibre with nothing behind it.

These checks are offline and read the repository, not the machine, so a
missing entry fails in CI rather than on someone's desktop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MENU_RC = REPO_ROOT / "roles/desktop/files/whiskermenu-defaults.rc"
VARS = REPO_ROOT / "vars/main.yml"

# Binaries that arrive with the Xfce or Xubuntu metapackages NikOS already
# installs, so they need no separate entry. Anything not listed here has to be
# named in vars/main.yml, which is what the mugshot and menulibre gaps were.
PROVIDED_BY_METAPACKAGES = {
    "dm-tool": "lightdm, in nikos_desktop_extra_packages",
    "xfce4-settings-manager": "xfce4-settings, via xubuntu-desktop-minimal",
    "xflock4": "xfce4-session, via xubuntu-desktop-minimal",
    "xfce4-session-logout": "xfce4-session, via xubuntu-desktop-minimal",
}


def menu_settings() -> dict[str, str]:
    settings = {}
    for line in MENU_RC.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            settings[key.strip()] = value.strip()
    return settings


def packages_nikos_installs() -> set[str]:
    data = yaml.safe_load(VARS.read_text(encoding="utf-8"))
    names: set[str] = set()
    for key, value in data.items():
        if not key.startswith("nikos_desktop"):
            continue
        if isinstance(value, list):
            names.update(str(v) for v in value)
        elif isinstance(value, dict):
            for group in value.values():
                names.update(str(v) for v in group)
    return names


def shown_commands() -> dict[str, str]:
    """command-<name> entries whose button is actually displayed."""
    settings = menu_settings()
    shown = {}
    for key, value in settings.items():
        if not key.startswith("command-"):
            continue
        action = key[len("command-"):]
        if settings.get(f"show-command-{action}", "true") != "true":
            continue
        shown[action] = value.split()[0]
    return shown


def test_the_menu_config_defines_some_commands() -> None:
    assert shown_commands(), "no shown command-* entries found; the parser is wrong"


@pytest.mark.parametrize("action,binary", sorted(shown_commands().items()))
def test_every_shown_menu_command_has_something_behind_it(action: str, binary: str) -> None:
    if binary in PROVIDED_BY_METAPACKAGES:
        return
    installed = packages_nikos_installs()
    assert binary in installed, (
        f"the menu shows '{action}' and runs '{binary}', but nothing installs it. "
        f"Add it to nikos_desktop_extra_packages, or record which metapackage "
        f"provides it in PROVIDED_BY_METAPACKAGES. On xubuntu-desktop-minimal a "
        f"Recommends of the full xubuntu-desktop is not installed, which is how "
        f"mugshot and menulibre both reached users as a failed menu click."
    )


def test_hidden_commands_are_still_defined() -> None:
    """A shown button with no command runs nothing at all."""
    settings = menu_settings()
    for key in settings:
        if key.startswith("show-command-") and settings[key] == "true":
            action = key[len("show-command-"):]
            assert f"command-{action}" in settings, (
                f"show-command-{action} is true but command-{action} is not set"
            )


def test_favourites_do_not_use_the_settings_manager_id_that_does_not_exist() -> None:
    """The desktop id is xfce-settings-manager, with no 4 after xfce.

    The binary is xfce4-settings-manager, which is why the wrong id is easy to
    write and silent: the favourite simply never appears in the menu.
    """
    favourites = menu_settings().get("favorites", "")
    assert "xfce4-settings-manager.desktop" not in favourites.split(","), (
        "favorites uses xfce4-settings-manager.desktop; the file shipped by "
        "xfce4-settings is xfce-settings-manager.desktop"
    )


@pytest.mark.parametrize("entry", sorted(menu_settings().get("favorites", "").split(",")))
def test_favourites_look_like_desktop_ids(entry: str) -> None:
    assert re.fullmatch(r"[A-Za-z0-9_.+-]+\.desktop", entry), (
        f"favourite {entry!r} is not a desktop file id"
    )
