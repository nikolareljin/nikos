# Changelog

All notable changes to NikOS are documented here.

## [0.2.0] — 2026-04-04

### Added
- **script-helpers submodule** (`scripts/script-helpers`) — vendored as a git submodule
  pinned to the `production` branch of [nikolareljin/script-helpers](https://github.com/nikolareljin/script-helpers).
  Provides shared Bash utilities (logging, dialog, deps, etc.) used by installer and management scripts.
- **Dialog TUI installer** — `install.sh` now presents a `dialog` checklist for optional bundle
  selection instead of plain `read` prompts.
- **Persistent local repo** — installer clones NikOS with `--recurse-submodules` to
  `~/.local/share/nikos`; `nikos update` uses `git pull` + submodule sync instead of `ansible-pull`.
- **`dialog` package** added to base role core dependencies.
- **Submodule init post-task** in `site.yml` — ensures `scripts/script-helpers` is initialized
  after every playbook run.
- **`nikos doctor`** now checks for `dialog` and the local repo/submodule presence.
- **CHANGELOG** — this file.

### Changed
- **Repo renamed** from `nikos-os` to `nikos` (directory and GitHub repo).
- **`nikos update`** now runs `git pull --ff-only` + `git submodule update --init --recursive`
  + `ansible-playbook` (was `ansible-pull`).
- **`scripts/nikos` CLI** sources `script-helpers` logging for consistent output;
  falls back to plain `echo` if submodule is not yet initialized.
- Version bumped `0.1.0` → `0.2.0` in `vars/main.yml`, `install.sh`, and `scripts/nikos`.

## [0.1.0] — 2026-04-02

Initial release.
- Ansible playbook for Ubuntu 24.04 LTS: Xfce 4 + Nordic theme, full AI stack
  (Ollama, aider, Claude Code, Gemini CLI, Miniforge/conda), VS Code with AI extensions,
  developer tools via distrodeck, GitHub first-login wizard.
- `nikos` CLI: `setup`, `update`, `add`, `status`, `doctor`.
- CI: ansible-lint, dry-run test, GitHub Release workflow.
