# Changelog

All notable changes to NikOS are documented here.

## [0.6.0] — 2026-08-21

### Fixed
- **The Whisker Menu button drew a missing-image placeholder** - the icon was
  installed under hicolor, the icon cache was current, and `GtkIconTheme`
  resolved the name, but gdk-pixbuf refused the file with
  `Unrecognized image file format (3)`. gdk-pixbuf picks a loader by matching
  the head of a file against each loader's signature, and the SVG signature is
  the literal `<svg`. `menu-icon.svg` opened with a comment block between the
  XML declaration and the root element, which pushed `<svg` past the window
  gdk-pixbuf looks at. `logo.svg` and `wallpaper.svg` carry `<svg` on line 2,
  so only the menu icon was affected. The comment now sits inside the root
  element. `assets/wallpaper-vertical.svg` had the same defect, latent, since
  nothing loads it through gdk-pixbuf.
- **The wallpaper read as a framed panel on wide monitors** - both wallpapers
  filled their background with a diagonal gradient and a centre glow, while
  xfdesktop paints a flat `#2e3440` behind them. The image is drawn Scaled, so
  on a 3440x1440 screen it covers 2560px and the lighter gradient region ended
  visibly where the flat colour began. Both now use the same flat `#2e3440`.
  Marks, wordmark, taglines and every coordinate are unchanged.
- **Artwork changes never reached an existing install** - both wallpaper PNG
  exports were guarded by `creates:`, so a machine that already had a PNG kept
  the artwork it was first installed with, `nikos update` included. They now
  re-export when the SVG changes or the PNG is missing.
- **A re-rendered wallpaper needed a logout to appear** - the backdrop path
  does not change between releases, so re-setting it to the same value emits no
  xfconf signal and xfdesktop keeps serving the image it cached at session
  start. `xfdesktop --reload` now runs after the wallpaper pass.
- **A reinstall could not fix the menu icon on an affected machine** - GTK
  searches `~/.icons` and `~/.local/share/icons` ahead of `/usr/share/icons`, so
  a copy of `nikos-menu.svg` in either shadows the one the role installs and
  rewriting the system icon changes nothing on screen. Earlier NikOS builds left
  one behind. The theming role now removes the user-level copies and rebuilds
  the icon cache that listed them, so the system icon is the only one left.

### Added
- **A full boot splash, including passphrase entry** - the Plymouth theme
  shipped one image, the colour logo, and a script that pulsed it. No password
  handler was registered and no dialog existed to draw, so a machine with an
  encrypted root sat on a static logo while it waited for a passphrase, with
  nothing on screen to say so. `nikos.script` now registers refresh, boot
  progress, password, normal, message, status and quit handlers, covering
  passphrase entry, boot progress, fsck progress and shutdown.
- **Boot chrome rendered from the existing artwork** -
  `scripts/render-plymouth-assets.py` generates the greyscale set the splash
  needs: the mark and wordmark from `plymouth-logo.svg`, and the spinner and
  passphrase bullet from `menu-icon.svg`, which is the cut of the mark drawn to
  survive icon sizes. Progress meters and the passphrase dialog are drawn to
  match. Everything is transparent and desaturated, because the splash sets its
  own background and the mark's blue reads as a colour cast on a dim
  framebuffer. The output is committed, so nothing is rendered on the target
  machine.
- **Tests for the artwork and the splash** - `tests/test_assets.py` requires
  every asset SVG to expose its root element inside the gdk-pixbuf sniff
  window, and the wallpaper backdrop to stay a flat colour matching the `rgba1`
  value in `xfce4-desktop.xml`. `tests/test_plymouth_theme.py` checks that the
  splash registers every handler it needs, that every image it loads is
  committed, that the spinner sequence has no gaps, and that the artwork stays
  transparent and desaturated. The splash cannot be exercised locally:
  `plymouthd` takes exclusive control of the framebuffer and Ubuntu ships no
  X11 renderer for it, so anything past these checks needs a reboot or a VM.

## [0.5.0] — 2026-08-20

