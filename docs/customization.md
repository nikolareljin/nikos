# Customization

Bundles — the optional parts of NikOS you pick at install time, and how that
list is meant to be published — are described in `docs/bundles.md`.

Keep local overrides in `vars/local.yml`. `site.yml` loads `vars/main.yml` and
`vars/versions.yml` (every pinned version, hash, commit and key fingerprint) first, then
overlays any values from `vars/local.yml`, so updates can refresh tracked defaults without
clobbering your machine-specific settings. Override a pin and its hash or commit together.

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
nordic_gtk_sha256: "..."                 # change together with the URL
nikos_firefox_dark: true                 # false leaves Firefox alone
nikos_chromium_dark: true                # false leaves Chromium / Chrome alone

# ── Ollama ────────────────────────────────────────────
nikos_ai_model_tier: ""                  # small|standard|large|xlarge; empty measures

# ── Python ────────────────────────────────────────────
# Versions (Miniforge, llama.cpp, the pip packages) are pins: see "Pinned
# versions" below before overriding one.
nikos_conda_env: "nikos-ai"
nikos_python_version: "=3.12"            # a conda spec, operator included
nikos_aider_conda_env: "nikos-aider"     # aider has its own env; the `aider` launcher is in ~/.local/bin

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

NikOS theming (Nordic, Papirus-Dark, the NikOS wallpaper, GRUB and Plymouth
themes) runs after the desktop role in every case, so it layers on top of
whichever set you pick.

