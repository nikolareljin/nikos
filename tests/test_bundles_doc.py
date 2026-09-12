"""The tag list in docs/bundles.md is the playbook's, not a copy of it.

`docs/bundles.md` says outright that
`ansible-playbook site.yml -i inventory/local --list-tags` is the only thing
that sees every tag, "which is why that is what any check of this list has to
run" -- and then pastes a copy of that command's output. Nothing ran the
command against the copy, so when three role tags were added the prose and the
count beside it were updated and the pasted block three lines below was not.

This runs the command the document nominates and compares the names, not the
line breaks: rewrapping the block is free, dropping or inventing a tag is not.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "bundles.md"

_TAGS = re.compile(r"TASK TAGS:\s*\[([^\]]*)\]", re.S)


def _names(text: str) -> set[str]:
    match = _TAGS.search(text)
    assert match, f"no 'TASK TAGS: [...]' block found in {text[:200]!r}"
    return {name.strip() for name in match.group(1).split(",") if name.strip()}


def test_documented_tag_list_matches_the_playbook() -> None:
    # Not skipped when ansible is absent. A skip here would read as a pass and
    # reintroduce exactly the blindness this test exists to remove: the whole
    # point is that the document's claim is checked, or the suite says it was
    # not.
    assert shutil.which("ansible-playbook"), (
        "ansible-playbook is required to check docs/bundles.md against the "
        "playbook; install ansible rather than skipping this test"
    )

    result = subprocess.run(
        [
            "ansible-playbook",
            "site.yml",
            "-i",
            "inventory/local",
            "--list-tags",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    playbook = _names(result.stdout)
    documented = _names(DOC.read_text(encoding="utf-8"))

    assert documented == playbook, (
        "docs/bundles.md no longer matches --list-tags. "
        f"missing from the document: {sorted(playbook - documented)}; "
        f"documented but not in the playbook: {sorted(documented - playbook)}"
    )