### Fixed
- **The installer could not update its own checkout** - installing a release
  tag leaves `~/.local/share/nikos` on a detached HEAD. The next run began with
  `git pull --ff-only` on that checkout, which has no upstream to merge, so it
  failed with `You are not currently on a branch` and exited before reaching
  the code that would have switched refs. Every install after a tag install
  failed this way. The sync now fetches first, switches to the target ref, and
  only fast-forwards when HEAD is on a branch with an upstream. The same guard
  covers `nikos update`.
- **`install.sh` guessed the version from its surrounding directory** - the ref
  was inferred from whatever git checkout the script happened to sit in, so
  `curl | bash` in a project directory could pick up an unrelated repository's
  branch name. Version selection is now explicit.
- **image-view was never built, silently** - the cargo version was read with
  `regex_search('[0-9]+\\.[0-9]+\\.[0-9]+')`, and inside a folded YAML scalar
  that backslash does not survive to the regex. The pattern never matched, the
  version fell back to `0.0.0`, and `0.0.0` is below the 1.85 gate the build
  requires - so the build was skipped on every run and reported as "cargo too
  old" no matter which cargo was installed. Matching the dot with `[.]` needs
  no escaping and cannot regress the same way.
- **The cargo resolver returned three lines** - it used `command -v rustup
  &>/dev/null`, and `ansible.builtin.shell` runs `/bin/sh`, which is dash on
  Ubuntu. There `&>` means "run in the background, then redirect nothing", so
  the probe printed the path it was meant to suppress. The multi-line result
  was then passed to `command` as if it were one path, producing
  `error: unexpected argument` where a version string was expected, an empty
  version fact, and a hard failure from the `version` test. Now POSIX
  redirection, and only the last line is used.
- **The AI CLIs ran under the wrong Node** - the role added the NodeSource
  repository and then installed `nodejs` with `state: present`, which does
  nothing when a `nodejs` package is already there. Ubuntu 24.04 ships Node 18,
  so the repository was configured and the package never moved: Gemini CLI then
  failed with `EBADENGINE ... required: { node: '>=20' }, current: v18.19.1`.
  Forcing the upgrade is not the fix either - the NodeSource package conflicts
  with Ubuntu's `npm` and removes `eslint`, `webpack` and a dozen Debian
  `node-*` packages with it. NikOS now uses the Node already on `PATH` when it
  meets `nikos_node_min_version`, and otherwise installs nvm and a pinned Node
  under the user's home, where the npm prefix needs no root.
- **`npm` global installs could be blocked permanently** - npm stages an
  upgrade by renaming the existing package aside, and an abandoned staging
  directory from an interrupted run makes every later install fail with
  `ENOTEMPTY`. One had been sitting in `/usr/local/lib/node_modules/@google`
  since March. These are now cleared before the npm tasks run.
- **The AI CLIs never upgraded** - Gemini CLI and Claude Code used
  `state: present` and OpenClaw guarded on `creates: /usr/bin/openclaw`, so
  each was resolved once at first install and then stayed frozen at that
  version forever, `nikos update` included. All three now use
  `state: latest`.
- **`gh extension install github/gh-copilot` failed the play** - gh 2.98.0
  promoted `copilot` to a built-in command, and `gh extension install` rejects
  any extension whose name collides with one (`"copilot" matches the name of a
  built-in command or alias`). Because `gh` is installed from GitHub's apt
  repository and is not pinned, this began failing on its own. The role now
  asks whether gh can already run `copilot` and installs the extension only
  when it cannot, so it works either way.
- **Stale repo sync helpers on upgrade** - the installer sourced
  `scripts/repo-sync.sh` from `NIKOS_HOME`, which belongs to the *installed*
  version. Upgrading from 0.4.2 would load a copy with none of the functions
  this installer calls. Each candidate is now checked for what it must provide,
  and a stale one is replaced from the remote.