Browsers are dark in the desktop colour (#2E3440):

- Firefox: the built-in Dark theme plus a `userChrome.css` / `userContent.css`
  that paint the tab strip, toolbar, URL bar and new tab page one colour. The
  open tab is the NikOS accent, Nord frost `#88C0D0`, with dark text, so it
  stands out from the strip.
  Written as `NikOS dark Firefox` blocks, so your own lines in those files stay.
  `user.js` is read at every Firefox start, so the theme stays while this is
  on; `nikos_firefox_dark: false` and `nikos update` remove the blocks.
- Chromium (snap or deb) and Google Chrome: Classic mode, dark, seeded with the
  NikOS accent `#88C0D0`, set in each profile's Preferences. Chromium derives
  the frame and tab colours from the seed, so the open tab takes the accent's
  hue; one tab's exact colour cannot be set from Preferences. A profile still on
  the earlier seed (`#2E3440`) gets the new one at `nikos update`, and nothing
  else of its theme changes. The Chromium snap cannot
  read the host GTK theme, so GTK mode would fall back to light Adwaita. A
  browser that is running is skipped; close it and run `nikos-chromium-theme`.
  Each profile is set once (recorded in `~/.local/state/nikos/chromium-themed`),
  so a theme you pick later in "Customize Chromium" survives `nikos update`;
  `nikos-chromium-theme --force` sets it again.

Both apply to profiles that exist. Start a browser once, then run
`nikos update`, to theme a new profile.

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

Models come in modules, and each module pulls **one model per role, the one this
machine can run**. The model per role and class of machine is the fleet's approved set,
in `ai-models.env` (ADR-0058). The default module is always pulled; the others when
you ask:

```bash
nikos add ollama-text        # general, creative, extract, classify
nikos add ollama-reasoning
nikos add ollama-coding
nikos add ollama-vision
nikos add ollama-embedding
nikos add ollama-models      # every role
nikos add model qwen3:14b    # any other model, on purpose; updates keep it
```

| Module | Role | small | standard | large | xlarge |
|---|---|---|---|---|---|
| default, text | general | `qwen3.5:2b` | `qwen3.5:4b` | `qwen3.5:9b` | `qwen3.5:9b` |
| text | creative | `qwen3.5:4b` | `gemma4:latest` | `gemma4:latest` | `gemma4:latest` |
| text | extract | `qwen3.5:2b` | `qwen3.5:4b` | `qwen3.5:9b` | `qwen3.5:9b` |
| text | classify | `qwen3:1.7b` | `qwen3:1.7b` | `qwen3:1.7b` | `qwen3:1.7b` |
| reasoning | reasoning | `qwen3.5:4b` | `qwen3:8b` | `qwen3:8b` | `gpt-oss:20b` |
| coding | code | `qwen3.5:4b` | `qwen2.5-coder:7b` | `qwen2.5-coder:7b` | `qwen3-coder:30b` |
| vision | vision | `qwen3-vl:4b` | `qwen3-vl:4b` | `qwen3-vl:8b` | `qwen3-vl:8b` |
| embedding | embed | `nomic-embed-text` | `nomic-embed-text` | `nomic-embed-text` | `nomic-embed-text` |

Class of machine, measured by script-helpers (whole GiB):

- small: less than 11 GiB of memory and of GPU memory
- standard: the default
- large: a GPU with the role's large figure (11 GiB), or 30 GiB of memory
- xlarge: a GPU with the role's xlarge figure (15 GiB for reasoning, 23 for code)

A role with no model for a class uses the next one down.

Before each pull, script-helpers checks disk and memory; a model that does not fit
falls back one class. `nikos_ai_model_tier: small|standard|large|xlarge` in
`vars/local.yml` names the class instead of measuring it. `nikos models` shows the
class and the model per role.

`nikos update` pulls the default and the selected modules, so a machine moves to
the current approved set. Before it pulls, it offers to remove installed models
that are not approved for this machine, one question per model (`[y/N]`). Without
a terminal it lists them and removes nothing; `nikos models prune` asks again.
Models load on demand, so all of this is disk and bandwidth, not idle memory.

To use a model outside the set, `nikos add model <name>`. The set itself changes
in the fleet registry, which regenerates `ai-models.env`; it is not edited here.

### Models replaced in the next release

`deepseek-r1:1.5b`, `qwen3:4b`, `phi4`, `deepseek-coder-v2`, `qwen2.5-coder:14b`,
`llama3.1`, `gemma3`, `mistral:7b`, `granite3.2-vision`, `minicpm-v` and
`qwen2.5vl` are no longer pulled. Their places go to `gpt-oss`, `qwen3.5`,
`gemma4` and `qwen3-vl`, and the default moves to `qwen3.5:4b`. Models already on disk are not removed; `ollama rm <name>` frees
the space.

### Models that were retired in 0.5.0

`codellama:7b`, `deepseek-coder:6.7b`, `gemma2:9b` and `llava:7b` were all two
years old and are no longer pulled. Each capability is covered by a newer model
above; Code Llama in particular has no successor, because Meta discontinued the
line, so its role passes to Qwen2.5-Coder and DeepSeek-Coder-V2. Any of them can
still be pulled by hand with `ollama pull`, or added back through
`nikos add model <name>`.

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
ollama pull qwen3.5:4b
ollama pull granite4:micro
ollama list
```

## Pinned versions

Every external version NikOS installs (release archives, apt key
fingerprints, npm/pip/go packages, git checkouts) is pinned in
`vars/versions.yml`, with its sha256 or fingerprint next to it. Override a pin
in `vars/local.yml` only together with its hash. On `nikos update` a pin is a
minimum: something newer you installed yourself is left alone. To move the
pins forward, use `scripts/bump-versions.py` (docs/development.md).

## GPU drivers

On an NVIDIA GPU with no driver loaded, the `ai-stack` role runs Ubuntu's
`ubuntu-drivers install`, which picks Canonical's recommended driver from the
signed archive; reboot afterwards. Image builds skip it. To leave GPU drivers
alone:

```yaml
nikos_nvidia_drivers: false
```

## Adding VS Code extensions

Add extension IDs (from the VS Code Marketplace URL) to `nikos_vscode_extensions` in `vars/local.yml`, then run `nikos update`.

## Adding optional bundles

```bash
nikos add network    # nmap, wireshark, OpenVPN, traceroute, tcpdump
nikos add music      # LMMS, Ardour (Flatpak), Audacity
nikos add education  # LibreOffice, draw.io (Flatpak), Anki
nikos add neovim     # Neovim plus a minimal lazy.nvim bootstrap config
nikos add java       # OpenJDK 21; set nikos_java_versions: [21, 17, 25] for more
nikos add podman     # Podman container runtime
nikos add bun        # Bun JavaScript runtime
nikos add redis      # Redis server and Python client
nikos add postgres   # PostgreSQL with pgvector and psycopg2
nikos add mongodb    # MongoDB Community, mongosh, Atlas CLI and pymongo
nikos add qdrant     # Qdrant vector database via Docker user service
nikos add zsh        # Zsh plus Starship prompt
nikos add act        # Run GitHub Actions locally
nikos add fabric     # Fabric AI pattern CLI
nikos add jev        # Jev client: official TypeSafe SDK + `jev` command (run `jev login` with your key)
nikos add k8s-tools  # kubectl and Helm
nikos add bitnet     # BitNet.cpp 1-bit LLM inference (bitnet-cli)
nikos add mistral-rs # mistral.rs Rust LLM server
nikos add monitoring # Netdata monitoring dashboard
nikos add openclaw   # OpenClaw LLM gateway CLI
nikos add ollama-models # Every module: this machine's model per role (12 GB small, 28 GB standard, 34 GB large, 57 GB xlarge)
```

### MongoDB

`nikos add mongodb` adds the vendor apt repository for the series in
`mongodb_series` (default `8.2`, signed with the 8.0 key in
`mongodb_key_series`), installs `mongodb-org`, `mongosh` and the
Atlas CLI, starts `mongod` bound to `127.0.0.1:27017`, and installs `pymongo`
into the `nikos-ai` env. Nothing logs in to MongoDB Atlas.

With Docker installed, the Atlas CLI can also run a local Atlas deployment,
which adds Atlas Search and Vector Search. NikOS does not start one; run it
yourself when you want it:

```bash
atlas deployments setup --type local
```

## Choosing distrodeck tools

NikOS installs only the distrodeck tools you pick, never the whole catalog.
The installer, `nikos setup` and `nikos add tools` read the catalog from
distrodeck itself (`distrodeck install-tools --list-catalog --format tsv`) and
offer it by category: a checklist in the TUI, or one prompt per category in
plain mode (Enter keeps the preselection, `-` for none, `*` for the whole
category). The answer is saved as `NIKOS_DISTRODECK_TOOLS_SAVED` in
`~/.config/nikos/selected-options.env`, and the `dev-tools` role installs
exactly that list with `distrodeck install-tools --tools <list>`.

Three adjustments are made to the list:

- distrodeck's `ollama` and `mongodb` are never offered or installed: NikOS
  owns both (`nikos_distrodeck_owned_tools`). Ollama comes from the ai-stack
  role, the one owner of the inference port; MongoDB from `nikos add mongodb`.
  A saved list that names them is installed without them, with a warning.
- A tool that needs something to install is given it, unless that is already
  chosen or installed. A catalog with a 7th `needs` column names the needs
  (`docker` is met by docker or podman). An older 6-column catalog has none,
  so the label decides: a `(container)` tool needs `docker`, a `plugin-*`
  needs `claude-code`. Without them distrodeck fails the whole run. Needs are
  listed before the tool that needs them (`postgresql` before `pgvector`),
  because distrodeck installs in the order given.
- When `nikos update` has moved distrodeck to a newer release, saved names
  that release no longer lists are skipped with a warning rather than sent to
  distrodeck, which would reject the whole list.

```bash
nikos add tools      # choose again and install the new list now
```

The catalog flag needs a distrodeck release that has it. `distrodeck_version`
is pinned in `vars/versions.yml` (`latest` follows the newest tag); a release that predates the flag
(0.10.3 and earlier, or one pinned in `vars/local.yml`) skips the screen with a
one-line note, and the `dev-tools` role falls back to the previous behaviour,
`distrodeck install-tools --all`.

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
3. Test locally with `ansible-playbook site.yml --check --tags my-role -e nikos_update_mode=false`
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
