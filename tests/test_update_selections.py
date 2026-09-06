"""Persisted optional-bundle selections and the `nikos update` replay.

`nikos update` has to refresh the optional bundles the user actually chose.
Those bundles are tagged `[never, <name>]` in site.yml, so Ansible runs them
only when their tag is named explicitly - the saved `--skip-tags` list cannot
reach them. 0.6.5 therefore persists a positive selection
(`NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED`) and replays it as a second tagged
playbook pass.

Three failure modes are specific to this design and are what these tests pin:

* Installs made by 0.6.4 have no positive selection at all - the old installer
  saved skip tags only - so it has to be reconstructed once, from the run logs,
  and the reconstruction must then latch so later runs do not re-derive it.
* `_save_skip_tags` is called with one argument from several places. If it did
  not carry the existing selection forward, every `nikos add` of a
  skip-tag-only bundle would silently drop the saved optional selection.
* The replay pass must run without the saved skip tags. Ansible gives skip tags
  precedence over selected tags, so a saved `ai-gemini` skip would skip the
  shared Node tasks that the selected `openclaw` role depends on.

The release-upgrade case is the reason `_exec_update_continuation` exists: the
running CLI is the copy the *previous* release installed at /usr/local/bin/nikos,
and its already-parsed `cmd_update` knows nothing about the replay.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NIKOS = REPO_ROOT / "scripts" / "nikos"

SELECTION_HELPERS = (
    "_get_default_skip_tags",
    "_save_skip_tags",
    "_migrate_saved_optional_tags",
    "_get_saved_optional_tags",
    "_add_optional_tag",
    "_remove_skip_tag",
)


def extract_helper(name: str) -> str:
    """Pull a bash function out of scripts/nikos so it can be run on its own."""
    text = NIKOS.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"scripts/nikos no longer defines {name}"
    return match.group(0)


def run_bash(body: str, tmp_path: Path, names=SELECTION_HELPERS):
    """Run `body` with the named scripts/nikos helpers in scope."""
    config_dir = tmp_path / "config"
    log_dir = config_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    program = tmp_path / "probe.sh"
    program.write_text(
        "set -euo pipefail\n"
        f'NIKOS_CONFIG_DIR={str(config_dir)!r}\n'
        'SELECTIONS_FILE="${NIKOS_CONFIG_DIR}/selected-options.env"\n'
        f'NIKOS_LOG_DIR={str(log_dir)!r}\n'
        "print_info() { echo \"INFO:$*\"; }\n"
        "print_error() { echo \"ERROR:$*\" >&2; }\n"
        + "\n\n".join(extract_helper(name) for name in names)
        + "\n\n"
        + body,
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(program)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    return result, config_dir


def read_selections(config_dir: Path) -> dict[str, str]:
    text = (config_dir / "selected-options.env").read_text(encoding="utf-8")
    values = {}
    for line in text.splitlines():
        key, _, raw = line.partition("=")
        # The file is written with %q, so let bash undo the quoting.
        values[key] = subprocess.run(
            ["bash", "-c", f'printf "%s" {raw}'], capture_output=True, text=True
        ).stdout
    return values



# ── Migrating a 0.6.4 install ────────────────────────────────────────────────


def test_migration_derives_selections_from_run_logs(tmp_path):
    """A 0.6.4 install saved skip tags only; the selection is rebuilt from logs."""
    config = tmp_path / "config"
    (config / "logs").mkdir(parents=True)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED='network,music'\n", encoding="utf-8"
    )
    (config / "logs" / "nikos-20260101-000000-playbook.log").write_text(
        "Playbook start: ansible-playbook --tags redis,postgres site.yml\n",
        encoding="utf-8",
    )

    result, config_dir = run_bash("_get_saved_optional_tags", tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "redis,postgres"
    saved = read_selections(config_dir)
    assert saved["NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED"] == "redis,postgres"
    assert saved["NIKOS_OPTIONAL_TAGS_MIGRATED"] == "1"
    # The skip list the user chose at install time must survive the migration.
    assert saved["NIKOS_SKIP_TAGS_SAVED"] == "network,music"


def test_migration_latches_even_when_no_logs_survive(tmp_path):
    """With nothing to derive from, the migration records that it has run.

    Otherwise every later `nikos update` would re-grep the logs, and a bundle
    name appearing in an unrelated log line would silently become a selection.
    """
    config = tmp_path / "config"
    (config / "logs").mkdir(parents=True)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED='network'\n", encoding="utf-8"
    )

    result, config_dir = run_bash("_get_saved_optional_tags", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
    assert read_selections(config_dir)["NIKOS_OPTIONAL_TAGS_MIGRATED"] == "1"

    # A log written after the migration must not retroactively add a selection.
    (config / "logs" / "later.log").write_text("--tags redis\n", encoding="utf-8")
    result, config_dir = run_bash("_get_saved_optional_tags", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_migration_leaves_an_existing_selection_alone(tmp_path):
    config = tmp_path / "config"
    (config / "logs").mkdir(parents=True)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED='network'\n"
        "NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED='redis'\n"
        "NIKOS_OPTIONAL_TAGS_MIGRATED=''\n",
        encoding="utf-8",
    )
    (config / "logs" / "run.log").write_text("--tags postgres\n", encoding="utf-8")

    result, _ = run_bash("_get_saved_optional_tags", tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "redis"


def test_get_saved_optional_tags_without_a_selections_file(tmp_path):
    result, _ = run_bash("_get_saved_optional_tags", tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


# ── Preserving the selection through later writes ────────────────────────────


def test_save_skip_tags_carries_the_selection_forward(tmp_path):
    """One-argument `_save_skip_tags` must not drop the optional selection."""
    config = tmp_path / "config"
    (config / "logs").mkdir(parents=True)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED='network,music'\n"
        "NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED='redis,postgres'\n"
        "NIKOS_OPTIONAL_TAGS_MIGRATED='1'\n",
        encoding="utf-8",
    )

    result, config_dir = run_bash('_save_skip_tags "music"', tmp_path)

    assert result.returncode == 0, result.stderr
    saved = read_selections(config_dir)
    assert saved["NIKOS_SKIP_TAGS_SAVED"] == "music"
    assert saved["NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED"] == "redis,postgres"
    assert saved["NIKOS_OPTIONAL_TAGS_MIGRATED"] == "1"


def test_remove_skip_tag_keeps_the_selection(tmp_path):
    """`nikos add network` removes a skip tag; it must not clear selections."""
    config = tmp_path / "config"
    (config / "logs").mkdir(parents=True)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED='network,music'\n"
        "NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED='redis'\n"
        "NIKOS_OPTIONAL_TAGS_MIGRATED='1'\n",
        encoding="utf-8",
    )

    result, config_dir = run_bash('_remove_skip_tag "network"', tmp_path)

    assert result.returncode == 0, result.stderr
    saved = read_selections(config_dir)
    assert saved["NIKOS_SKIP_TAGS_SAVED"] == "music"
    assert saved["NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED"] == "redis"
    assert saved["NIKOS_OPTIONAL_TAGS_MIGRATED"] == "1"


def test_add_optional_tag_appends_once(tmp_path):
    config = tmp_path / "config"
    (config / "logs").mkdir(parents=True)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED='network'\n"
        "NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED='redis'\n"
        "NIKOS_OPTIONAL_TAGS_MIGRATED='1'\n",
        encoding="utf-8",
    )

    result, config_dir = run_bash(
        '_add_optional_tag "postgres"\n_add_optional_tag "postgres"\n', tmp_path
    )

    assert result.returncode == 0, result.stderr
    saved = read_selections(config_dir)
    assert saved["NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED"] == "redis,postgres"
    assert saved["NIKOS_SKIP_TAGS_SAVED"] == "network"


# ── Every `never`-tagged bundle `nikos add` accepts is persisted ─────────────

# Skip-tag-only bundles. These roles run on a bare playbook and are excluded by
# name, so `_remove_skip_tag` is the whole of their state; they carry no `never`
# tag and so need no positive selection to be replayed.
SKIP_TAG_ONLY_BUNDLES = {"network", "music", "education"}


def _cmd_add_case_lists() -> tuple[set[str], set[str]]:
    text = NIKOS.read_text(encoding="utf-8")
    body = re.search(r"^cmd_add\(\) \{.*?^\}", text, re.M | re.S)
    assert body, "scripts/nikos no longer defines cmd_add"
    patterns = re.findall(r"^\s*((?:[\w-]+ \| )+[\w-]+)\)", body.group(0), re.M)
    assert len(patterns) == 2, f"expected two case lists in cmd_add, got {patterns}"
    accepted, persisted = ({p.strip() for p in group.split("|")} for group in patterns)
    return accepted, persisted


def test_every_never_tagged_bundle_add_accepts_is_persisted():
    """A bundle `nikos add` installs but never persists cannot be updated later.

    Its tasks carry `never`, so the update replay is the only thing that can
    reach them, and the replay runs from the saved selection.
    """
    accepted, persisted = _cmd_add_case_lists()

    missing = accepted - persisted - SKIP_TAG_ONLY_BUNDLES
    assert not missing, f"accepted by `nikos add` but never persisted: {sorted(missing)}"
    assert not persisted - accepted, "persisted a bundle `nikos add` rejects"


def test_all_persisted_bundles_are_known_to_the_migration():
    """The migration has to be able to reconstruct any bundle add can persist."""
    _, persisted = _cmd_add_case_lists()
    migration = extract_helper("_migrate_saved_optional_tags")
    known = set(re.search(r"optional_role_tags=\((.*?)\)", migration, re.S).group(1).split())

    assert not persisted - known, f"migration cannot recover: {sorted(persisted - known)}"


# ── The release-upgrade continuation ─────────────────────────────────────────


def _run_continuation(tmp_path: Path, checkout_cli: str | None, running_cli: str):
    """Drive the helper with a checkout CLI and a running CLI of known content."""
    home = tmp_path / "nikos-home"
    (home / "scripts").mkdir(parents=True)
    if checkout_cli is not None:
        (home / "scripts" / "nikos").write_text(checkout_cli, encoding="utf-8")
    running = tmp_path / "running-nikos"
    running.write_text(running_cli, encoding="utf-8")
    program = tmp_path / "continuation.sh"
    program.write_text(
        "set -euo pipefail\n"
        f'NIKOS_HOME={str(home)!r}\n'
        # scripts/nikos resolves this at startup from BASH_SOURCE; the probe
        # stands in for a CLI installed at that path.
        f'NIKOS_CLI_PATH={str(running)!r}\n'
        "print_info() { echo \"INFO:$*\"; }\n"
        + extract_helper("_exec_update_continuation")
        + "\n\n_exec_update_continuation\necho 'NO-EXEC'\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(program)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )


def test_continuation_execs_the_checked_out_cli_when_it_differs(tmp_path):
    """The 0.6.4 -> 0.6.5 case: the running CLI predates the new checkout."""
    new_cli = "echo \"EXECED:${NIKOS_UPDATE_CONTINUATION:-unset}:$*\"\n"
    result = _run_continuation(tmp_path, new_cli, "old cli\n")

    assert result.returncode == 0, result.stderr
    assert "EXECED:1:update" in result.stdout, result.stdout
    # exec replaces the process, so nothing after the call may run.
    assert "NO-EXEC" not in result.stdout


def test_continuation_is_a_no_op_when_the_cli_is_unchanged(tmp_path):
    """The steady state - no release change - must not re-exec anything."""
    same = "echo 'EXECED'\n"
    result = _run_continuation(tmp_path, same, same)

    assert result.returncode == 0, result.stderr
    assert "EXECED" not in result.stdout
    assert "NO-EXEC" in result.stdout


def test_continuation_is_a_no_op_without_a_checked_out_cli(tmp_path):
    result = _run_continuation(tmp_path, None, "old cli\n")

    assert result.returncode == 0, result.stderr
    assert "NO-EXEC" in result.stdout


# ── cmd_update: sync, then the two playbook passes ───────────────────────────


def _run_cmd_update(tmp_path: Path, continuation: bool, optional_tags: str):
    home = tmp_path / "nikos-home"
    (home / ".git").mkdir(parents=True)
    calls = tmp_path / "calls.log"
    program = tmp_path / "update.sh"
    program.write_text(
        "set -euo pipefail\n"
        f'NIKOS_HOME={str(home)!r}\n'
        'REPO_URL="https://example.invalid/nikos"\n'
        'REPO_SYNC_HELPERS="/nonexistent"\n'
        f'CALLS={str(calls)!r}\n'
        "print_info() { echo \"INFO:$*\"; }\n"
        "print_error() { echo \"ERROR:$*\" >&2; }\n"
        '_resolve_update_ref() { printf "0.6.5\\n"; }\n'
        '_sync_repo_to_ref() { echo "sync:$*" >> "${CALLS}"; }\n'
        '_playbook() { echo "playbook:$*" >> "${CALLS}"; }\n'
        '_exec_update_continuation() { echo "continuation" >> "${CALLS}"; }\n'
        f'_get_saved_optional_tags() {{ printf "%s\\n" {optional_tags!r}; }}\n'
        + extract_helper("cmd_update")
        + "\n\ncmd_update\n",
        encoding="utf-8",
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    if continuation:
        env["NIKOS_UPDATE_CONTINUATION"] = "1"
    result = subprocess.run(
        ["bash", str(program)], capture_output=True, text=True, env=env
    )
    recorded = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result, recorded


def test_update_syncs_then_runs_both_playbook_passes(tmp_path):
    result, calls = _run_cmd_update(tmp_path, continuation=False, optional_tags="redis,postgres")

    assert result.returncode == 0, result.stderr
    assert calls[0].startswith("sync:0.6.5"), calls
    # The continuation check belongs to the sync branch: only a run that
    # actually re-synced the checkout can be running a CLI the update replaced.
    assert calls[1] == "continuation", calls
    assert calls[-2:] == [
        "playbook:-e nikos_update_mode=true",
        # No saved skip tags on the replay: Ansible gives skip tags precedence
        # over selected tags, so a saved skip would defeat the selection.
        "playbook:--no-saved-skip-tags -e nikos_update_mode=true --tags redis,postgres",
    ], calls


def test_update_skips_the_replay_when_nothing_optional_is_selected(tmp_path):
    result, calls = _run_cmd_update(tmp_path, continuation=False, optional_tags="")

    assert result.returncode == 0, result.stderr
    assert calls.count("playbook:-e nikos_update_mode=true") == 1
    assert not [c for c in calls if "--tags" in c], calls


def test_continuation_does_not_re_sync_the_checkout(tmp_path):
    """The CLI that exec'd us already synced; syncing again would re-stash."""
    result, calls = _run_cmd_update(tmp_path, continuation=True, optional_tags="redis")

    assert result.returncode == 0, result.stderr
    assert not [c for c in calls if c.startswith("sync:")], calls
    assert "continuation" not in calls, "must not recurse into another continuation"
    assert calls == [
        "playbook:-e nikos_update_mode=true",
        "playbook:--no-saved-skip-tags -e nikos_update_mode=true --tags redis",
    ], calls