- **Wallpaper stayed on the Xubuntu default** - the Xubuntu session puts
  `/etc/xdg/xdg-xubuntu` ahead of `/etc/xdg` in `XDG_CONFIG_DIRS`, so
  `xubuntu-default-settings`' `xfce4-desktop.xml` shadowed the NikOS copy, and
  xfdesktop seeded every connector-named backdrop
  (`monitorHDMI-A-0`, `monitorDisplayPort-2`, ...) from its `image-path` values
  at first login. The role's own fixups could not counter that: they edited a
  user file that does not exist until a session has run, and called
  `xfconf-query` at install time when no `xfconfd` is listening. NikOS now
  repoints the Xubuntu defaults as well, and ships
  `/usr/local/bin/nikos-apply-wallpaper` plus an `/etc/xdg/autostart` entry that
  sets every backdrop once, inside the session, after xfdesktop has registered
  the real monitors.
- **Ubuntu hosts never switched to Xubuntu** - the desktop role probed a single
  `gnome-session` package to decide whether it was migrating an Ubuntu install.
  Ubuntu 24.04 ships `ubuntu-session`, `gnome-session-bin` and
  `gnome-session-common` instead, so `dpkg-query` reported "not installed" and
  the whole migration block was skipped. Detection now reads the full package
  list through `package_facts`.
- **Display manager handover** - the role only wrote
  `/etc/X11/default-display-manager`, which systemd does not read.
  `systemctl enable lightdm` cannot take the `display-manager.service` alias
  while GDM3 owns it, so Ubuntu hosts kept booting into the GNOME greeter. The
  role now pre-seeds the `shared/default-x-display-manager` debconf answer,
  rewrites the `display-manager.service` symlink, disables `gdm3` without
  removing it, and asserts the result before the play ends.
- **Default session** - LightDM kept honouring the session recorded for an
  existing account, dropping migrated users straight back into GNOME. The role
  now writes `Session`/`XSession` to the AccountsService user file and ships
  `/etc/lightdm/lightdm.conf.d/60-nikos.conf` with the seat defaults.
- **llama.cpp install** - `unarchive` targeted `/tmp/llama-<version>` without
  creating it first, failing with `dest must be an existing dir`. The directory
  is created up front and the whole llama.cpp sequence now runs inside a
  `block`/`rescue`, so a download or release-asset failure no longer aborts the
  play and skips every role after `ai-stack`.
- **llama.cpp archive layout** - the role expected `build/bin/llama-cli`, a path
  that no longer exists in the b9151 release. The binaries are now located with
  `find`, and because they carry `RUNPATH=$ORIGIN` and need `libllama.so` and
  the `libggml*.so` set beside them, the release tree is installed whole under
  `~/.local/lib/llama.cpp-<version>` and symlinked into `~/.local/bin`. The
  install is keyed on the version directory, so a version bump reinstalls and a
  rerun does not.
- **VS Code install** - the task carried `cache_valid_time: 3600` while the
  `base` role refreshes the apt cache at the start of the same play, so the
  update that would first fetch the repository added moments earlier was always
  skipped and the install failed with `No package matching 'code' is available`.
  The cache refresh is now its own unconditional task.
- **Plymouth theme note** - the role tried to purge `xubuntu-plymouth-theme`,
  a package that does not exist on noble. The real themes are
  `plymouth-theme-xubuntu-logo` and `plymouth-theme-xubuntu-text`, which
  `xubuntu-artwork` depends on; NikOS keeps them installed and wins through the
  manually selected `default.plymouth` alternative instead.

### Changed
- **Pinned dependency versions moved forward**, deliberately not to the newest
  release of each:

  | | Was | Now |
  |---|---|---|
  | llama.cpp | `b9151` | `b10444` |
  | Miniforge | `24.11.3-0` | `26.3.2-3` |
  | Kubernetes apt | `v1.35` | `v1.36` |
  | conda Python | `3.11` | `>=3.11,<3.14` |

  llama.cpp cuts several releases a day and `b10549` was published the same
  morning; `b10444` had a week to settle. Miniforge `26.5.3-0` was six days
  old against `26.3.2-3`'s two and a half months. `mkcert` (`v1.4.4`) and the
  Nordic theme (`v2.2.0`) are already on their latest releases and are
  unchanged. Node stays on the 22.x LTS line and Java on 21 rather than
  moving to Node 24 or JDK 25.

  The conda Python pin becomes a range. An exact minor makes the environment
  unsolvable the moment one dependency drops support for it, and nothing in
  the AI stack needs a specific 3.1x. Set `nikos_python_version: "=3.12"` in
  `vars/local.yml` to pin hard again.

