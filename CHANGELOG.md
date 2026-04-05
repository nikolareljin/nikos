# Changelog

All notable changes to NikOS are documented here.

## [0.2.0] — 2026-04-05

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
- **Optional AI tool selection** in `install.sh` — separate AI checklist with default-on entries
  for local AI stack, Gemini CLI, Claude Code, Copilot CLI, ai-runner, and AI-focused VS Code extensions.
- **System-wide Xfce defaults** for Nordic/Papirus theme application, wallpaper, and Whisker Menu branding.
- **Whisker Menu defaults** — system-wide menu button branding now points at `/usr/share/nikos/wallpaper.png`.

### Changed
- **Repo renamed** from `nikos-os` to `nikos` (directory and GitHub repo).
- **`nikos update`** now runs `git pull --ff-only` + `git submodule update --init --recursive`
  + `ansible-playbook` (was `ansible-pull`).
- **`scripts/nikos` CLI** sources `script-helpers` logging for consistent output;
  falls back to plain `echo` if submodule is not yet initialized.
- Version bumped `0.1.0` → `0.2.0` in `vars/main.yml`, `install.sh`, and `scripts/nikos`.
- **`./test` installer flow** now stages the local NikOS source tree into the VM, runs the local
  bootstrap installer with a TTY, and verifies the installed system using checks aligned with optional installs.
- **`nikos doctor`** now distinguishes optional or first-login-dependent components from hard failures.
- **Developer tools install flow** now uses distrodeck's interactive TUI instead of forcing `install-tools --all`.
- **VS Code extension defaults** now include `nikolareljin.leak-lock`, and AI-oriented extensions
  are tracked separately for optional installation.

### Fixed
- **Installer bootstrap and repo sync** now surface pull/submodule/stash errors cleanly instead of
  exiting abruptly under `set -e`.
- **Fresh-install submodule handling** now retries `script-helpers` initialization explicitly and
  fails clearly when the required helper checkout is missing.
- **GitHub CLI setup role** now uses privilege escalation consistently for key, repository, and package install tasks.
- **Cloud AI CLI role** now skips GitHub Copilot CLI extension install until `gh auth login` has been completed.
- **VS Code apt source handling** now removes stale legacy source/keyring state before any apt operations.
- **distrodeck launcher integration** now uses a wrapper instead of a broken symlinked entrypoint.
- **git-lantern clone flow** now avoids unnecessary recursive submodule initialization during NikOS install.
- **Theming role** now applies Xfce theme assets as active defaults instead of only installing files on disk.

## [0.1.0] — 2026-04-02

Initial release.
- Ansible playbook for Ubuntu 24.04 LTS: Xfce 4 + Nordic theme, full AI stack
  (Ollama, aider, Claude Code, Gemini CLI, Miniforge/conda), VS Code with AI extensions,
  developer tools via distrodeck, GitHub first-login wizard.
- `nikos` CLI: `setup`, `update`, `add`, `status`, `doctor`.
- CI: ansible-lint, dry-run test, GitHub Release workflow.
