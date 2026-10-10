# Installation Guide

## Requirements

- **OS:** Xubuntu or Ubuntu 22.04, 24.04 or 26.04 LTS (24.04 recommended;
  the NikOS ISO is built from Xubuntu 24.04)
- **Ansible:** `ansible-playbook` 2.15 or newer; the installer can offer to
  upgrade older Ubuntu packages from the Ansible PPA
- **User:** a non-root user with `sudo` access
- **Internet:** required during install (packages, theme files, models)
- **Disk:** ~20 GB free (Ollama model + conda env + VS Code + tools); add
  about 30 GB more for every Ollama module on a standard machine (more on large and xlarge)
- **RAM:** 4 GB minimum; 8 GB recommended for running `qwen3.5:4b`

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/nikolareljin/nikos/main/install.sh | bash
```

The script will:
1. Check you are not running as root
2. Check you are on Ubuntu or Xubuntu 22.04, 24.04 or 26.04 LTS
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
9. Ask for the profile, `desktop` (default) or `server`, saying whether a display
   manager was found, and write it to `vars/local.yml`. See [profiles.md](profiles.md).
10. Run `ansible-playbook` from the local clone, behind a per-role progress gauge

## What the playbook does (in order)

Roles marked *desktop* run only on the `desktop` profile; see
[profiles.md](profiles.md).

| Role | What it installs |
|---|---|
| `base` | apt update, nala, core build deps, flatpak, tmux, pipx, sqlite3, openssh-server, locale, timezone, NTP sync |
| `desktop` (*desktop*) | Xubuntu desktop, LightDM, xfce4-terminal, display manager and default session handover |
| `theming` (*desktop*) | Nordic GTK theme, Papirus-Dark icons, GRUB theme, LightDM greeter, wallpaper |
| `github-setup` | gh CLI, first-login wizard (SSH key, git identity) |
| `ai-stack` | Ollama on 127.0.0.1:11434 + qwen3.5:4b, llama.cpp, Miniforge, nikos-ai conda env, uv, aider in its own nikos-aider env |
| `editors` (*desktop*) | VS Code + AI extensions + Nord theme + JetBrains Mono |
| `cloud-ai-cli` | Node (system or nvm-pinned), Gemini CLI, shell-gpt, glances |
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
Git setup wizard (`nikos-git-setup`) asks which Git host you use:

1. GitHub - `gh auth login`, then `gh ssh-key add`
2. GitLab (gitlab.com or self-hosted) - adds the key with a personal access token (scope `api`)
3. Bitbucket - adds the key with your Atlassian account email and an API token
4. Custom Git server - prints the key for you to add; writes a `Host` block to
   `~/.ssh/config` when the port is not 22 or the user is not `git`
5. Skip - no key is generated or uploaded; create one with `ssh-keygen -t ed25519`
   and add it to your host yourself

For any host it reuses `~/.ssh/id_ed25519` or creates it, sets your git name and
email if unset, checks the login with `ssh -T`, and can clone a dotfiles repo
(`user/repo` or a full git URL). You can add more than one host in one run.
Tokens are read without echo, sent only over HTTPS, and never saved.

The wizard writes `~/.config/nikos/github-configured` when it finishes or is
skipped, and does not run again. `nikos-git-setup --reset` runs it again;
`nikos-git-setup --skip` marks it done without asking. To install without the
terminal hook, set `nikos_git_setup: skip` in `vars/local.yml`.

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
cd nikos    # your clone of this repository
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

Everything NikOS downloads is pinned in `vars/versions.yml`: release files to
a version and a sha256, registry packages to an exact version, git checkouts to
a commit, vendor apt keys to a fingerprint. For an existing install the pin is a
minimum: `nikos update` installs a component that is missing or older than its
pin and leaves one that is newer (it prints that it did). It never downgrades,
and a git checkout that already contains its pinned commit is not moved.

- **Ollama.** Installed from the pinned release archive when missing or older
  than `ollama_version`; `ollama.service` is restarted after a change. The
  NikOS drop-in (`ollama.service.d/nikos.conf`, the listen address) is kept.
- **distrodeck.** Checked out at `distrodeck_commit` after confirming that tag
  `distrodeck_version` still points there. `distrodeck_version: latest` in
  `vars/local.yml` follows the newest `X.Y.Z` tag instead. Offline, or when the
  clone has uncommitted edits to tracked files, the existing clone is kept and
  the run prints a warning.

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
ansible-playbook site.yml -i inventory/local --ask-become-pass -e nikos_update_mode=false
```

`nikos_update_mode=false` is required for a hand-run install. The variable
defaults to `true` so the pre-0.6.5 CLI still refreshes dependencies on its
first update; leaving it at that default turns a fresh install into an update
run.

## Offline / air-gapped installs

Not supported in 0.5.0. The playbook downloads theme files, Ollama, Miniforge, and selected tool binaries at install time.

## Base OS choice

**Recommended: Xubuntu 24.04 LTS** (~3 GB ISO, Xfce pre-installed, minimal footprint)

Also supported: **Ubuntu 24.04 LTS**, and Ubuntu or Xubuntu **22.04** and
**26.04 LTS**. The NikOS ISO (`isoforge.yml`) stays on Xubuntu 24.04.

What differs per release (`nikos_ubuntu_releases` in `vars/main.yml`):

| | 22.04 jammy | 24.04 noble | 26.04 resolute |
|---|---|---|---|
| Ansible | archive 2.10 is too old; the installer upgrades from the Ansible PPA (2.17) | archive 2.16 | archive 2.20 |
| Xubuntu minimal desktop | `xubuntu-core` | `xubuntu-desktop-minimal` | `xubuntu-desktop-minimal` |
| `postgres` bundle | no pgvector (not in the archive) | `postgresql-16-pgvector` | `postgresql-18-pgvector` |
| `mongodb` bundle | yes | yes | skipped: MongoDB publishes no `resolute` repository |
| `monitoring` bundle | yes | yes | Netdata from Netdata's own apt repository (signing key fingerprint-checked), bound to 127.0.0.1 |
| `education` bundle | yes | yes | Anki from the official ankitects/anki release tarball (sha256-checked) |

A skipped bundle prints why and the rest of the install carries on.

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

`--profile=server` runs the same flow against Ubuntu Server 24.04 in its own VM,
with the server profile and a checklist that asserts no desktop artefact is
present (`./test -b --profile=server`). See [profiles.md](profiles.md).

To rebuild the VM from scratch and re-run the full OS + NikOS install flow:

```bash
./test -b
# or
./test --build
```

**Requirements:** VirtualBox, `curl`, `sshpass`, OpenSSH client tools (`ssh`, `scp`, `ssh-copy-id`), ~4 GB RAM free.
