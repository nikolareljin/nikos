# NikOS Design Spec
**Neural Innovation for Knowledge OS**

_Tagline: Light system. Heavy thinking._

---

## Context

NikOS is a curated Ubuntu 24.04 LTS remix for AI coding and development, built and maintained by Nikos Reljin. Rather than a custom ISO, NikOS is an Ansible playbook + `nikos` CLI that transforms a fresh Ubuntu 24.04 install into a fully configured AI development workstation. The visual identity is Xfce with a Nordic (Nord palette) theme styled to feel modern and COSMIC-inspired.

**What prompted it:** The author wanted a repeatable, shareable, opinionated dev environment that is lightweight (Xfce, ~250 MB RAM idle), visually distinctive (Nordic palette), and AI-native (full local + cloud AI stack pre-configured). The existing `distrodeck` tool handles cross-distro developer tool installation and is reused here — NikOS calls it as one task, keeping `distrodeck` portable and independent.

**Intended outcome:** A single `curl | bash` command turns Ubuntu 24.04 into NikOS 0.1.0. Updates are self-hosted via `ansible-pull`. The result is publishable on GitHub and installable by others.

---

## Architecture

```
install.sh  (bootstrap)
  └── apt install ansible
  └── ansible-pull -U https://github.com/nikolareljin/nikos-os site.yml
        └── site.yml  (top-level playbook)
              └── roles/ (run in order, idempotent)
```

NikOS is split into two layers:

| Layer | Tool | Scope |
|---|---|---|
| System configuration | Ansible playbook | DE, theming, system apps, AI stack, GitHub setup |
| Developer tool installation | distrodeck | CLI tools, language runtimes, devops tools |

`distrodeck` is called by the `dev-tools` role. It remains cross-distro and independent.

---

## Repository Structure

**GitHub repo:** `nikolareljin/nikos-os` — public, MIT licensed.

```
nikos-os/
├── README.md
├── install.sh                   # bootstrap: installs ansible, runs ansible-pull
├── site.yml                     # top-level playbook
├── vars/
│   └── main.yml                 # nikos_version, theme URLs, Ollama model, etc.
├── inventory/
│   └── local                    # localhost ansible_connection=local
├── roles/
│   ├── base/                    # apt update, core deps, nala, flatpak
│   ├── desktop/                 # xfce4, xfce4-goodies, lightdm
│   ├── theming/                 # Nordic GTK + icons + GRUB + LightDM + wallpaper
│   ├── github-setup/            # gh CLI, first-run wizard, SSH key, git identity
│   ├── ai-stack/                # Ollama, aider, miniforge/conda, PyTorch, Jupyter
│   ├── editors/                 # VS Code + AI extensions + NikOS settings.json
│   ├── cloud-ai-cli/            # Claude CLI, Gemini CLI, gh copilot extension
│   ├── agent-dev/               # LangChain, LlamaIndex, MCP deps, Claude Code
│   ├── dev-tools/               # distrodeck clone + distrodeck install-tools --all
│   └── optional/
│       ├── network/             # nmap, wireshark, network manager extras
│       ├── music/               # LMMS, Ardour, Audacity
│       └── education/           # LibreOffice, draw.io, Anki
└── .github/workflows/
    ├── lint.yml                 # ansible-lint on every PR
    ├── test.yml                 # Ubuntu 24.04 Docker --check dry-run
    └── release.yml              # GitHub Release on tag push
```

---

## Role Details

### base
- `apt update && apt full-upgrade`
- Install: `git curl wget build-essential python3-pip flatpak nala`
- Configure locale (`en_US.UTF-8`) and timezone (user-configurable via `vars/main.yml`)

### desktop
- `apt install xfce4 xfce4-goodies lightdm xfce4-docklike-plugin`
- Disable GNOME/Unity session if present
- Configure Xfce panel layout: top bar + taskbar

### theming
- Download and install Nordic GTK theme → `~/.themes/Nordic/`
- Install `papirus-icon-theme` with Nordic folder colors
- Apply via `xfconf-query` (fully scriptable, no manual clicking):
  - GTK theme: Nordic
  - Icon theme: Papirus-Dark
  - Window manager theme: Nordic
- Nordic GRUB theme → `/boot/grub/themes/Nordic/`
- Nordic LightDM greeter config + NikOS wallpaper (static SVG committed to repo at `assets/wallpaper.svg`, Nord palette, exported to PNG on install)
- NikOS version stamped on LightDM login screen

