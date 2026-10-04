## What changed and why

<!-- One or two sentences each. Link the issue: "Fixes #123". -->

## How it was tested

<!-- Commands you ran and on which Ubuntu release(s). -->

- [ ] `python3 -m pytest tests -q`
- [ ] `ansible-lint site.yml`
- [ ] `shellcheck` on changed scripts (see CONTRIBUTING.md for CI's file list)
- [ ] A test under `tests/` fails without this change
- [ ] Ran on a real or virtual machine: release(s): <!-- 22.04 / 24.04 / 26.04 -->

## Checklist

- [ ] A line under `## [Unreleased]` in CHANGELOG.md
- [ ] Anything installed comes from a verified source, pinned in `vars/versions.yml` with its sha256 or key fingerprint (no `curl | sh`, `@latest`, `releases/latest`)
- [ ] `nikos update` does not downgrade anything newer the user installed
- [ ] Works on 22.04, 24.04 and 26.04, or skips with a clear message where a release lacks something
- [ ] Docs updated if behaviour or settings changed
