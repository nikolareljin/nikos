# Changelog

All notable changes to NikOS are documented here.

## [0.2.1] — 2026-04-14

### Added
- **Install logging** — `install.sh` and `scripts/nikos` now write timestamped log files
  to `~/.config/nikos/logs/`. Each installer run produces
  `install-YYYYMMDD-HHMMSS.log`; each `nikos setup/update/add` run produces
  `nikos-YYYYMMDD-HHMMSS-playbook.log`. A `*-latest.log` symlink always points at the
  most recent run. The full Ansible playbook output (stdout + stderr) is captured via
  `tee`, ANSI escape codes are stripped from the file, and a summary block reporting
  `ok/changed/failed/unreachable` counts plus the names of any failed tasks is printed
  at the end of every run.
- **`nikos log [N]`** — new CLI command; shows the last N lines (default 50) of the
  latest playbook log. `nikos log list` lists all available log files.

### Fixed
- **`./test` VirtualBox repair path** now retries existing VMs that never had `openssh-server`
  installed. If the SSH port is still closed during the default `./test` flow, NikOS now
  uses VirtualBox guest control to install and start `openssh-server`, then retries SSH
  before failing.
- **`./test -b` unattended desktop boot** now adds `only-ubiquity` so the Xubuntu live ISO
  launches the installer automatically instead of stopping in the live session and waiting
  for a manual click on the install shortcut.
- Version bumped `0.2.0` → `0.2.1` in `vars/main.yml`, `install.sh`, and `scripts/nikos`.
- **Testing docs** now document the SSH repair behavior for older VirtualBox VMs.
- **VS Code apt source conflict** (`Conflicting values set for option Signed-By`)
  fixed systematically. Root cause: VS Code's own `dpkg` postinst script detects
  `vscode.list`, writes `vscode.sources` (DEB822 format, `Signed-By: microsoft.gpg`),
  then deletes `vscode.list`. The playbook was writing `vscode.list` with
  `microsoft.asc`, so every VS Code install/upgrade left both files present with
  different keyring paths — causing apt to refuse to read its source list.
  Fix: align with VS Code's own format. The editors role now downloads and dearmors
  the key to `microsoft.gpg` and registers the repository via
  `ansible.builtin.deb822_repository` (`vscode.sources`). VS Code's postinst now
  overwrites the entry with identical content, making it fully idempotent. The
  pre-playbook cleanup now only removes the legacy `vscode.list`; `vscode.sources`
  and `microsoft.gpg` are no longer treated as legacy artifacts to be deleted.
- **VS Code extension downgrade conflict** no longer fails the playbook. When
  `code --install-extension` refuses to downgrade a built-in bundled extension
  (e.g. `github.copilot-chat` already at a newer built-in version), the task now
  treats that as `ok` rather than `failed`. Any other non-zero exit code from the
  extension install still surfaces as a real failure. Applied to both the standard
  and AI extension install tasks in the `editors` role.
- **GitHub setup wizard crash loop** fixed. When `gh` lacks the `admin:public_key` OAuth
  scope, `gh ssh-key list` returns a non-zero exit code; the wizard previously misread this
  as "key not uploaded", attempted `gh ssh-key add`, crashed with an unhandled
  `CalledProcessError`, and never wrote the completion flag — causing the wizard to re-run
  on every shell session. Fixed by treating a scope-missing error as "assume present, warn
  user" rather than triggering an upload attempt. The `gh ssh-key add` call is also now
  wrapped in a try/except for a clean error message instead of a traceback. The `main()`
  early-exit no longer prints a noisy message on sessions where setup is already complete.
  Four new unit tests cover the scope-missing, key-present, key-absent, and other-error paths.

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
- **NikOS logo assets** (`assets/logo.png`, `assets/logo.svg`) — official NikOS visual identity (node-graph + wordmark, Nord palette).
- **Plymouth boot splash** — custom NikOS theme replacing the default Xubuntu spinner; centered logo with a slow opacity-pulse animation on a dark Nord background. Installed to `/usr/share/plymouth/themes/nikos/` and set as system default.

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
- **Developer tools install flow** remains automated via distrodeck and currently runs
  `install-tools --all`.
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
