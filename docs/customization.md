# Customization

Keep local overrides in `vars/local.yml`. `site.yml` loads `vars/main.yml` first, then
overlays any values from `vars/local.yml`, so updates can refresh tracked defaults without
clobbering your machine-specific settings.

## vars/local.yml reference

```yaml
# ── System ───────────────────────────────────────────
nikos_timezone: "Europe/London"     # set interactively during install; any tz from timedatectl list-timezones
nikos_locale: "en_US.UTF-8"

# ── Desktop ───────────────────────────────────────────
nikos_desktop_flavor: "xubuntu-minimal"  # xubuntu-minimal | xubuntu-full | xfce
nikos_remove_gnome: false                # true purges GNOME during an Ubuntu migration
nikos_disable_gdm: true                  # disable gdm3 without removing the package
nikos_default_session: "auto"            # auto | xubuntu | xfce | any /usr/share/xsessions entry

# ── Theme ─────────────────────────────────────────────
nordic_gtk_url: "https://github.com/EliverLara/Nordic/releases/..."

# ── Ollama ────────────────────────────────────────────
ollama_default_model: "qwen2.5-coder:7b"
ollama_optional_models:
  - "phi4:14b"
  - "codellama:7b"
  - "deepseek-coder:6.7b"
# Other good choices: llama3.2, mistral, codellama, phi3
llama_cpp_version: "b9151"

# ── Python ────────────────────────────────────────────
miniforge_version: "24.11.3-0"
nikos_conda_env: "nikos-ai"
nikos_python_version: "3.11"

# ── VS Code extensions ────────────────────────────────
nikos_vscode_extensions:
  - "Continue.continue"
  - "eamodio.gitlens"
  - "GitHub.copilot"
  - "ms-python.python"
  - "ms-toolsai.jupyter"
  - "arcticicestudio.nord-visual-studio-code"
  - "ms-vscode-remote.remote-ssh"
  - "ms-azuretools.vscode-docker"
  - "humao.rest-client"
```

## Choosing the desktop package set

`nikos_desktop_flavor` selects what the `desktop` role installs:

| Value | Packages | Notes |
|---|---|---|
| `xubuntu-minimal` (default) | `xubuntu-desktop-minimal`, `xubuntu-default-settings`, `xubuntu-artwork` | Xubuntu session, greeter and artwork without the full Xubuntu application suite |
| `xubuntu-full` | `xubuntu-desktop` and the above | The complete Xubuntu metapackage, including its default apps |
| `xfce` | `xfce4` | Bare Xfce with no Xubuntu branding; the pre-0.5.0 behaviour |

NikOS theming (Nordic, Papirus-Dark, the NikOS wallpaper and Plymouth theme)
runs after the desktop role in every case, so it layers on top of whichever set
you pick.

## Keeping or removing GNOME

Migrating from Ubuntu leaves GNOME installed and selectable from the LightDM
session menu. To purge it instead:

```yaml
nikos_remove_gnome: true
```

That removes `ubuntu-desktop`, `ubuntu-desktop-minimal`, `ubuntu-session`,
`gnome-session*` and `gnome-shell` with `autoremove`. It is not reversible
without reinstalling those packages.

`nikos_disable_gdm: false` leaves the `gdm3` service enabled. LightDM still owns
`display-manager.service`, so this only matters if you plan to switch back.

## Changing the Ollama model

Edit `vars/local.yml`:

```yaml
ollama_default_model: "llama3.2"
```

Then run `nikos update`. The new model will be pulled on the next playbook run.

You can also pull models manually at any time:

```bash
ollama pull codellama
ollama pull phi3:mini
ollama list
```

## Adding VS Code extensions

Add extension IDs (from the VS Code Marketplace URL) to `nikos_vscode_extensions` in `vars/local.yml`, then run `nikos update`.

## Adding optional bundles

```bash
nikos add network    # nmap, wireshark, OpenVPN, traceroute, tcpdump
nikos add music      # LMMS, Ardour (Flatpak), Audacity
nikos add education  # LibreOffice, draw.io (Flatpak), Anki
nikos add neovim     # Neovim plus a minimal lazy.nvim bootstrap config
nikos add java       # OpenJDK 21
nikos add podman     # Podman container runtime
nikos add bun        # Bun JavaScript runtime
nikos add redis      # Redis server and Python client
nikos add postgres   # PostgreSQL with pgvector and psycopg2
nikos add qdrant     # Qdrant vector database via Docker user service
nikos add zsh        # Zsh plus Starship prompt
nikos add act        # Run GitHub Actions locally
nikos add fabric     # Fabric AI pattern CLI
nikos add k8s-tools  # kubectl and Helm
nikos add bitnet     # BitNet.cpp 1-bit LLM inference
nikos add mistral-rs # mistral.rs Rust LLM server
nikos add monitoring # Netdata monitoring dashboard
nikos add openclaw   # OpenClaw LLM gateway CLI
nikos add ollama-models # Pull optional Ollama models; about 26 GB
```

## Changing the wallpaper

The wallpaper is `assets/wallpaper.svg` — a vector file exported to PNG on install. Edit the SVG directly and run `nikos update` to re-export and apply.

## Changing the timezone

The installer detects the system timezone via `timedatectl` and prompts you to confirm or
override it. The chosen value is written to `vars/local.yml` automatically.

To change it later, edit `vars/local.yml`:

```yaml
nikos_timezone: "America/New_York"
```

Use any IANA timezone identifier — list all available with `timedatectl list-timezones`.

Run `nikos update` to apply. The playbook sets the timezone and enables NTP via
`systemd-timesyncd` (no extra packages required).

## Adding a new role

1. Create `roles/my-role/tasks/main.yml`
2. Add it to `site.yml` under `roles:`
3. Test locally with `ansible-playbook site.yml --check --tags my-role`
4. Run: `nikos update`

## Using your own fork

Fork `nikolareljin/nikos` on GitHub, then install from your fork:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_USER/nikos/main/install.sh | bash
```

Or set `NIKOS_REPO_URL` to your fork URL before running the installer:

```bash
NIKOS_REPO_URL=https://github.com/YOUR_USER/nikos bash install.sh
```

This keeps `install.sh` unmodified and works with the repo-sync flow (`nikos update` will continue pulling from your fork).
