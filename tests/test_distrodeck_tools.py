"""Choosing distrodeck tools from distrodeck's own catalog.

NikOS keeps no copy of the catalog: it reads
`distrodeck install-tools --list-catalog --format tsv` and saves the chosen
names next to the optional-bundle selection. Each test covers one way that
could lose or invent a tool:

* a catalog in the wrong shape accepted as if it were one,
* an older distrodeck, without the flag, failing the install,
* the plain prompt returning prose or an unknown name,
* a later write of the selections file dropping the saved list.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts" / "nikos-tools.sh"
NIKOS_CLI = REPO / "scripts" / "nikos"
FIXTURE = REPO / "tests" / "fixtures" / "distrodeck-catalog.tsv"

needs_pty = pytest.mark.skipif(
    shutil.which("script") is None, reason="util-linux `script` is required"
)


def fake_distrodeck(path: Path, *, catalog: bool, log: Path | None = None) -> Path:
    """A distrodeck that has (or, like 0.10.3, lacks) --list-catalog."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if catalog:
        body = (
            'if [ "$2" = "--list-catalog" ]; then cat ' + str(FIXTURE) + "; exit 0; fi\n"
            + (f'echo "$@" >> {log}\n' if log else "")
        )
    else:
        body = 'echo "distrodeck: error: unrecognized arguments: $2" >&2; exit 2\n'
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def bash(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f"source {LIB}\n{script}"], capture_output=True, text=True, timeout=30
    )


def test_catalog_is_read_and_validated(tmp_path: Path) -> None:
    dd = fake_distrodeck(tmp_path / "distrodeck", catalog=True)
    result = bash(f"nikos_tools_catalog {dd}")
    assert result.returncode == 0, result.stderr
    assert result.stdout == FIXTURE.read_text(encoding="utf-8")
    names = bash(f'nikos_tools_names "$(nikos_tools_catalog {dd})"').stdout.split()
    assert names == ["vscode", "zed", "ollama", "claude-code", "vlc", "gimp"]


def test_an_older_distrodeck_is_reported_not_fatal(tmp_path: Path) -> None:
    dd = fake_distrodeck(tmp_path / "distrodeck", catalog=False)
    assert bash(f"nikos_tools_catalog {dd}").returncode == 1


@pytest.mark.parametrize(
    "row",
    ["ides\tIDEs\tvscode\tVS Code\t0", "ides\tIDEs\tvscode\tVS Code\tyes\t1", "\t\t\t\t0\t0"],
    ids=["five-columns", "bad-flag", "no-tool-name"],
)
def test_a_malformed_catalog_is_rejected(tmp_path: Path, row: str) -> None:
    dd = tmp_path / "distrodeck"
    dd.write_text(f"#!/bin/sh\nprintf '%s\\n' '{row}'\n", encoding="utf-8")
    dd.chmod(0o755)
    assert bash(f"nikos_tools_catalog {dd}").returncode == 1


def test_default_is_saved_list_else_installed() -> None:
    tsv = FIXTURE.read_text(encoding="utf-8")
    assert bash(f'nikos_tools_default "$(cat {FIXTURE})" ""').stdout.strip() == "vscode,vlc"
    assert bash(f'nikos_tools_default "$(cat {FIXTURE})" "gimp"').stdout.strip() == "gimp"
    # Stale or unknown names never reach distrodeck; catalog order wins.
    out = bash(f'nikos_tools_filter "$(cat {FIXTURE})" "gimp,nosuch,vscode"').stdout.strip()
    assert out == "vscode,gimp", tsv


def _run_plain(tmp_path: Path, answers: str, *, piped: bool) -> str:
    program = tmp_path / "probe.sh"
    program.write_text(
        f"source {LIB}\n"
        f'tsv="$(cat {FIXTURE})"\n'
        'NIKOS_SELECTED_TOOLS=""\n'
        'nikos_tools_select_plain "$tsv" ""\n'
        "printf '\\nTOOLS=[%s]\\n' \"$NIKOS_SELECTED_TOOLS\"\n",
        encoding="utf-8",
    )
    # piped: the program arrives on bash's stdin, exactly like `curl | bash`.
    cmd = f"cat {program} | bash" if piped else f"bash {program} < /dev/null"
    result = subprocess.run(
        ["script", "-qec", cmd, "/dev/null"],
        input=answers.encode(),
        capture_output=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "TERM": "xterm", "HOME": str(tmp_path)},
    )
    return result.stdout.decode(errors="replace").replace("\r", "")


def _tools(out: str) -> str:
    match = re.search(r"^TOOLS=\[(.*)\]$", out, re.M)
    assert match, out
    return match.group(1)


@needs_pty
@pytest.mark.parametrize("piped", [False, True], ids=["terminal", "piped-stdin"])
def test_plain_selection_round_trips_by_category(tmp_path: Path, piped: bool) -> None:
    # IDEs: keep [vscode]; AI: a typo, then both; Media: none; Graphics: all.
    answers = "\nollamaa\nollama claude-code\n-\n*\n"
    assert _tools(_run_plain(tmp_path, answers, piped=piped)) == "vscode,ollama,claude-code,gimp"


