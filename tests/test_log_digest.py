"""nikos_log_digest: the summary appended to install and update logs, and the
Chromium theme helper the theming role runs."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "scripts" / "nikos-progress.sh"

LOG = """\
TASK [base : Install packages] *************************************************
ok: [localhost]

TASK [dev-tools : Clone ai-runner] *********************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "Local modifications exist in the destination: /x (force=no)."}
[ERROR]: Task failed: Module failed: Local modifications exist in the destination: /x (force=no).

TASK [desktop : Find configs] **************************************************
[WARNING]: Skipped '/h/.config/xfce4/panel' path due to this access issue
[WARNING]: Skipped '/h/.config/xfce4/panel' path due to this access issue

TASK [theming : Loop] **********************************************************
failed: [localhost] (item=a) => {"ansible_loop_var": "item", "msg": "no \\"quoted\\" luck"}
[WARNING]: Deprecation warnings can be disabled by setting `deprecation_warnings=False` in ansible.cfg.
"""


def digest(tmp_path: Path, text: str) -> str:
    log = tmp_path / "run.log"
    log.write_text(text)
    result = subprocess.run(
        ["bash", "-c", f'source "{LIB}"; nikos_log_digest "{log}" "{ROOT}"'],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_failed_tasks_are_listed_with_their_message(tmp_path):
    out = digest(tmp_path, LOG)
    assert "Failed tasks (2):" in out
    assert "  - [dev-tools : Clone ai-runner] Local modifications exist in the destination: /x (force=no)." in out
    assert '  - [theming : Loop] no \\"quoted\\" luck' in out


def test_warnings_are_counted_once_and_the_ansible_hint_dropped(tmp_path):
    out = digest(tmp_path, LOG)
    assert "Warnings (1 distinct):" in out
    assert "(2x) [WARNING]: Skipped '/h/.config/xfce4/panel'" in out
    assert "Deprecation warnings can be disabled" not in out
    assert "Errors (1 distinct):" in out


def test_a_clean_log_says_none(tmp_path):
    out = digest(tmp_path, "TASK [a : b] ***\nok: [localhost]\n")
    assert "Failed tasks (0):\n  none" in out
    assert "Warnings (0 distinct):\n  none" in out
    assert out.startswith("=== NikOS log digest ===") and "Kernel:" in out


# ── nikos-chromium-theme ────────────────────────────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "nikos_chromium_theme", ROOT / "roles/theming/files/nikos-chromium-theme.py"
)
chromium = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chromium)


def _profile(home: Path, rel: str = "snap/chromium/common/chromium") -> Path:
    prefs = home / rel / "Default" / "Preferences"
    prefs.parent.mkdir(parents=True)
    prefs.write_text(json.dumps({"other": {"kept": True}}))
    return prefs


def test_chromium_profile_gets_dark_classic_seeded_theme(tmp_path, capsys):
    prefs = _profile(tmp_path)
    chromium.main(tmp_path)
    data = json.loads(prefs.read_text())
    theme = data["browser"]["theme"]
    assert theme["color_scheme"] == 2 and theme["follows_system_colors"] is False
    assert theme["user_color"] & 0xFFFFFFFF == 0xFF2E3440
    assert data["extensions"]["theme"]["system_theme"] == 0
    assert data["other"] == {"kept": True}
    assert ": changed" in capsys.readouterr().out


def test_chromium_is_set_once_so_a_later_user_choice_survives(tmp_path, capsys):
    prefs = _profile(tmp_path)
    chromium.main(tmp_path)
    data = json.loads(prefs.read_text())
    data["browser"]["theme"]["color_scheme"] = 1  # user picks light afterwards
    prefs.write_text(json.dumps(data))
    capsys.readouterr()
    chromium.main(tmp_path)  # the next nikos update
    assert "kept" in capsys.readouterr().out
    assert json.loads(prefs.read_text())["browser"]["theme"]["color_scheme"] == 1
    chromium.main(tmp_path, force=True)
    assert json.loads(prefs.read_text())["browser"]["theme"]["color_scheme"] == 2


def test_chromium_running_is_skipped_but_a_stale_lock_is_not(tmp_path, capsys):
    prefs = _profile(tmp_path, ".config/google-chrome")
    lock = prefs.parent.parent / "SingletonLock"
    os.symlink(f"{os.uname().nodename}-{os.getpid()}", lock)
    chromium.main(tmp_path)
    assert "skipped: browser running" in capsys.readouterr().out
    assert "browser" not in json.loads(prefs.read_text())
    lock.unlink()
    os.symlink(f"{os.uname().nodename}-999999999", lock)
    chromium.main(tmp_path)
    assert ": changed" in capsys.readouterr().out


def test_chromium_unreadable_prefs_are_left_alone(tmp_path, capsys):
    prefs = _profile(tmp_path, ".config/chromium")
    prefs.write_text("{not json")
    chromium.main(tmp_path)
    assert "skipped: unreadable" in capsys.readouterr().out
    assert prefs.read_text() == "{not json"


def test_chromium_preferences_keep_their_mode(tmp_path):
    # Chromium writes Preferences 0600; a temp file made with the umask left it
    # 0664, readable by other users.
    prefs = _profile(tmp_path, ".config/chromium")
    prefs.chmod(0o600)
    chromium.main(tmp_path)
    assert prefs.stat().st_mode & 0o777 == 0o600