### github-setup
- Install `gh` CLI
- Run Python TUI wizard (idempotent — skipped if `~/.config/nikos/github-configured` exists):
  1. `gh auth login`
  2. SSH key generation + upload via `gh ssh-key add`
  3. `git config --global user.name` / `user.email`
  4. Optional: `ansible-pull` from user's dotfiles repo
- Write `~/.config/nikos/github-configured` on completion

### ai-stack
- Install Ollama (official install script)
- Pull default model: `qwen2.5-coder:7b`
- Install Miniforge (conda) → `~/miniforge3/`
- Create `nikos-ai` conda env: Python 3.11, PyTorch CPU, transformers, jupyter, pandas, numpy, scikit-learn
- `pip install aider-chat uv`

### editors
- Install VS Code via Microsoft apt repo
- Install extensions: `Continue.continue`, `eamodio.gitlens`, `GitHub.copilot`, `ms-python.python`, `ms-toolsai.jupyter`, `arcticicestudio.nord-visual-studio-code`, `ms-vscode-remote.remote-ssh`, `ms-azuretools.vscode-docker`, `humao.rest-client`
- Deploy NikOS `settings.json`: Nord color theme, font `JetBrains Mono`, terminal → `xfce4-terminal`

### cloud-ai-cli
- Install Gemini CLI: `npm install -g @google/gemini-cli`
- `gh extension install github/gh-copilot`

### agent-dev
- `pip install langchain llama-index openai anthropic instructor`
- Install Claude Code: `npm install -g @anthropic-ai/claude-code`

### dev-tools
- Clone `distrodeck` into `~/Projects/distrodeck/` if not present
- Symlink to `/usr/local/bin/distrodeck`
- Run `distrodeck install-tools --all` (installs bat, eza, fzf, gh, lazygit, rust, go, docker, etc.)

### optional/*
- Tag-gated: `--tags network`, `--tags music`, `--tags education`
- Skipped by default; `install.sh` prompts user to opt in
- `nikos add <name>` installs any optional role post-setup

---

## The `nikos` CLI

Installed to `/usr/local/bin/nikos` — a thin shell wrapper around Ansible:

```
nikos setup          # run full playbook (first install)
nikos update         # ansible-pull + re-run (idempotent)
nikos add network    # install optional/network role
nikos add music      # install optional/music role
nikos add education  # install optional/education role
nikos status         # show roles, versions, Ollama models
nikos doctor         # check broken configs, missing deps
```

---

## Visual Identity

| Element | Choice |
|---|---|
| DE | Xfce 4 |
| GTK theme | Nordic |
| Icon theme | Papirus-Dark (Nordic folders) |
| Window decorations | Nordic (Xfwm4) |
| Color palette | Nord (#2e3440 base, #88c0d0 accent) |
| GRUB theme | Nordic |
| Login screen | LightDM Nordic greeter + NikOS wallpaper |
| VS Code theme | Nord (`arcticicestudio.nord-visual-studio-code`) |
| Wallpaper | Static SVG in `assets/wallpaper.svg` (Nord palette) |
| Terminal font | JetBrains Mono |
| Tagline | "Light system. Heavy thinking." |

---

## CI/CD & Versioning

- **Versioning:** Strict semver `X.Y.Z` (no `v` prefix). First release: `0.1.0`.
- `nikos_version: "0.1.0"` in `vars/main.yml` is the single source of truth.
- Git tags match exactly: `0.1.0`, `0.2.0`, etc.

| Workflow | Trigger | Action |
|---|---|---|
| `lint.yml` | Every PR | `ansible-lint` — blocks merge on errors |
| `test.yml` | Every PR + push to main | Ubuntu 24.04 Docker, `--check` dry-run |
| `release.yml` | Tag push (`0.*`) | GitHub Release with CHANGELOG + `install.sh` asset |

**Branch strategy:**
- `main` — stable, always installable
- `dev` — integration branch, PRs target here
- `feature/*` — individual role work

---

## Verification Plan

1. **Lint:** `ansible-lint site.yml` passes with zero errors
2. **Dry-run:** `ansible-playbook site.yml --check` completes without failures on Ubuntu 24.04 Docker
3. **Live install:** Fresh Ubuntu 24.04 VM → run `install.sh` → verify:
   - Xfce desktop loads with Nordic theme
   - `nikos status` reports version `0.1.0`
   - `ollama list` shows `qwen2.5-coder:7b`
   - `code --list-extensions` includes Continue, GitLens, Copilot, Nord theme
   - `distrodeck` launches TUI successfully
   - `gh auth status` shows authenticated
4. **Idempotency:** Run `nikos update` twice — second run reports no changes
5. **Optional roles:** `nikos add music` installs LMMS and Ardour cleanly
