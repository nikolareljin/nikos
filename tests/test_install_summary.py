"""Guards on the install summary's PLAY RECAP parsing.

An install can run the playbook more than once: the main run, then a second
run for the optional bundles. Each prints its own PLAY RECAP. Reading them
with a bare grep returned one line per recap, so the count became "177\\n10"
instead of a number. That broke the summary box, and worse, `[[ "0\\n1" -gt 0 ]]`
raises a syntax error and evaluates false, so a genuine failure in the second
run was never reported.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [REPO_ROOT / "install.sh", REPO_ROOT / "scripts" / "nikos"]

TWO_RECAPS = textwrap.dedent(
    """\
    PLAY RECAP *********************************************************************
    localhost                  : ok=177  changed=13   unreachable=0    failed=0    skipped=34
    \n
    PLAY RECAP *********************************************************************
    localhost                  : ok=10   changed=3    unreachable=0    failed=1    skipped=1
    """
)

ONE_RECAP = textwrap.dedent(
    """\
    PLAY RECAP *********************************************************************
    localhost                  : ok=42   changed=7    unreachable=0    failed=0    skipped=2
    """
)


def extract_helper(script: Path) -> str:
    """Pull _recap_total out of a script so it can be run on its own."""
    text = script.read_text(encoding="utf-8")
    match = re.search(r"^_recap_total\(\) \{.*?^\}", text, re.M | re.S)
    assert match, f"{script.name} no longer defines _recap_total"
    return match.group(0)


def run_helper(script: Path, log: Path, field: str) -> str:
    program = f"{extract_helper(script)}\n_recap_total {field} {log}\n"
    result = subprocess.run(
        ["bash", "-c", program], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == "", f"helper wrote to stderr: {result.stderr}"
    return result.stdout.strip()


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
@pytest.mark.parametrize(
    "field,expected", [("ok", "187"), ("changed", "16"), ("failed", "1"), ("unreachable", "0")]
)
def test_counts_are_totalled_across_every_recap(
    script: Path, tmp_path: Path, field: str, expected: str
) -> None:
    log = tmp_path / "install.log"
    log.write_text(TWO_RECAPS, encoding="utf-8")
    assert run_helper(script, log, field) == expected


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
@pytest.mark.parametrize("field", ["ok", "changed", "failed", "unreachable"])
def test_result_is_always_a_single_integer(script: Path, tmp_path: Path, field: str) -> None:
    """A multi-line value breaks the summary box and the `-gt` comparisons."""
    for name, body in (("two", TWO_RECAPS), ("one", ONE_RECAP), ("empty", "")):
        log = tmp_path / f"{name}.log"
        log.write_text(body, encoding="utf-8")
        value = run_helper(script, log, field)
        assert "\n" not in value, f"{name}: {field} came back multi-line"
        assert value.isdigit(), f"{name}: {field} is not a number: {value!r}"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_a_failure_in_a_later_run_is_still_counted(script: Path, tmp_path: Path) -> None:
    """The original defect: the second run failed and the summary said nothing."""
    log = tmp_path / "install.log"
    log.write_text(TWO_RECAPS, encoding="utf-8")
    assert int(run_helper(script, log, "failed")) > 0
