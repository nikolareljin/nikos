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


def test_a_catalog_with_appended_columns_is_accepted(tmp_path: Path) -> None:
    # distrodeck's contract is append-only. Requiring exactly six columns made
    # the next added column look like "no catalog" and fall back to --all.
    wide = tmp_path / "wide.tsv"
    wide.write_text(
        "".join(line + "\textra\n" for line in FIXTURE.read_text(encoding="utf-8").splitlines()),
        encoding="utf-8",
    )
    dd = tmp_path / "distrodeck"
    dd.write_text(f"#!/bin/sh\ncat {wide}\n", encoding="utf-8")
    dd.chmod(0o755)
    result = bash(f'c="$(nikos_tools_catalog {dd})" && nikos_tools_names "$c"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["vscode", "zed", "ollama", "claude-code", "vlc", "gimp"]


@needs_pty
def test_dialog_keeps_columns_aligned_when_a_label_is_empty(tmp_path: Path) -> None:
    # IFS=tab read merges empty fields, which moved opt_in into the label.
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "dialog.args"
    (fake / "dialog").write_text(
        f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > {log}\nexit 0\n',
        encoding="utf-8",
    )
    (fake / "dialog").chmod(0o755)
    program = tmp_path / "probe.sh"
    program.write_text(
        f"source {LIB}\n"
        "nikos_tools_select_dialog \"$(printf 'ai\\tAI tools\\tollama\\t\\t1\\t0')\" ''\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["script", "-qec", f"bash {program}", "/dev/null"],
        capture_output=True, timeout=30,
        env={"PATH": f"{fake}:/usr/bin:/bin", "TERM": "xterm"},
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stdout
    args = log.read_text(encoding="utf-8").splitlines()
    i = args.index("ollama")
    assert args[i + 1 : i + 3] == ["[AI tools]  (opt-in)", "off"], args


@pytest.mark.parametrize(
    "row",
    [
        "ides\tIDEs\tvscode\tVS Code\t0",
        "ides\tIDEs\tvscode\tVS Code\tyes\t1",
        "\t\t\t\t0\t0",
        "ides\tIDEs\tvs,code\tVS Code\t0\t0",
        "ides\tIDEs\tvs code\tVS Code\t0\t0",
    ],
    ids=["five-columns", "bad-flag", "no-tool-name", "comma-in-name", "space-in-name"],
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


def _run_plain(tmp_path: Path, answers: str, *, piped: bool, cwd: Path | None = None) -> str:
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
        cwd=cwd,
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
def test_a_pattern_answer_is_not_expanded_against_the_working_directory(tmp_path: Path) -> None:
    # Unquoted word splitting also globbed: with a file named vscode in the
    # current directory, "v*" was accepted as the tool vscode.
    work = tmp_path / "work"
    work.mkdir()
    (work / "vscode").touch()
    out = _run_plain(tmp_path, "v*\n-\n-\n-\n-\n", piped=False, cwd=work)
    assert "Not in IDEs and editors: v*" in out, out
    assert _tools(out) == ""


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


def _run_dev_tools_selection(tmp_path: Path, *, catalog: bool, tools: str) -> list[str]:
    """Run the role's distrodeck tasks against a fake distrodeck."""
    assert shutil.which("ansible-playbook"), "ansible-playbook is required"
    role = (REPO / "roles" / "dev-tools" / "tasks" / "main.yml").read_text(encoding="utf-8")
    start = role.index("- name: Check whether this distrodeck publishes a tool catalog")
    end = role.index("# `distrodeck install-tools` has no upgrade")
    (tmp_path / "tasks.yml").write_text("---\n" + role[start:end], encoding="utf-8")
    (tmp_path / "play.yml").write_text(
        "---\n- hosts: localhost\n  connection: local\n  gather_facts: false\n"
        "  tasks:\n    - ansible.builtin.include_tasks: tasks.yml\n",
        encoding="utf-8",
    )
    log = tmp_path / "calls.log"
    fake_distrodeck(tmp_path / "Projects" / "distrodeck" / "distrodeck", catalog=catalog, log=log)
    if not catalog:
        # The 0.10.3 shape: no --list-catalog, but --all works and is recorded.
        dd = tmp_path / "Projects" / "distrodeck" / "distrodeck"
        dd.write_text(
            "#!/bin/sh\n"
            'if [ "$2" = "--list-catalog" ]; then echo "unrecognized arguments" >&2; exit 2; fi\n'
            f'echo "$@" >> {log}\n',
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            "ansible-playbook", "play.yml", "-i", "localhost,",
            "-e", f"nikos_home={tmp_path}", "-e", f"nikos_distrodeck_tools={tools}",
            "-e", "distrodeck_version=0.10.3",
        ],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_dev_tools_installs_the_saved_list_when_the_catalog_exists(tmp_path: Path) -> None:
    assert _run_dev_tools_selection(tmp_path, catalog=True, tools="ollama,vlc") == [
        "install-tools --tools ollama,vlc"
    ]


def test_dev_tools_installs_nothing_when_the_catalog_exists_and_nothing_was_chosen(
    tmp_path: Path,
) -> None:
    assert _run_dev_tools_selection(tmp_path, catalog=True, tools="") == []


def test_dev_tools_falls_back_to_all_on_an_older_distrodeck(tmp_path: Path) -> None:
    # A saved list cannot be honoured without a catalog to check it against.
    assert _run_dev_tools_selection(tmp_path, catalog=False, tools="ollama") == [
        "install-tools --all"
    ]


def test_dev_tools_clones_a_resolved_release_tag() -> None:
    # Never main: the clone takes what scripts/distrodeck-version.sh resolved.
    role = (REPO / "roles" / "dev-tools" / "tasks" / "main.yml").read_text(encoding="utf-8")
    assert 'version: "{{ dev_tools_distrodeck_resolve.stdout | trim }}"' in role


def test_installer_catalog_clone_brings_the_submodules(tmp_path: Path) -> None:
    # install-tools sources scripts/script-helpers. A clone without it fails
    # the catalog request, so the selection screen never appears. A cache left
    # by the old clone (no submodule) is replaced, not reused.
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    func = re.search(r"^_distrodeck_for_catalog\(\) \{.*?^\}", text, re.M | re.S)
    assert func, "install.sh no longer defines _distrodeck_for_catalog"
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "git.args"
    (fake / "git").write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> {log}\n'
        'dir="${!#}"; mkdir -p "$dir/scripts/script-helpers"\n'
        'printf "#!/bin/sh\\n" > "$dir/distrodeck"; chmod +x "$dir/distrodeck"\n'
        'case " $* " in *" --recurse-submodules "*) touch "$dir/scripts/script-helpers/helpers.sh";; esac\n',
        encoding="utf-8",
    )
    (fake / "git").chmod(0o755)
    stale = tmp_path / "cache" / "nikos" / "distrodeck-0.11.0"
    stale.mkdir(parents=True)
    (stale / "distrodeck").write_text("#!/bin/sh\n", encoding="utf-8")
    (stale / "distrodeck").chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", f"{func.group(0)}\n_distrodeck_for_catalog 0.11.0"],
        capture_output=True, text=True, timeout=30,
        env={"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path),
             "XDG_CACHE_HOME": str(tmp_path / "cache")},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{stale}/distrodeck"
    assert "--recurse-submodules" in log.read_text(encoding="utf-8")
    assert (stale / "scripts" / "script-helpers" / "helpers.sh").exists()
