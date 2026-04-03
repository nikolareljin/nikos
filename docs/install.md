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
3. Install Ansible if not present
4. Ask whether to include optional bundles (network tools, music, education)
5. Run `ansible-pull` — pulls the playbook from GitHub and applies it

## What the playbook does (in order)

| Role | What it installs |
|---|---|
| `base` | apt update, nala, core build deps, flatpak, locale, timezone |
| `desktop` | Xfce 4, LightDM, xfce4-terminal |
| `theming` | Nordic GTK theme, Papirus-Dark icons, GRUB theme, LightDM greeter, wallpaper |
| `github-setup` | gh CLI, first-login wizard (SSH key, git identity) |
| `ai-stack` | Ollama + qwen2.5-coder:7b, Miniforge, nikos-ai conda env, aider, uv |
| `editors` | VS Code + AI extensions + Nord theme + JetBrains Mono |
| `cloud-ai-cli` | Node.js, Gemini CLI, GitHub Copilot CLI extension |
| `agent-dev` | LangChain, LlamaIndex, Claude Code |
| `dev-tools` | distrodeck tools, image-view, git-lantern, ai-runner |
| `optional/*` | network / music / education (opt-in) |

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

This runs `ansible-pull` again. All roles are idempotent — already-installed components are skipped.

## Manual run (without curl | bash)

```bash
git clone https://github.com/nikolareljin/nikos.git
cd nikos
ansible-playbook site.yml -i inventory/local --ask-become-pass
```

## Offline / air-gapped installs

Not supported in 0.1.0. The playbook downloads theme files, Ollama, and Miniforge at install time.

## Base OS choice

**Recommended: Xubuntu 24.04 LTS** (~3 GB ISO, Xfce pre-installed, minimal footprint)

Also supported: **Ubuntu 24.04 LTS** — the playbook detects GNOME and removes it before installing Xfce. Use the standard Ubuntu desktop ISO.

Starting from Ubuntu adds a GNOME purge step and takes a few extra minutes, but the end state is identical.

## Testing with VirtualBox

The canonical way to validate a fresh NikOS install:

1. Download [Xubuntu 24.04 LTS](https://xubuntu.org/download/) (recommended) or Ubuntu 24.04 LTS
2. Create a VM (minimum 6 GB RAM, 40 GB disk) and attach the ISO
3. Install the OS, take a snapshot at first boot
4. Run the curl install command
5. Verify with `nikos doctor` after reboot

Revert to the snapshot to re-test cleanly.