### Changed
- **Claude Code installs its native binary** rather than a global npm package.
  It ships a standalone build that needs no Node at all, and its installer
  refuses to run under sudo - with sudo the binary lands in root's home and the
  `claude` command is missing from the user's shell.

### Added
- **Ollama models grouped by capability.** `ollama_models_reasoning`,
  `_coding`, `_text`, `_vision` and `_embedding`, each with its own tag, so a
  laptop can take one capability without pulling the rest:
  `nikos add ollama-vision` (~13 GB) instead of `nikos add ollama-models`
  (~93 GB). Every group lists its smallest usable model first;
  `deepseek-r1:1.5b` runs on a 4 GB machine.
- **Model refresh.** `codellama:7b`, `deepseek-coder:6.7b`, `gemma2:9b` and
  `llava:7b` were all two years old and are replaced rather than kept:
  Code Llama has no successor at all, since Meta discontinued the line, so its
  role passes to `qwen2.5-coder:14b` and `deepseek-coder-v2:16b`;
  `gemma2:9b` -> `gemma3:12b`; `llava:7b` -> `qwen2.5vl:7b`,
  `minicpm-v:8b` and `granite3.2-vision:2b`. New additions cover reasoning
  (`deepseek-r1`, `qwen3`), text generation (`granite4`, `llama3.1`,
  `mistral`) and current embeddings (`embeddinggemma`,
  `qwen3-embedding:0.6b`, replacing the two-year-old `nomic-embed-text`).
  Nothing on the list is now older than about a year. The default stays
  `qwen2.5-coder:7b`, because `qwen3-coder` publishes no tag below `30b`
  (19 GB).
- **Image analysis stack** (`ai-vision` tag) - `opencv-contrib-python`,
  `pillow`, `scikit-image`, `imageio`, `pytesseract` and `timm` in the
  `nikos-ai` environment, with the shared libraries OpenCV's wheels link
  against (`libgl1`, `libglib2.0-0t64`, `libsm6`, `libxext6`, `ffmpeg`) so
  `import cv2` also works on a minimal host.
- **Tesseract OCR** with `osd` and nine language packs by default, selectable
  through `nikos_tesseract_languages`; set it to `["all"]` for all 160+.
- **Version selection.** With no options the installer resolves and installs the
  newest release tag (`X.Y.Z`; pre-release and floating tags are ignored).
  `--ref <branch-or-tag>` pins a specific ref, and `NIKOS_REPO_REF` is
  equivalent. `install.sh --help` documents both.
- **`--dev` mode.** Runs the checkout the script lives in, exactly as it stands,
  including uncommitted changes. Nothing is cloned, fetched, pulled or stashed
  and `~/.local/share/nikos` is left untouched, so testing a branch cannot
  damage a working install. Refuses to run outside a NikOS checkout, and cannot
  be combined with `--ref`.
- **`nikos update --ref <branch-or-tag>`.** Bare `nikos update` now advances a
  release install to the newest release and keeps a branch install on its
  branch, so an update never downgrades.
- `scripts/repo-sync.sh` is covered by the `shellcheck` gate and by 36 new tests
  in `tests/test_version_select.py`, including a regression test that reproduces
  the detached-HEAD failure.
- **Xubuntu desktop packages** - `xubuntu-desktop-minimal`,
  `xubuntu-default-settings` and `xubuntu-artwork` replace the bare `xfce4`
  install, which is what provides the Xubuntu session and the Xubuntu login
  form. `nikos_desktop_flavor` selects between `xubuntu-minimal` (default),
  `xubuntu-full` and `xfce`.