@needs_pty
def test_enter_through_every_category_keeps_what_is_installed(tmp_path: Path) -> None:
    assert _tools(_run_plain(tmp_path, "\n\n\n\n", piped=True)) == "vscode,vlc"


# ── persistence through scripts/nikos ────────────────────────────────────────


def _nikos_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "share" / "nikos"
    (home / "scripts").mkdir(parents=True)
    shutil.copy(LIB, home / "scripts" / "nikos-tools.sh")
    shutil.copytree(REPO / "vars", home / "vars")
    config = tmp_path / ".config" / "nikos"
    config.mkdir(parents=True)
    return home, config


def _cli(tmp_path: Path, home: Path, *args: str, answers: str = "") -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        NIKOS_HOME=str(home),
        HOME=str(tmp_path),
        NIKOS_USE_DIALOG="0",
        PATH="/usr/bin:/bin",
        TERM="xterm",
    )
    cmd = " ".join([f"bash {NIKOS_CLI}", *args])
    return subprocess.run(
        ["script", "-qec", cmd, "/dev/null"],
        input=answers.encode(),
        capture_output=True,
        timeout=60,
        env=env,
    )


def _saved(config: Path) -> dict[str, str]:
    out = subprocess.run(
        ["bash", "-c", f"source {config}/selected-options.env; set | grep ^NIKOS_"],
        capture_output=True,
        text=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


@needs_pty
def test_nikos_add_tools_saves_and_installs_exactly_the_selection(tmp_path: Path) -> None:
    home, config = _nikos_home(tmp_path)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED=music\nNIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED=redis\n"
        "NIKOS_OPTIONAL_TAGS_MIGRATED=1\n",
        encoding="utf-8",
    )
    log = tmp_path / "calls.log"
    fake_distrodeck(tmp_path / "Projects" / "distrodeck" / "distrodeck", catalog=True, log=log)
    result = _cli(tmp_path, home, "add", "tools", answers="-\nollama\n\n-\n")
    out = result.stdout.decode(errors="replace")
    assert result.returncode == 0, out

    saved = _saved(config)
    assert saved["NIKOS_DISTRODECK_TOOLS_SAVED"] == "ollama,vlc", saved
    # The other selections survive the rewrite.
    assert saved["NIKOS_SKIP_TAGS_SAVED"] == "music"
    assert saved["NIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED"] == "redis"
    assert log.read_text(encoding="utf-8").split() == ["install-tools", "--tools", "ollama,vlc"]


@needs_pty
def test_nikos_add_tools_with_an_older_distrodeck_says_so_and_changes_nothing(tmp_path: Path) -> None:
    home, config = _nikos_home(tmp_path)
    (config / "selected-options.env").write_text(
        "NIKOS_SKIP_TAGS_SAVED=\nNIKOS_EXPLICIT_OPTIONAL_TAGS_SAVED=\n"
        "NIKOS_OPTIONAL_TAGS_MIGRATED=1\nNIKOS_DISTRODECK_TOOLS_SAVED=gimp\n",
        encoding="utf-8",
    )
    fake_distrodeck(tmp_path / "Projects" / "distrodeck" / "distrodeck", catalog=False)
    result = _cli(tmp_path, home, "add", "tools")
    out = result.stdout.decode(errors="replace")
    assert "no tool catalog" in out, out
    assert _saved(config)["NIKOS_DISTRODECK_TOOLS_SAVED"] == "gimp"


def test_rewriting_skip_tags_keeps_the_saved_tools(tmp_path: Path) -> None:
    text = NIKOS_CLI.read_text(encoding="utf-8")
    fn = re.search(r"^_save_skip_tags\(\) \{.*?^\}", text, re.M | re.S).group(0)
    env_file = tmp_path / "selected-options.env"
    env_file.write_text("NIKOS_DISTRODECK_TOOLS_SAVED=vscode,gimp\n", encoding="utf-8")
    subprocess.run(
        [
            "bash",
            "-c",
            f'NIKOS_CONFIG_DIR={tmp_path}; SELECTIONS_FILE={env_file}\n{fn}\n_save_skip_tags "a,b" "redis"',
        ],
        check=True,
    )
    saved = _saved(tmp_path)
    assert saved["NIKOS_DISTRODECK_TOOLS_SAVED"] == "vscode,gimp", saved
    assert saved["NIKOS_SKIP_TAGS_SAVED"] == "a,b", saved


def test_dev_tools_role_installs_the_list_not_the_catalog() -> None:
    role = (REPO / "roles" / "dev-tools" / "tasks" / "main.yml").read_text(encoding="utf-8")
    assert "--all" not in role
    assert "nikos_distrodeck_tools" in role
    assert 'version: "{{ distrodeck_version }}"' in role
