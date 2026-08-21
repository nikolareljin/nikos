"""Guards on the theming role's icon handling.

The menu icon is installed system-wide, but GTK resolves user-level icon
directories first. A reinstall that only rewrites /usr/share therefore fixes
nothing on a machine that has a copy in either of them, which is exactly how a
already-fixed icon kept coming up as a missing-image placeholder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
THEMING_TASKS = REPO_ROOT / "roles/theming/tasks/main.yml"

# In GTK's search order, ahead of /usr/share/icons.
USER_ICON_PATHS = [
    "{{ nikos_home }}/.icons/hicolor/scalable/apps/nikos-menu.svg",
    "{{ nikos_home }}/.local/share/icons/hicolor/scalable/apps/nikos-menu.svg",
]


@pytest.fixture(scope="module")
def tasks() -> str:
    return THEMING_TASKS.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", USER_ICON_PATHS)
def test_reinstall_clears_shadowing_user_icons(tasks: str, path: str) -> None:
    assert path in tasks, (
        f"the theming role no longer clears {path}, so a copy there would "
        "shadow the system icon and a reinstall would change nothing"
    )


def test_shadowing_icons_are_removed_not_just_detected(tasks: str) -> None:
    assert "Remove user-level copies of the NikOS menu icon" in tasks
    assert "theming_shadowing_menu_icons" in tasks


def test_user_icon_cache_is_rebuilt_after_removal(tasks: str) -> None:
    """A cache still listing the icon resolves a name with nothing behind it."""
    assert "gtk-update-icon-cache --force --ignore-theme-index" in tasks, (
        "removing the file without rebuilding the cache leaves GTK resolving "
        "an icon that is no longer on disk"
    )


def test_system_icon_install_still_refreshes_the_system_cache(tasks: str) -> None:
    assert "/usr/share/icons/hicolor/scalable/apps/nikos-menu.svg" in tasks
    assert "Theming_update_icon_cache" in tasks
