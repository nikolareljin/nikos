# Installation Guide

## Requirements

- **OS:** Xubuntu 24.04 LTS (recommended) or Ubuntu 24.04 LTS
- **Ansible:** `ansible-playbook` 2.15 or newer; the installer can offer to
  upgrade older Ubuntu packages from the Ansible PPA
- **User:** a non-root user with `sudo` access
- **Internet:** required during install (packages, theme files, models)
- **Disk:** ~20 GB free (Ollama model + conda env + VS Code + tools); add
  about 93 GB if selecting every optional Ollama model group
- **RAM:** 4 GB minimum; 8 GB recommended for running `qwen2.5-coder:7b`

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/nikolareljin/nikos/main/install.sh | bash
```

The script will:
1. Check you are not running as root
2. Check you are on Xubuntu 24.04 LTS or Ubuntu 24.04 LTS
3. Install bootstrap packages: `git`, `ansible`, and `dialog` unless `NIKOS_USE_DIALOG=0`
4. Offer to upgrade unsupported Ansible versions from the Ansible Ubuntu PPA
5. Clone the repo (with submodules) to `~/.local/share/nikos`; when launched
   from a non-main checkout, the persistent repo follows that same branch
6. Present a `dialog` TUI checklist to select optional bundles
7. Present a `dialog` TUI checklist to select AI tools
8. Ask for the timezone to use — detects the system timezone via `timedatectl` and offers:
   - **Auto** — use the detected system timezone (NTP-synchronized)
   - **Keep existing** — if `vars/local.yml` already has `nikos_timezone` set (shown only
     when the configured value differs from the detected one)
   - **Custom** — enter any IANA timezone string (e.g. `America/New_York`, `Asia/Tokyo`)
   The chosen timezone is written to `vars/local.yml` before the playbook runs.
9. Run `ansible-playbook` from the local clone, behind a per-role progress gauge

## What the playbook does (in order)

| Role | What it installs |
|---|---|
| `base` | apt update, nala, core build deps, flatpak, tmux, pipx, sqlite3, locale, timezone, NTP sync |
| `desktop` | Xubuntu desktop, LightDM, xfce4-terminal, display manager and default session handover |
| `theming` | Nordic GTK theme, Papirus-Dark icons, GRUB theme, LightDM greeter, wallpaper |
| `github-setup` | gh CLI, first-login wizard (SSH key, git identity) |
| `ai-stack` | Ollama + qwen2.5-coder:7b, llama.cpp, Miniforge, nikos-ai conda env, aider, uv |
| `editors` | VS Code + AI extensions + Nord theme + JetBrains Mono |
| `cloud-ai-cli` | Node (system or nvm-pinned), Gemini CLI, GitHub Copilot CLI extension, shell-gpt, glances |
| `agent-dev` | LangChain, LlamaIndex, ML/data libraries, Claude Code |
| `dev-tools` | distrodeck tools, image-view, git-lantern, mkcert, ai-runner |
| `optional/*` | network / music / education / neovim / java / podman / bun / databases / LLM tools / monitoring (opt-in) |

## First login

Coming from Xubuntu, log out and back in; the NikOS session starts through
LightDM.

Coming from Ubuntu, **reboot**. The installer switches the display manager from
GDM3 to LightDM and sets the default session to Xubuntu, and neither takes
effect while the GNOME session that launched the installer is still running.
The installer prints which of the two you need at the end of the run.

On the first terminal session, NikOS shows a short one-time command hint, then the
GitHub setup wizard runs:
1. `gh auth login` — authenticate with GitHub
2. SSH key generation and upload
3. Git name/email configuration
4. Optional: pull your dotfiles repo

The wizard writes `~/.config/nikos/github-configured` on completion and will not run again.

## Which version gets installed

With no options the installer picks the **newest release tag** — the highest
`X.Y.Z` the repository publishes. Pre-release tags (`0.6.0-rc1`) and floating
tags (`production`) are never selected.

| Command | Installs |
|---|---|
| `curl -fsSL .../install.sh \| bash` | latest release tag |
| `bash install.sh` | latest release tag |
| `bash install.sh --ref release/0.6.0` | that branch or tag |
| `bash install.sh --dev` | the checkout you launched it from, as it stands |

The persistent checkout at `~/.local/share/nikos` is moved onto the chosen ref
before the playbook runs. Installing a tag leaves that checkout on a detached
HEAD, which is expected.

`NIKOS_REPO_REF=<ref>` is equivalent to `--ref <ref>`.

### Dev mode

```bash
cd ~/Projects/nikos
bash install.sh --dev
```

`--dev` runs the checkout the script lives in, **including uncommitted
changes**. Nothing is cloned, fetched, pulled or stashed, and
`~/.local/share/nikos` is left untouched — so a broken branch cannot damage a
working install. Use it to test a change before pushing it.

It refuses to run if the directory has no `site.yml`, and cannot be combined
with `--ref`.

## Updating

```bash
nikos update                      # newest release
nikos update --ref release/0.6.0  # a specific branch or tag
```

`nikos update` fetches, moves `~/.local/share/nikos` onto the target ref,
updates submodules and re-runs the playbook. All roles are idempotent —
already-installed components are skipped.

The target is chosen from what is currently checked out:

- **On a release tag** — advances to the newest release, and only if it really
  is newer. An update never downgrades.
- **On a branch** — stays on that branch and fast-forwards it.

## Which interface a run gets

The TUI follows the **controlling terminal**, not stdin. Under
`curl ... | bash`, bash reads the script itself from stdin, so stdin is a pipe
on every such run — the installer asks whether `/dev/tty` is reachable instead,
which it is whenever a person is sitting at a terminal. The one-liner therefore
gets the same checklists and the same per-role gauge as a clone-and-run install.

Before 0.6.2 that test asked about stdin, and no piped install could pass it: the
one-liner showed raw `TASK [...]` output, and on machines without `dialog` it
also discarded the bundles that had been selected. See issues #52 and #53.

A run with no controlling terminal at all — `setsid`, a systemd unit, most CI
jobs — does not fall back to plain prompts. It stops. It cannot ask which
optional bundles to install, and an empty answer is indistinguishable from a
deliberate "install nothing optional", so it says so and exits rather than
reporting success for an install that skipped everything.

`nohup` alone is not such a run: it ignores SIGHUP and redirects the standard
streams, but leaves the controlling terminal in place, so a `nohup` install
started from a terminal still gets the TUI.

To force plain output on a real terminal, for a scripted or logged run:

```bash
NIKOS_USE_DIALOG=0 bash install.sh
```

The same variable applies to `nikos setup` and `nikos update`, which use the
per-role gauge on a terminal and plain output without one.

## Manual run (without curl | bash)

```bash
git clone --recurse-submodules https://github.com/nikolareljin/nikos.git
cd nikos
ansible-galaxy collection install -r requirements.yml
ansible-playbook site.yml -i inventory/local --ask-become-pass
```

## Offline / air-gapped installs

Not supported in 0.5.0. The playbook downloads theme files, Ollama, Miniforge, and selected tool binaries at install time.

## Base OS choice

**Recommended: Xubuntu 24.04 LTS** (~3 GB ISO, Xfce pre-installed, minimal footprint)

Also supported: **Ubuntu 24.04 LTS**. Use the standard Ubuntu desktop ISO.

### Ubuntu to Xubuntu migration

On an Ubuntu host the `desktop` role does four things a plain `apt install
xfce4` does not:

1. Installs `xubuntu-desktop-minimal`, `xubuntu-default-settings` and
   `xubuntu-artwork`, which provide the Xubuntu session and the Xubuntu login
   form. Bare `xfce4` provides neither.
2. Pre-seeds the `shared/default-x-display-manager` debconf answer and rewrites
   `/etc/systemd/system/display-manager.service` to point at LightDM. This is
   the setting systemd actually reads; `/etc/X11/default-display-manager` alone
   changes nothing, and `systemctl enable lightdm` cannot take the alias while
   GDM3 holds it.
3. Disables the `gdm3` service without removing the package.
4. Writes the default session to the AccountsService user file and to
   `/etc/lightdm/lightdm.conf.d/60-nikos.conf`, so an existing account does not
   get dropped back into its previously recorded GNOME session.

GNOME stays installed by default and remains selectable from the greeter's
session menu, so the migration is reversible. Set `nikos_remove_gnome: true` in
`vars/local.yml` to purge it instead.

Reboot once the install finishes.

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
