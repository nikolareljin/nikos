#!/usr/bin/env python3
"""nikos-chromium-theme - dark Chromium and Google Chrome in the NikOS colour.

Sets, in every existing profile's Preferences:
  - Classic theme mode instead of GTK: the Chromium snap cannot read the host
    GTK theme (Nordic), so in GTK mode it falls back to light Adwaita;
  - dark colour scheme;
  - #2E3440 (the desktop colour) as the theme seed colour.
These are the values the "Customize Chromium" panel writes, so the user can
change them there afterwards. A browser that is running is skipped: it rewrites
Preferences on exit and would undo the edit.

Exit 0; prints one line per profile: "changed", "ok" or "skipped: <why>".
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SEED = 0xFF2E3440 - (1 << 32)  # ARGB as Chromium stores it: a signed 32-bit int
DARK = 2
TONAL_SPOT = 1

USER_DATA_DIRS = (
    "snap/chromium/common/chromium",
    ".config/chromium",
    ".config/google-chrome",
)

# Both spellings: Chromium migrates the synced "*2" keys to the plain ones.
THEME = {
    "color_scheme": DARK,
    "color_scheme2": DARK,
    "user_color": SEED,
    "user_color2": SEED,
    "color_variant": TONAL_SPOT,
    "color_variant2": TONAL_SPOT,
    "follows_system_colors": False,
}


def running(user_data_dir: Path) -> bool:
    """Chromium holds a SingletonLock symlink to "<host>-<pid>" while it runs.
    A crash or kill leaves it behind, so a lock counts only when that pid is
    alive on this host; a stale one would otherwise skip the profile forever."""
    lock = user_data_dir / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return False
    host, _, pid = target.rpartition("-")
    if host != os.uname().nodename or not pid.isdigit():
        return True  # another machine's lock (shared home): leave it alone
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def apply(prefs_path: Path) -> str:
    try:
        data = json.loads(prefs_path.read_text())
    except (OSError, ValueError) as exc:
        return f"skipped: unreadable ({exc.__class__.__name__})"
    theme = data.setdefault("browser", {}).setdefault("theme", {})
    ext_theme = data.setdefault("extensions", {}).setdefault("theme", {})
    if all(theme.get(k) == v for k, v in THEME.items()) and ext_theme.get("system_theme") == 0:
        return "ok"
    theme.update(THEME)
    ext_theme["system_theme"] = 0  # Classic, not GTK
    tmp = prefs_path.with_suffix(".nikos-tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, prefs_path)
    return "changed"


def main(home: Path) -> int:
    for rel in USER_DATA_DIRS:
        udd = home / rel
        if not udd.is_dir():
            continue
        for prefs in sorted(udd.glob("*/Preferences")):
            if running(udd):
                status = "skipped: browser running; close it and run nikos-chromium-theme"
            else:
                status = apply(prefs)
            print(f"{prefs.parent}: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()))