- **Desktop migration variables** - `nikos_remove_gnome` (default `false`,
  GNOME stays selectable from the greeter), `nikos_disable_gdm`,
  `nikos_default_session` and `nikos_gnome_packages`.
- **Installer progress UI** - `scripts/nikos-progress.sh` renders the playbook
  as a `dialog --mixedgauge`: one row per role with Succeeded/Failed/In
  Progress, an overall percentage counted against
  `ansible-playbook --list-tasks`, and the current task as the caption.
- **NikOS menu button icon** - `assets/menu-icon.svg`, installed as
  `nikos-menu` under `/usr/share/icons/hicolor/scalable/apps`. The Whisker Menu
  button kept the Xubuntu mouse (`xubuntu-logo-menu`) because
  `/etc/xdg/xdg-xubuntu/xfce4/whiskermenu/defaults.rc` shadows the NikOS
  defaults the same way the wallpaper file did; that copy and any existing
  per-user `whiskermenu-*.rc` are now pointed at the NikOS icon. The NikOS
  defaults themselves named `/usr/share/nikos/wallpaper.png` as the button
  icon, which is a 1920x1080 wallpaper, not an icon.
- **Portrait wallpaper** - `assets/wallpaper-vertical.svg`, exported to
  `/usr/share/nikos/wallpaper-vertical.png`. Monitors in vertical orientation
  get the portrait cut; every other monitor gets the landscape one.
- **Backdrop colour matches the artwork** - backdrops are Scaled rather than
  Zoomed, so nothing is cropped, and `color-style`/`rgba1` are set to `#2e3440`,
  the flat base colour of both wallpapers, so the area an aspect ratio does not
  cover reads as part of the image.
- **Wallpaper follows monitor changes** - the marker file records the monitor
  layout the wallpaper was last applied to. Rotating, adding or removing a
  monitor re-applies at the next login, but only over backdrops still holding a
  NikOS wallpaper, so a wallpaper the user picked themselves is left alone.

### Changed
- **Installer no longer runs the playbook under a pty** - `script -qefc` forced
  Ansible into colour mode and the escape sequences were rendered as literal
  text by `dialog --progressbox`. The playbook now runs with colour disabled and
  every stream is ANSI-stripped before it reaches dialog or the log.
- **Log ANSI stripping** - the strip expressions run under `LC_ALL=C`; under a
  UTF-8 locale the `[ -/]` and `[@-~]` ranges follow collation order and stop
  matching escape sequences.
- **Completion message** - the installer now says whether a reboot or a log-out
  is needed, based on the session that is currently running.
- Version bumped `0.4.2` -> `0.5.0`.

## [0.4.2] — 2026-05-22

### Fixed
- **Installer Ansible compatibility failure** - dialog installs now use a
  version-compatible `--become-password-file`, offer to upgrade
  `ansible-playbook` versions older than the role minimum before the playbook
  starts, and pin `community.general` to a collection release compatible with
  that minimum.
- **Dialog sudo password handling** - dialog installs now pass the sudo password
  through a `0600` temporary become-password file after the Ansible version gate,
  reducing plaintext exposure in process environments.
- **Dialog cursor cleanup** - the installer restores the terminal cursor through
  the controlling terminal after progress dialogs, on normal exit, and when
  interrupted.
- **Supported OS guard** - the installer now verifies it is running on Ubuntu
  24.04 before installing bootstrap packages, instead of accepting any
  apt-based distribution.
- **Release checkout inference** - the installer now follows exact tag checkouts
  when launched from a detached HEAD, unless `NIKOS_REPO_REF` is set.
- **GRUB splash determinism** - theming replaces an existing `nosplash` kernel
  command-line token with `splash` before enforcing Plymouth splash support.
- **CI helper alignment** - release tag checks and auto-tagging now use the
  current reusable `ci-helpers` workflows from `@production`, and the dry-run
  playbook check runs through the reusable workflow's test phase.
