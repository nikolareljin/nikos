# Customization

Bundles — the optional parts of NikOS you pick at install time, and how that
list is meant to be published — are described in `docs/bundles.md`.

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
  - "qwen3-coder:30b"
  - "deepseek-coder-v2:16b"
  - "deepseek-r1:8b"
# Other good choices: gemma3, mistral-small3.2, devstral, granite4
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

## Changing the Ollama models

Edit `vars/local.yml`:

```yaml
ollama_default_model: "qwen3:8b"
```

Then run `nikos update`. The new model is pulled on the next playbook run.

### The default

`qwen2.5-coder:7b` (4.7 GB). It stays on the 2.5 generation deliberately:
`qwen3-coder` publishes no tag below `30b` (19 GB), which is too large to pull
onto every machine by default.

### The optional bundles

Models are grouped by what they are for, and each group has its own tag, so a
laptop can take one capability without pulling all of them:

```bash
nikos add ollama-reasoning   # ~23 GB  general purpose reasoning
nikos add ollama-coding      # ~34 GB  code models
nikos add ollama-text        # ~22 GB  text generation and chat
nikos add ollama-vision      # ~13 GB  image analysis
nikos add ollama-embedding   # ~1.3 GB embeddings for the RAG stack
nikos add ollama-models      # ~93 GB  every group
```

Nothing here is pulled unless you ask for the tag. Override any group in
`vars/local.yml` to take a subset.

| Group | Model | Size | Notes |
|---|---|---|---|
| reasoning | `deepseek-r1:1.5b` | 1.1 GB | Runs on a 4 GB machine |
| reasoning | `qwen3:4b` | 2.5 GB | |
| reasoning | `deepseek-r1:8b` | 5.2 GB | |
| reasoning | `qwen3:8b` | 5.2 GB | Thinking mode |
| reasoning | `phi4:14b` | 9.1 GB | Desktop-class |
| coding | `deepseek-coder-v2:16b` | 6.4 GB | Mid-size |
| coding | `qwen2.5-coder:14b` | 9.0 GB | One size up from the default |
| coding | `qwen3-coder:30b` | 19 GB | Current generation, workstation-class |
| text | `granite4:micro` | 2.1 GB | Small enough to keep resident |
| text | `llama3.1:8b` | 3.2 GB | |
| text | `gemma3:4b` | 4.0 GB | |
| text | `mistral:7b` | 4.4 GB | |
| text | `gemma3:12b` | 8.1 GB | Multimodal |
| vision | `granite3.2-vision:2b` | 2.4 GB | Smallest, laptop-friendly |
| vision | `minicpm-v:8b` | 4.1 GB | |
| vision | `qwen2.5vl:7b` | 6.0 GB | Vision and document understanding |
| embedding | `embeddinggemma` | 622 MB | |
| embedding | `qwen3-embedding:0.6b` | 639 MB | |

Models load on demand, so none of this counts against the idle RAM target — it
is disk and bandwidth only.

### Models that were retired in 0.5.0

`codellama:7b`, `deepseek-coder:6.7b`, `gemma2:9b` and `llava:7b` were all two
years old and are no longer pulled. Each capability is covered by a newer model
above; Code Llama in particular has no successor, because Meta discontinued the
line, so its role passes to Qwen2.5-Coder and DeepSeek-Coder-V2. Any of them can
still be pulled by hand with `ollama pull`, or added back through
`ollama_models_coding` / `ollama_models_vision` in `vars/local.yml`.

## Image analysis and OCR

The `agent-dev` role installs an image analysis stack into the `nikos-ai` conda
environment, under the `ai-vision` tag:

| Package | Purpose |
|---|---|
| `opencv-contrib-python` | OpenCV with the contrib modules |
| `pillow` | Image loading and basic manipulation |
| `scikit-image` | Classical image processing algorithms |
| `imageio` | Image and video I/O |
| `pytesseract` | Python binding for the Tesseract engine |
| `timm` | Pretrained vision backbones for torch |

`numpy`, `pandas`, `scikit-learn` and `matplotlib` are already installed by the
`ai-stack` role.

OpenCV's wheels are dynamically linked, so `libgl1`, `libglib2.0-0t64`,
`libsm6`, `libxext6` and `ffmpeg` are installed alongside them — without those,
`import cv2` fails with `libGL.so.1: cannot open shared object file` on a
minimal host.

### Tesseract languages

Tesseract performs OCR — it reads text out of images. It does not translate;
pair it with a language model for that.

English, French, German, Spanish, Italian, Portuguese, Russian, Greek and
Serbian are installed by default, plus `osd` for orientation and script
detection. Change the set in `vars/local.yml`:

```yaml
nikos_tesseract_languages:
  - eng
  - jpn
  - chi-sim
```

Ubuntu ships over 160 language packs; `apt-cache search '^tesseract-ocr-'`
lists them. To install every one:

```yaml
nikos_tesseract_languages: ["all"]   # pulls tesseract-ocr-all
```

You can also pull models manually at any time:

```bash
ollama pull gemma3:4b
ollama pull granite4:micro
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
nikos add bitnet     # BitNet.cpp 1-bit LLM inference (bitnet-cli)
nikos add mistral-rs # mistral.rs Rust LLM server
nikos add monitoring # Netdata monitoring dashboard
nikos add openclaw   # OpenClaw LLM gateway CLI
nikos add ollama-models # Pull every optional Ollama model; about 93 GB
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

## Node.js for the npm-only CLIs

Gemini CLI and OpenClaw are published through npm only, so a Node new enough
for them has to exist. Claude Code no longer needs one - it installs a
standalone binary.

NikOS does **not** install Node from apt. Ubuntu 24.04 ships Node 18, and the
NodeSource package conflicts with Ubuntu's `npm`, so upgrading in place removes
`npm` and takes `eslint`, `webpack`, `node-tap` and around fifteen Debian
`node-*` packages with it. That is a large and surprising change to make to a
developer's machine in order to install two CLIs.

Instead:

1. The Node first on your `PATH` is checked against `nikos_node_min_version`.
2. If it qualifies, it is used as-is.
3. If not, nvm is installed (when missing) and `nikos_node_version` is
   installed and set as the default.

When the nvm path is taken, the global npm prefix sits under your home, so the
CLIs install without root and cannot collide with the distribution's packages.

```yaml
nikos_node_min_version: "22.22.3"   # OpenClaw's floor; anything at or above this is accepted
nikos_node_version: "22.23.2"       # installed through nvm when the check fails
nikos_nvm_version: "v0.40.7"
```

The minimum is a full version rather than a major on purpose: OpenClaw requires
`>=22.22.3`, and a major-only test would accept 22.22.2 and then fail at
install time.

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
