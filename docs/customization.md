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

The wallpaper is a pair of vector files exported to PNG on install:

| File | Exported to | Used on |
| --- | --- | --- |
| `assets/wallpaper.svg` | `/usr/share/nikos/wallpaper.png` (1920x1080) | monitors in landscape orientation |
| `assets/wallpaper-vertical.svg` | `/usr/share/nikos/wallpaper-vertical.png` (1080x1920) | monitors rotated into portrait orientation |

Edit either SVG and run `nikos update` to re-export and apply.

Backdrops are set to Scaled, not Zoomed, so the whole image stays on screen
whatever the monitor aspect ratio is, and the backdrop colour is set to
`#2e3440` - the flat base colour of both wallpapers - so the remainder reads as
part of the artwork. Keep that colour in the SVG background if you replace the
artwork, or change `RGBA1` in `roles/theming/files/nikos-apply-wallpaper.sh` to
match your own.

Monitor orientation is read from `xrandr --listmonitors`, which already
reflects rotation, so a screen turned either way reports the taller geometry and
gets the portrait wallpaper.

xfdesktop only creates the per-connector backdrop properties once an Xfce
session is running, so the playbook cannot set them directly. NikOS installs
`/usr/local/bin/nikos-apply-wallpaper` and registers it under
`/etc/xdg/autostart`; it runs at login, after xfdesktop has registered the real
monitors, and records the monitor layout it applied to in
`~/.local/state/nikos/wallpaper-applied`. An unchanged layout is a no-op. A
changed one (a monitor rotated, added or removed) re-applies, but only over
backdrops still holding a NikOS wallpaper, so your own wallpaper is left alone.
Delete the marker to have it claim every backdrop again at the next login:

```bash
rm -f ~/.local/state/nikos/wallpaper-applied
```

Running it by hand applies the wallpaper to the current session immediately:

```bash
rm -f ~/.local/state/nikos/wallpaper-applied && nikos-apply-wallpaper
```

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

## Choosing which version to install

The installer defaults to the newest release tag. Two ways to override it:

```bash
bash install.sh --ref release/0.6.0   # a specific branch or tag
bash install.sh --dev                 # the checkout you launched it from
```

| Option | Env var | Effect |
|---|---|---|
| `--ref <ref>` | `NIKOS_REPO_REF` | Install that branch or tag instead of the latest release |
| `--dev` | `NIKOS_DEV=1` | Run the current checkout in place, uncommitted changes included; nothing is cloned, fetched or pulled, and `~/.local/share/nikos` is untouched |
| — | `NIKOS_HOME` | Where the persistent checkout lives (default `~/.local/share/nikos`) |
| — | `NIKOS_SKIP_REPO_SYNC=1` | Use whatever is already staged at `NIKOS_HOME`, without syncing it |

`--dev` and `--ref` are mutually exclusive: dev mode installs the tree in front
of it, so there is no ref to resolve.

Only bare `X.Y.Z` tags count as releases. A pre-release (`0.6.0-rc1`) or a
floating tag (`production`) is never picked automatically — install one with
`--ref`.

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

## Changing the menu button icon

The Whisker Menu button uses `assets/menu-icon.svg`, installed as the
`nikos-menu` icon under `/usr/share/icons/hicolor/scalable/apps`. Edit the SVG
and run `nikos update`; the panel picks the new icon up at the next panel start
(`xfce4-panel -r` applies it immediately).

To use a different icon, set `button-icon` to any icon name or absolute path in
`roles/desktop/files/whiskermenu-defaults.rc`. Note that the Xubuntu defaults in
`/etc/xdg/xdg-xubuntu/xfce4/whiskermenu/defaults.rc` are read before the NikOS
ones, so the desktop role rewrites the `button-icon` line there as well.