- **Plymouth helper availability** - theming no longer fails when
  `plymouth-set-default-theme` is unavailable; NikOS still configures Plymouth
  through `plymouthd.conf` and the `default.plymouth` alternative.
- **NikOS Plymouth logo embedding** - theming now enables Plymouth framebuffer
  hooks for initramfs generation and installs `plymouth-label`, ensuring the
  custom NikOS logo theme is included in rebuilt boot images instead of the
  default Xubuntu mouse splash.
- **Release branch installer testing** - installer runs now keep the persistent
  `NIKOS_HOME` checkout on the same non-main branch as the installer source, or
  on `NIKOS_REPO_REF` when explicitly set.
- Version bumped `0.4.1` -> `0.4.2`.

## [0.4.1] — 2026-05-14

### Fixed
- **NikOS Plymouth logo missing after install** — the playbook now forces
  handlers to run even if a later non-critical task fails, selects the `nikos`
  Plymouth theme through `plymouth-set-default-theme`, and rebuilds initramfs
  for all installed kernels so the boot splash assets are embedded reliably.
- **mkcert install failure** — fixed the GitHub release asset URL by pinning
  `mkcert_version` and using the actual upstream asset name.
- **image-view optional build noise** — the role now checks Cargo version first
  and skips cleanly with a warning when Cargo is older than 1.85, avoiding an
  ignored failure caused by `edition2024` dependencies.
- Version bumped `0.4.0` → `0.4.1`.

## [0.4.0] — 2026-05-14

### Added
- **Core developer additions** — base installs now include `tmux`, `pipx`,
  `sqlite3`, and `unzip`, plus a Nord-compatible default `~/.tmux.conf` that is
  deployed with `force: false`.
- **Expanded AI workstation tooling** — `llama.cpp` CPU binaries are installed
  as `llama-cli` and `llama-server`, optional Ollama model pulls are available
  through the `ollama-models` tag, and the `nikos-ai` environment now includes
  additional ML/data packages for embeddings, RAG, datasets, evaluation, and CLI
  database work.
- **Cloud and local CLI tools** — Node.js moves to NodeSource 22.x, and
  `shell-gpt`, `glances`, and `mkcert` are installed as core utilities.
- **New optional bundles** — `bun`, `redis`, `postgres`, `qdrant`, `zsh`, `act`,
  `fabric`, `k8s-tools`, `bitnet`, `mistral-rs`, `monitoring`, and `openclaw`.

### Changed
- **Installer optional bundle selection** now exposes the expanded bundle set and
  runs an explicit tagged pass for opt-in roles that are guarded with `never`.
- **`nikos add`** now supports every optional bundle tag, and `nikos doctor`
  checks for the new core tools.
- **First terminal session** now shows a short one-time NikOS welcome with the
  core commands to start, check, and update the system.
- Version bumped `0.3.2` → `0.4.0`.

## [0.3.2] — 2026-04-23

### Changed
- **Full dialog UI for `install.sh`** — every installation step now uses the `dialog`
  TUI when available, not just the interactive selections. Changes:
  - Welcome screen uses `dialog --msgbox` (user presses OK to proceed).
  - System requirements check uses `dialog --infobox`; failure shown in `dialog --msgbox`.
  - Bootstrap package installation shows `dialog --infobox` before running `apt-get` (only when `dialog` is already present; falls back to plain text when it is being installed as part of the bootstrap).
  - Repository clone and update steps show `dialog --infobox` status messages.
  - Ansible collections install shows `dialog --infobox` before running `ansible-galaxy`.
  - Ansible playbook execution: output streamed inside `dialog --progressbox`;
    `dialog --passwordbox` collects the sudo password and passes it to Ansible via
    a temporary `--become-password-file` instead of storing the password in the environment.
  - Install summary shown in `dialog --msgbox` after the plain-text summary.
  - All changes are guarded by `_USE_DIALOG` and `_can_use_dialog()` checks;
    plain-text fallbacks remain unchanged.
- Version bumped `0.3.1` → `0.3.2`.

