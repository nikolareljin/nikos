#!/usr/bin/env python3
"""nikos-chromium-theme - dark Chromium and Google Chrome in the NikOS colour.

Sets, in every existing profile's Preferences:
  - Classic theme mode instead of GTK: the Chromium snap cannot read the host
    GTK theme (Nordic), so in GTK mode it falls back to light Adwaita;
  - dark colour scheme;
  - #2E3440 (the desktop colour) as the theme seed colour.
These are the values the "Customize Chromium" panel writes, so the user can
change them there afterwards. Each profile is set once, recorded in
~/.local/state/nikos/chromium-themed, so `nikos update` does not undo a theme
the user picked later; --force sets it again. A browser that is running is
skipped: it rewrites Preferences on exit and would undo the edit.

Exit 0; prints one line per profile: "changed", "ok", "kept" or "skipped: <why>".
"""

from __future__ import annotations

import json
import os
import stat
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
    # Keep Chromium's mode (0600): a temp file made with the default umask
    # would leave the profile's Preferences readable by other users.
    tmp = prefs_path.with_suffix(".nikos-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, stat.S_IMODE(prefs_path.stat().st_mode))
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, prefs_path)
    return "changed"


def main(home: Path, force: bool = False) -> int:
    state = home / ".local" / "state" / "nikos" / "chromium-themed"
    done = set(state.read_text().splitlines()) if state.exists() else set()
    for rel in USER_DATA_DIRS:
        udd = home / rel
        if not udd.is_dir():
            continue
        for prefs in sorted(udd.glob("*/Preferences")):
            profile = str(prefs.parent)
            if profile in done and not force:
                status = "kept (set once already; --force sets it again)"
            elif running(udd):
                status = "skipped: browser running; close it and run nikos-chromium-theme"
            else:
                status = apply(prefs)
                if status in ("changed", "ok"):
                    done.add(profile)
            print(f"{profile}: {status}")
    if done:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("".join(f"{p}\n" for p in sorted(done)))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    sys.exit(main(Path(args[0]) if args else Path.home(), force="--force" in sys.argv[1:]))
