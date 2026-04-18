# Installation Guide

## Requirements

- **OS:** Xubuntu 24.04 LTS (recommended) or Ubuntu 24.04 LTS
- **User:** a non-root user with `sudo` access
- **Internet:** required during install (packages, theme files, models)
- **Disk:** ~20 GB free (Ollama model + conda env + VS Code + tools)
- **RAM:** 4 GB minimum; 8 GB recommended for running `qwen2.5-coder:7b`

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/nikolareljin/nikos/main/install.sh | bash
```

The script will:
1. Check you are not running as root
2. Check you are on an apt-based system
3. Install bootstrap packages: `git`, `ansible`, and `dialog` unless `NIKOS_USE_DIALOG=0`
4. Clone the repo (with submodules) to `~/.local/share/nikos`
5. Present a `dialog` TUI checklist to select optional bundles
6. Present a `dialog` TUI checklist to select AI tools
7. Ask for the timezone to use — detects the system timezone via `timedatectl` and offers:
   - **Auto** — use the detected system timezone (NTP-synchronized)
   - **Keep existing** — if `vars/local.yml` already has `nikos_timezone` set (shown only
     when the configured value differs from the detected one)
   - **Custom** — enter any IANA timezone string (e.g. `America/New_York`, `Asia/Tokyo`)
   The chosen timezone is written to `vars/local.yml` before the playbook runs.
8. Run `ansible-playbook` from the local clone

## What the playbook does (in order)

| Role | What it installs |
|---|---|
| `base` | apt update, nala, core build deps, flatpak, locale, timezone, NTP sync |
| `desktop` | Xfce 4, LightDM, xfce4-terminal |
| `theming` | Nordic GTK theme, Papirus-Dark icons, GRUB theme, LightDM greeter, wallpaper |
| `github-setup` | gh CLI, first-login wizard (SSH key, git identity) |
| `ai-stack` | Ollama + qwen2.5-coder:7b, Miniforge, nikos-ai conda env, aider, uv |
| `editors` | VS Code + AI extensions + Nord theme + JetBrains Mono |
| `cloud-ai-cli` | Node.js, Gemini CLI, GitHub Copilot CLI extension |
| `agent-dev` | LangChain, LlamaIndex, Claude Code |
| `dev-tools` | distrodeck tools, image-view, git-lantern, ai-runner |
| `optional/*` | network / music / education / neovim / java / podman (opt-in) |

## First login

After install, log out and back in. Xfce starts automatically via LightDM.

On the first terminal session, the GitHub setup wizard runs:
1. `gh auth login` — authenticate with GitHub
2. SSH key generation and upload
3. Git name/email configuration
4. Optional: pull your dotfiles repo

The wizard writes `~/.config/nikos/github-configured` on completion and will not run again.

## Updating

```bash
nikos update
```

This runs `git pull --ff-only` on `~/.local/share/nikos`, then
`git submodule update --init --recursive`, and finally re-runs the playbook.
All roles are idempotent — already-installed components are skipped.

To force the plain-prompt installer path instead of the `dialog` UI:

```bash
NIKOS_USE_DIALOG=0 bash install.sh
```

## Manual run (without curl | bash)

```bash
git clone --recurse-submodules https://github.com/nikolareljin/nikos.git
cd nikos
ansible-galaxy collection install -r requirements.yml
ansible-playbook site.yml -i inventory/local --ask-become-pass
```

## Offline / air-gapped installs

Not supported in 0.3.0. The playbook downloads theme files, Ollama, and Miniforge at install time.

## Base OS choice

**Recommended: Xubuntu 24.04 LTS** (~3 GB ISO, Xfce pre-installed, minimal footprint)

Also supported: **Ubuntu 24.04 LTS** — the playbook detects GNOME and removes it before installing Xfce. Use the standard Ubuntu desktop ISO.

Starting from Ubuntu adds a GNOME purge step and takes a few extra minutes, but the end state is identical.

## Testing with VirtualBox

The canonical way to validate a fresh NikOS install is the `./test` script,
which automates the full flow (VM creation, unattended OS install, NikOS install, verification):

```bash
./test
```

The script waits for SSH, uses `sshpass` to copy your SSH key to the VM non-interactively,
then runs the installer and prints a `nikos doctor` verification report. On older test VMs,
if SSH is still unavailable, the script now tries to install and start `openssh-server`
through VirtualBox guest control before retrying the SSH checks. During `./test -b`,
the unattended Xubuntu desktop boot now also forces the ISO straight into the installer
instead of stopping at the live session.

To rebuild the VM from scratch and re-run the full OS + NikOS install flow:

```bash
./test -b
# or
./test --build
```

**Requirements:** VirtualBox, `curl`, `sshpass`, OpenSSH client tools (`ssh`, `scp`, `ssh-copy-id`), ~4 GB RAM free.