## [0.3.1] — 2026-04-22

### Fixed
- **Plymouth boot splash overridden by xubuntu-plymouth-theme** — The NikOS splash
  was replaced by the Xubuntu mouse/spinner on every apt operation because
  `xubuntu-plymouth-theme`'s dpkg postinst calls `plymouth-set-default-theme xubuntu-logo`, resetting `plymouthd.conf` and rebuilding initramfs. Fixed by:
  (1) purging `xubuntu-plymouth-theme` during theming role execution;
  (2) registering the NikOS theme with `update-alternatives --install` at
  priority 200 and explicitly selecting it with `update-alternatives --set`,
  so Plymouth uses NikOS regardless of whether the group is in auto or manual mode;
  (3) ensuring the `ini_file` task notifies `Theming_update_initramfs`, so
  initramfs is rebuilt when `plymouthd.conf` changes.

## [0.3.0] — 2026-04-17

### Added
- **Optional Neovim bundle** — new `neovim` role installs `neovim`, creates
  `~/.config/nvim/`, and deploys a minimal `init.lua` that bootstraps `lazy.nvim`.
  The config is written with `force: false` so an existing Neovim setup is preserved.
- **Optional Java bundle** — new `java` role installs `openjdk-21-jdk`.
- **Optional Podman bundle** — new `podman` role installs `podman`.

### Changed
- **Optional role wiring** — `site.yml` now registers `neovim`, `java`, and `podman`
  with explicit tags, and `nikos add` now accepts all three bundles.
- Version bumped `0.2.1` → `0.3.0` in `vars/main.yml`, `install.sh`, `scripts/nikos`,
  and `README.md`.
- **Documentation refresh** — install, development, and debugging docs now list the new
  optional bundles and updated dry-run examples.

## [0.2.1] — 2026-04-16

### Added
- **Interactive timezone selection** — `install.sh` now detects the system timezone via
  `timedatectl` and presents a selection step during install (dialog TUI or plain prompt).
  Options: use the detected system timezone, keep an already-configured value, or enter a
  custom IANA timezone (e.g. `America/New_York`). The chosen timezone is written to
  `vars/local.yml` so subsequent `nikos update` runs respect it. `vars/main.yml` retains
  `Europe/London` only as a last-resort fallback for non-interactive runs without a
  `vars/local.yml`. Re-running the installer on a system that already has a timezone
  configured defaults to keeping the existing value and offers NTP auto-detect or custom as
  alternatives.
- **NTP synchronization enabled** — the `base` role now runs `timedatectl set-ntp true`
  after setting the timezone, activating `systemd-timesyncd` (present on Ubuntu by default,
  no extra packages required). The hardware clock is also set to UTC.
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
- **`image-view` build failure on Cargo.lock v4** fixed. When the cloned `image-view` repo
  contains a `Cargo.lock` generated by Cargo 1.78+ (version 4 format), older apt-installed
  Cargo (1.75.x) refuses to parse it. The `dev-tools` role now removes `Cargo.lock` before
  the build when the binary is not yet installed, letting the installed Cargo regenerate the
  lock file in the correct format. On systems where `image-view` is already installed the
  delete step is skipped.
- **`nikos log` argument validation** — passing a non-numeric argument (other than `list`)
  to `nikos log` previously caused `tail` to fail under `set -e` with no clear message. The
  command now validates the argument and prints a usage hint before returning 1.
- **ansible-lint violations in `editors` role** — replaced the `shell: curl | gpg --dearmor`
  key-download task with two separate tasks (`get_url` + `command: gpg --dearmor`) to fix
  `command-instead-of-module` and `risky-shell-pipe` violations. Renamed registered variables
  to carry the role prefix (`editors_ext_result`, `editors_ai_ext_result`) to fix
  `var-naming[no-role-prefix]`.
- **shellcheck warnings in `scripts/nikos`** — separated `local` declarations from
  command-substitution assignments (`SC2155`); replaced `ls` with `find` in `nikos log list`
  (`SC2012`).

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
