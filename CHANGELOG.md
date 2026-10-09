# Changelog

All notable changes to NikOS are documented here.

## [1.2.0] - 2026-10-09

### Added
- `nikos clean` (`scripts/clean-caches.sh`) frees disk from caches nothing uses: Docker
  build cache unused for `--keep-days` (7), untagged images, `node_modules` in git
  repositories idle for `--idle-days` (30) with nothing uncommitted and nothing running
  from them (no process of yours inside, no running container bind-mounting them), and unused uv,
  pnpm, npm and pip cache entries. A dry run lists each item with its size; `--apply`
  removes. It never removes Docker volumes, containers, virtual environments, build
  output or tracked files, and calls no `docker volume` or `docker system prune`.
- The site lists `nikos clean`: the command table on the included page and the
  maintenance commands on the install page. The install page names the version it comes with.

### Fixed
- `nikos doctor` reported the Ollama forwarder down while containers were
  answered: it probed from the host with the bridge address as source, which was
  dropped. It probes from `127.0.0.1` now.
- `nikos doctor` warned "ufw is active" with ufw off: `ufw.service` stays active
  after it runs. It reads `ENABLED=` in `/etc/ufw/ufw.conf` now.

## [1.1.1] - 2026-10-08

### Fixed
- **`nikos update` to 1.1.0 failed at "Install the forwarder's network check":**
  `Destination directory /usr/local/libexec does not exist`. Ubuntu does not ship
  that directory; it is created first now. A test requires every file the
  forwarder installs to go into a directory Ubuntu ships or an earlier task
  creates, and `tests/machine/ollama_bridge_files.sh` runs the file tasks as root
  on a stock `ubuntu:24.04` (`NIKOS_MACHINE_TESTS=1`). The failed run stopped
  before any forwarder unit was written, so nothing half-installed was left.

### Added
- `tests/machine/ollama_bridge_systemd.sh` runs the forwarder for real under
  systemd on a stock `ubuntu:24.04`: a LAN inside `172.16.0.0/12` refuses it and
  nothing is installed; installed, a container is answered and a LAN machine
  with a route to the bridge address is not; a second run changes nothing;
  `off` removes every piece and nothing listens.

## [1.1.0] - 2026-10-08

### Added
- **Containers reach the local Ollama.** Ollama listens on loopback only, and a
  container arrives on the Docker bridge, so `host.docker.internal:11434`
  answered nothing. `roles/ai-stack` now installs a forwarder; Ollama itself
  stays on loopback.
  - `nikos-ollama-bridge.socket` listens on the Docker bridge address and
    `systemd-socket-proxyd` forwards to `nikos_ollama_host`. Only loopback and
    `172.16.0.0/12` may connect.
  - An nftables table of its own lets that address and port answer only `lo`,
    `docker0` and `br-*`, whatever the source address. The socket requires it,
    and the forwarder will not start without it (a `flush ruleset` from
    `nftables.service` would remove it; the table is loaded again after one).
    It never touches Docker's rules.
  - A network check, run by the play, by `nikos doctor` and before every start
    of the forwarder, refuses it where a LAN or VPN reaches into
    `172.16.0.0/12` (an address, a peer or a route), or where an interface named
    `br-*` is not Docker's. It fails closed. The proxy exits when idle, so a
    network that joins later is caught at the next start.
  - `nikos_ollama_bridge`: `auto` (a rootful Docker Engine's bridge; nothing
    without Docker, with rootless Docker or with Docker Desktop), `off`, or an
    address in `172.16.0.0/12`. Where the forwarder must not run, every piece of
    it is removed, after its units are confirmed stopped.
  - `nikos doctor` asks the forwarder for `/api/version`, checks the filter is
    loaded, runs the network check, names a socket left failed by refused
    starts, and warns when `ufw` would drop container traffic.

### Fixed
- The forwarder tasks in `post_tasks` (run again after every role, so Docker
  installed later in the same run is seen) were skipped under `--tags ai-local`:
  `include_role` does not hand its tags to the tasks it includes.
- The test workflow checks out the script-helpers submodule, as an installed
  machine has it. Without it, `scripts/nikos` falls back to its own output
  format, and five `nikos doctor` tests passed only on that fallback.

## [1.0.2] - 2026-10-04

### Added
- **Community files**: a code of conduct, contributing guide, security policy
  (private vulnerability reporting), support page, bug and feature issue
  forms, and a pull request template; the README and the site's help page ask
  for bug reports and contributions.

### Fixed
- **`nikos update` no longer stops at `numpy==2.5.3`.** numpy 2.5 needs
  Python 3.12, and an env created by an earlier release is 3.11, so the
  `ai-stack` role failed and every role after it was skipped. numpy is pinned
  to 2.4.6, which installs on 3.11, 3.12 and 3.13.
- **aider works on every install.** `aider-chat` pins each of its
  dependencies exactly, so in the shared `nikos-ai` env it and the data
  science packages overwrote each other's (12 conflicts in `pip check`), and
  it could not be installed at all into a Python 3.13 env. It now has its
  own `nikos-aider` env, with an `aider` launcher in `~/.local/bin`; the next
  `nikos update` creates it and removes aider from `nikos-ai`.
- **pip installs into a conda env ignore `~/.local`.** A package present in
  `~/.local/lib/pythonX.Y` counted as installed, so the env was left without
  it. `roles/pin-gate` now runs pip with `PYTHONNOUSERSITE=1`.
- **`bump-versions.py` checks Requires-Python**: `--verify` fails on a pip
  pin that does not install on every Python the env may have, and `--check`
  and `--bump` skip releases that do not.
- **Pull requests no longer wait forever on `check-playbook / ci`.** The
  dry-run job became a matrix, so its legs report under other names; an
  aggregate job reports the name the ruleset on `main` requires.
- **The lint, dry-run and release tag gate workflows run with a read-only
  token** (`permissions: contents: read`); they had no `permissions:` block,
  which code scanning flagged.

### Changed
- **`bump-versions.py --bump` moves every pin in one run, the Python packages
  included.** They go to their newest releases as a set, checked with
  `uv pip compile` on each Python the env may have; a package that breaks the
  set is held back and named.
- **Pins moved**: Ollama v0.35.1, llama.cpp b11321, Miniforge 26.7.2-0,
  Node.js 22.23.3, nvm v0.40.8. `openai` stays at 2.54.0: 3.x does not resolve
  with the other packages.

## [1.0.1] - 2026-10-04

### Fixed
- **The GRUB theme shows the NikOS logo.** It was text only, so no logo
  appeared. `logo.png` (from the Plymouth logo) is drawn above the menu;
  checked by booting the theme in QEMU at 1024x768 and 1920x1080. Ubuntu
  still hides the menu on a single-OS machine (hold Shift or Esc at boot to
  see it).
- **The docs and the GitHub Pages site describe 1.0.0**: verified installs
  and `vars/versions.yml`, apt key fingerprints, dark browsers, the log
  digest, the NVIDIA driver step and the private download/key directories.
  Stale GRUB theme paths (`themes/Nordic`) are corrected.

## [1.0.0] - 2026-10-04

### Breaking
Existing installs change on the first `nikos update` to 1.0.0:
- Ollama is installed from its release archive with a NikOS-written
  `ollama.service`, so it restarts once.
- Netdata comes from Ubuntu's `netdata` package (Netdata's repository on 26.04),
  not the kickstart script; the `gh-copilot` extension is no longer installed.
- Every external version is a pin in `vars/versions.yml`; on update a pin is a
  minimum, so nothing is downgraded.

### Added
- **Ubuntu and Xubuntu 22.04 and 26.04 LTS are supported** next to
  24.04. `install.sh` accepts all three; package names that differ are picked
  per release from `nikos_ubuntu_releases` in `vars/main.yml`. On 26.04 the
  `mongodb` bundle is skipped with a message (no vendor repository), and
  Netdata and Anki, which the archive dropped, come from verified vendor
  sources: Netdata's apt repository (key fingerprint-checked, bound to
  127.0.0.1) and the official Anki release tarball (sha256-checked). 22.04
  gets PostgreSQL without pgvector. 22.04 and 24.04 install exactly as before.
  The ISO stays Xubuntu 24.04.
- The installer's bundle menu says what a release lacks before you pick it,
  e.g. `MongoDB Community, mongosh and Atlas CLI (not available on 26.04)` or
  `PostgreSQL with pgvector (no pgvector on 22.04)`.
- The dry-run CI job runs on ubuntu-22.04, ubuntu-24.04 and ubuntu-26.04.
- `site.yml` stops with a clear message on an unsupported release, so
  `nikos update` (which skips `install.sh`) fails early instead of on a
  missing package name.

- **`scripts/bump-versions.py`**: `--check` lists each pin against the newest
  release at least 3 days old, `--bump NAME` moves a pin and records the new
  sha256 after cross-checking the vendor's sums file (for Claude Code, its
  manifest signed by the pinned release key), and `--verify` re-downloads
  every pin and compares. See docs/development.md.

### Changed
- **All pins live in `vars/versions.yml`**, one entry per dependency with its
  version, sha256 / commit / fingerprint and source. `site.yml` loads it after
  `vars/main.yml`; `vars/local.yml` still overrides.
- **Nothing is downloaded to a fixed `/tmp` path.** Root steps use
  `/var/lib/nikos/downloads` and user steps `~/.cache/nikos/downloads`, both
  0700, and apt keys are fetched, checked and dearmored as root in
  `/var/lib/nikos/keys`. At a predictable `/tmp` path another local user could
  plant a file with the right checksum, which `get_url` then skips
  downloading, and swap it before it is run or unpacked by root.
- **`nikos update` never downgrades.** A pin is the exact version for a new
  install and a minimum for an existing one: a newer tool, Python package or
  checkout is left alone and the run says so (`roles/pin-gate`).
- **Ollama is installed from its release archive** (with the ROCm runners on
  an AMD GPU) and `ollama.service` is written by NikOS, so existing installs
  restart Ollama once. On an NVIDIA GPU with no driver loaded, NikOS runs
  Ubuntu's `ubuntu-drivers install` (signed archive) in place of the driver
  install the script did; `nikos_nvidia_drivers: false` turns it off.
- **Netdata comes from Ubuntu's `netdata` package** instead of the kickstart
  script; the role configures nothing that needs the upstream build. A static
  kickstart install under `/opt/netdata` is left alone.
- **The `gh-copilot` extension is no longer installed.** gh 2.98+ from
  cli.github.com has `gh copilot` built in; the extension was an unchecked
  release binary. An older gh gets a one-line hint to upgrade.

### Fixed
- **The Ansible upgrade works on 22.04.** The PPA's ansible-core refused to
  unpack over the archive's ansible 2.10 (both ship `/usr/bin/ansible`);
  `install.sh` now removes the old package first.

- **Nothing installs from an unverified source any more.** Ollama, Bun, Helm,
  act, Starship, mkcert, llama.cpp, Miniforge, mistral.rs, the nvm script and
  Claude Code are pinned release files checked against a sha256 (the vendor's
  published sum where there is one). No `curl | sh`, no vendor install script
  run unchecked, no `releases/latest`, `@latest` or `state: latest`.
- **Vendor apt keys are fingerprint-checked before apt trusts them**: VS Code,
  GitHub CLI, Kubernetes, MongoDB, and the Ansible PPA in `install.sh`
  (`scripts/verify-key-fingerprint.sh`; a wrong or extra key stops the run).
- **Git checkouts are pinned to a release tag's commit** (image-view,
  git-lantern, ai-runner, distrodeck) or a commit (BitNet, which has no tags),
  not `main`. distrodeck checks the tag still points at its pinned commit.
- **npm, PyPI and pipx installs use exact versions** (Gemini CLI, OpenClaw,
  shell-gpt, glances, every package in the nikos-ai env), and the Qdrant image
  is pinned by tag and digest.
- **`nikos add mistral-rs` works.** It ran `cargo install mistralrs-server`,
  a crate crates.io does not have; it now installs the pinned CPU release
  (`mistralrs serve` is the server).

## [0.8.1] - 2026-10-02

### Fixed
- **NikOS no longer clones its tools into `~/Projects`.** distrodeck,
  image-view, git-lantern, ai-runner and bitnet.cpp now live in
  `~/.local/share/nikos-tools` (`nikos_tools_dir`). `~/Projects` is the user's
  workspace, often absent, and a developer's own clone of one of these repos
  there failed `nikos update` with "Local modifications exist in the
  destination". Existing `~/Projects` copies are left untouched; NikOS clones
  fresh into the new directory and its wrappers point there. With the
  `bitnet` bundle, the next update builds bitnet.cpp once more there (several
  minutes); the old `~/Projects/bitnet.cpp` tree can then be deleted.
- **Fabric is pinned** (`fabric_version`, v1.4.505) instead of installed from
  `@latest`. `go install` checks it against sum.golang.org, and a changed pin
  now reinstalls (the old `creates:` guard never upgraded).

## [0.8.0] - 2026-10-02

### Added
- **The first-run wizard supports GitLab, Bitbucket and custom Git servers, and
  can be skipped.** `nikos-git-setup` asks for the host first; Skip writes the
  flag so it never asks again. GitLab and Bitbucket keys are added over HTTPS
  with a token read by getpass and never stored. `nikos_git_setup: skip` in
  `vars/local.yml` installs no terminal hook. The old multi-line hook
  never matched itself, so each run appended another copy to `~/.bashrc` (25
  on one machine); every copy is removed and replaced by one managed block.

- **Jev client (`nikos add jev`, or Jev in the installer's AI Tools list, off by
  default).** Installs the official TypeSafe SDK, `typesafe-sdk` 0.7.2, in its own
  venv from a lock that pins it and every dependency by sha256
  (`pip --require-hashes`); its PyPI files are attested as published from
  `github.com/typesafe-ai/typesafe-sdk-python`. Adds a `jev` command
  (`jev login`, `jev choose`, `jev score`); the API key is yours, read with
  getpass and kept in `~/.config/typesafe/api_key` at mode 600.
- **Dark browsers in the desktop colour.** Firefox gets the built-in Dark theme
  and a `userChrome.css` that paints the whole window #2E3440; Chromium and
  Google Chrome get a dark theme seeded with the same colour. Off with
  `nikos_firefox_dark: false` / `nikos_chromium_dark: false`.
- **A digest at the end of every install and update log**: NikOS ref, OS,
  kernel, Ansible and Python versions, free disk, each failed task with its
  message, and each distinct warning and error with a count. A failed task
  also prints its file and line (`show_task_path_on_failure`).

### Fixed
- **Firefox no longer loses its uniform dark background after an update.** A
  third-party static theme colours only the surfaces that existed when it was
  made; the built-in Dark theme plus NikOS CSS covers the current ones.
- **GRUB gets a theme.** NikOS looked for one in the Nordic GTK repository,
  which has none, so every install printed "Nordic GRUB theme was not found"
  and kept the default menu. NikOS now ships its own (`roles/theming/files/grub`)
  and no longer clones that repository on every run.
- The Nordic GTK download is checked against a pinned sha256.
- No more "`~/.config/xfce4/panel` is not a directory" warning when the panel
  has never saved settings.
- The Plymouth note says the `default.plymouth` alternative is Ubuntu's normal
  way to set the theme (Ubuntu ships no `plymouth-set-default-theme`), instead
  of reading like a fallback.
- **The install and update gauge no longer drops to raw `TASK [...]` output
  without a word.** Passwordless sudo now goes straight to the gauge instead of
  falling to `--ask-become-pass` on an empty answer; the sudo password is
  checked with `sudo -S -k -v` (three tries); `--list-tasks` and the playbook
  get `/dev/null` as stdin, since ansible-core refuses a non-blocking tty. Any
  remaining fallback prints `Plain progress view: <reason>` to the terminal and
  the log, and `nikos update` offers to install a missing `dialog`.
- **The installer checks the sudo password before the playbook starts.** A
  wrong one used to fail the first become task minutes into the run; now it
  is asked again (three tries), and passwordless sudo is not asked at all.
- A distrodeck tool whose need is an opt-in tool (held out of `--all`: it runs
  an upstream installer or is a server, IDE or database) no longer pulls that
  tool in silently. The picker asks `Add <need>? [y/N]`; a no, or no terminal,
  drops the tool with a note.

## [0.7.0] — 2026-10-01

### Added
- **An IsoForge integration manifest, `isoforge.yml`.** It declares the Xubuntu
  24.04.4 base, the ISO metadata, and the Ansible provisioning an image build
  runs: `site.yml` against `inventory/local`, with `/etc/skel` as the home the
  playbook configures so a built image ships the setup to every new user.
- **Selectable tags on the three core roles.** `base`, `desktop` and `theming`
  now carry role tags, so an image build can ask for exactly the system core
  with `--tags base,desktop,theming`. An ordinary untagged run is unchanged:
  they are core roles, not optional bundles, and `nikos add` still refuses
  them by name.
- **A test that the documented tag list is the playbook's.** `docs/bundles.md`
  names `--list-tags` as the only complete view of the tags and then pastes its
  output; nothing had ever run the one against the other, and the pasted block
  had gone stale. `tests/test_bundles_doc.py` now compares them by name.
- **A server profile.** `nikos_profile` (`desktop` by default, set in
  `vars/local.yml`) decides whether the desktop layer runs. On `server`,
  `desktop`, `theming`, `editors`, `music` and `education` are skipped even when
  named in `--tags`. The installer asks for the profile in both selector paths,
  says whether a display manager was found, and persists the answer; `nikos
  update` does not ask again. On a server, `nikos add music`/`education` stop
  with an error rather than report success for a role that will not run.
  `editors` gains a role tag. `docs/profiles.md`
  assigns every role to a layer. `./test --profile=server` builds an Ubuntu
  Server 24.04 VM and checks that no desktop artefact is present.
- **Pick distrodeck tools by category.** The installer, `nikos setup` and the
  new `nikos add tools` offer distrodeck's own catalog (read at run time from
  `install-tools --list-catalog --format tsv`), save the choice with the other
  selections, and the `dev-tools` role installs exactly that list instead of
  `install-tools --all`. A distrodeck without the flag (0.10.3 and earlier)
  skips the screen with a note and installs its default set with `--all`
  as before.
- **A `mongodb` bundle.** MongoDB Community 8.2 from repo.mongodb.org (signed-by
  keyring), `mongosh`, the Atlas CLI and `pymongo`; `mongod` stays on
  `127.0.0.1:27017`. The Atlas local deployment is documented, not run.
- **Several Java releases.** `nikos_java_versions` (default `[21]`) installs
  `openjdk-N-jdk` for each entry and points `java`/`javac` at the first.
- **One configured owner of the Ollama port.** `nikos_ollama_host` (default
  `127.0.0.1:11434`, loopback only) is written to an `ollama.service` drop-in;
  `nikos_ollama_mode` (`local`/`remote`) and `nikos_node_role` are read by the
  play and the CLI. A port held by another process stops the run and names it.
  `nikos status` prints mode, endpoint and node role; `nikos doctor` sends a
  request to the endpoint, lists its models and fails when it does not answer.

- **Windows in the GRUB menu.** `nikos_grub_os_prober` (default true) installs
  `os-prober` and ships `/etc/default/grub.d/60-nikos-os-prober.cfg` on an
  installed GRUB system. `docs/dual-boot.md` covers boot order, UEFI vs legacy
  and Secure Boot/SBAT.

### Changed
- **Ollama model groups match distrodeck.** Default `qwen3.5:4b` (3.4 GB); reasoning
  `deepseek-r1:8b`, `qwen3:8b`, `gpt-oss:20b`; coding `qwen2.5-coder:7b`,
  `qwen3-coder:30b`; text `granite4:micro`, `qwen3.5:9b`, `gemma4:12b`; vision
  `qwen3-vl:4b`, `qwen3-vl:8b`; embedding `embeddinggemma:300m`,
  `qwen3-embedding:0.6b`. Every group in full is about 75 GB. Models already on
  disk are not removed.
- `base` no longer installs `inkscape` or `xfconf`; `theming` and `desktop`
  install what they use.
- `nikos doctor` exits 1 when it finds a problem, prints the profile, and skips
  the VS Code, Nordic and Papirus checks on a server.
- Vendored `script-helpers` moves from 0.24.0 to 0.44.1. NikOS uses only
  `logging` and `dialog` from it, and neither changed incompatibly.
- `community.general` moves from 9.5.2 to 10.7.9, the newest release that still
  supports the ansible-core 2.15 minimum `install.sh` enforces.
- distrodeck is cloned at a release tag rather than `main`.
  `distrodeck_version: latest` (the default) resolves the newest `X.Y.Z` tag at
  run time and `nikos update` moves the clone to it; any other value pins.
  Offline, or with local edits to tracked files, an existing clone is kept
  with a warning. Saved tool names the new release no longer lists are
  skipped with a warning instead of failing the run.
- The tool selection adds what a chosen tool needs (distrodeck's `needs`
  column when the catalog has one, otherwise `docker` for a container tool and
  `claude-code` for a plugin) unless it is already chosen or installed, and
  puts it ahead of the tool that needs it; distrodeck fails the whole
  `--tools` run without them.
- distrodeck's `ollama` and `mongodb` are hidden from the tool selection and
  dropped from saved lists with a warning: NikOS installs both itself
  (`nikos_distrodeck_owned_tools`).
- `nikos update` upgrades Ollama when GitHub has a newer release, by re-running
  the official installer, then restarts `ollama.service`; the NikOS drop-in is
  kept. Ollama is deliberately not pinned. The installer runs with
  `pipefail`, so a failed download fails the task instead of reporting an
  update and restarting the old engine.

### Fixed
- An image build no longer runs `update-grub`, installs the GRUB theme under
  `/usr/share/grub/themes` (the squashfs excludes `boot/grub`; installed systems
  with a separate `/boot` or an encrypted root also get a `/boot` copy that
  `GRUB_THEME` points at), and holds the
  kernel packages during the `base` upgrade so the squashfs kernel matches the
  live one. The holds are released before the play moves on.
- The Ollama tasks managed a user-scope unit that does not exist and waited on
  `/tmp/ollama.sock`, which Ollama never creates. Both failures were swallowed
  on every run, after a 30 second timeout. Readiness is now an HTTP request to
  `/api/version` that fails the run when Ollama does not answer.
- `nikos doctor` exited 127 at the first optional check that failed on any
  installed machine: it called `print_warn`, which script-helpers does not
  define.

## [0.6.5] — 2026-09-05

### Changed
- **`nikos update` now updates NikOS-managed dependencies, not only the NikOS
  checkout.** It refreshes the pinned `script-helpers` submodule; updates the
  `distrodeck`, `image-view`, `git-lantern`, and `ai-runner` source checkouts;
  rebuilds the two compiled CLIs after their source changes; refreshes the apt,
  snap, and flatpak packages the distrodeck tool set is installed from; and
  upgrades the Python and pipx applications NikOS manages. Existing APT, VS Code
  extension, and Ollama update paths continue to run, and saved optional-bundle
  selections still determine which optional dependencies are refreshed.
  `distrodeck install-tools` has no upgrade mode - it skips any tool already
  present - so tools installed with cargo, go, or npm are not refreshed.
- Added `./update` as the standard checkout-only command for synchronizing the
  `script-helpers` submodule to the revision pinned by the current NikOS
  release.

- Vendored `script-helpers` moves from 0.12.1 to 0.24.0. The Bash API is
  additive across that range — every function the old pin exposed is still
  there — and NikOS imports only `logging` and `dialog`, both unchanged. The
  breaking changes recorded in that range are all in the PowerShell modules,
  which nothing here loads.

### Fixed
- `nikos update` now hands the rest of the update to the CLI it has just checked
  out. `site.yml` installs the CLI by copying `scripts/nikos` to
  `/usr/local/bin/nikos`, so the running process is always the copy the
  *previous* release left there: its already-parsed `cmd_update` cannot run
  anything a newer release adds to the update flow - the optional-bundle replay,
  for one - until a second `nikos update`. A guarded re-exec of the checked-out
  CLI closes that gap from 0.6.5 onwards. The `nikos_update_mode` default in
  `vars/main.yml` remains the compatibility signal for the 0.6.4 CLI itself,
  which predates the re-exec.
- The `image-view` checkout no longer becomes un-updatable. Its `setup` runs a
  plain `cargo build --release`, which can rewrite the tracked `Cargo.lock`, and
  the build now runs on every update; `ansible.builtin.git` defaults to
  `force: false` and refuses a checkout with local modifications, so the next
  update would fail to update it. The generated lock is restored before the
  update. Any other local change still blocks it, which is deliberate.
- The git-lantern troubleshooting steps in `docs/debugging.md` no longer name the
  superseded global paths. They checked `/usr/local/bin/lantern` and reinstalled
  to `/opt/git-lantern` with sudo, which diagnosed a healthy per-user install as
  missing and recreated the global launcher the release removed.
- Every documented direct `ansible-playbook` invocation now passes
  `-e nikos_update_mode=false`. Because that variable defaults to `true` for the
  0.6.4 CLI's benefit, a hand-run install or `--check` inherited update mode and
  performed update-only work, including a full system package upgrade.

### Added
- Regression coverage for the persisted optional-bundle selection
  (`tests/test_update_selections.py`): rebuilding the selection on a 0.6.4
  install that saved skip tags only, that rebuild latching so it cannot re-derive
  later, the selection surviving `_save_skip_tags` and `_remove_skip_tag`, both
  playbook passes `nikos update` runs, and the release-upgrade continuation.


## [0.6.4] — 2026-09-02

### Fixed
- **Galaxy outages took CI red and could break an install.** Both `Lint` and
  `Dry-run Test` failed on `main` on a commit that touched nothing near them,
  for two unrelated Galaxy faults on the same afternoon: a `504 Gateway
  Timeout` fetching `community.general`, and a corrupted ansible-galaxy
  response cache (`Missing expected 'results' in ansible-galaxy cache ... Try
  running with --clear-response-cache or --no-cache`). Neither is a fault in
  this repository, and either would equally have failed somebody's install
  rather than only a CI run.
- Collection installs now go through `scripts/install-collections.sh`, which
  passes `--no-cache` — removing the cache-corruption class outright — and
  retries with a backoff, which covers the transient network faults. Every call
  site goes through it: `Lint`, `Dry-run Test`, `install.sh` and the `nikos`
  CLI's own setup and update paths, so the behaviour is the same whether a
  machine or a person is doing the installing. Both scripts fall back to
  calling `ansible-galaxy --no-cache` directly when the helper is absent, so an
  older checkout still works, and the helper fails immediately with a clear
  message when `ansible-galaxy` is not installed at all rather than retrying
  and blaming Galaxy. On final failure it exits with `ansible-galaxy`'s own
  status rather than a flat `1`, matching how `install.sh` reports the code it
  gets back, and `NIKOS_GALAXY_ATTEMPTS` and `NIKOS_GALAXY_RETRY_DELAY` are
  validated before use so a typo is reported as such instead of surfacing as an
  arithmetic error mid-loop. Every call site runs it through `bash` and gates on
  the file existing rather than on its executable bit, so a checkout on a
  `noexec` mount, or an archive that dropped permissions, does not silently
  fall back to the unprotected call.


## [0.6.3] — 2026-09-01

### Fixed
- **Stopped tracking `docs/CLAUDE.md`.** claude-mem writes an activity log into
  any directory it touches, and one had been committed. It is generated, would
  churn on every session, and publishes internal work history. Nested
  `CLAUDE.md` files are now ignored while a root one, which is deliberate
  project instruction, still is not.
- **GRUB theming failed where GRUB is not installed yet.** Four tasks edited
  `/etc/default/grub` unconditionally and the playbook stopped with
  `Path /etc/default/grub does not exist !`. An installer payload holds the
  system that gets copied to the target disk, and the bootloader is installed
  onto that disk afterwards, so the file is genuinely absent while the payload
  is being built. The tasks now check for it first and skip when it is missing,
  which is also the right behaviour on any machine that boots something other
  than GRUB.
- **nvm installed Node into `/usr/bin/versions/node` instead of `NVM_DIR`.**
  The task that installs the pinned Node sources `nvm.sh` and then calls the
  `nvm` shell function, and its comment says as much, but it never set
  `executable: /bin/bash`. `ansible.builtin.shell` runs `/bin/sh`, which is
  dash on Ubuntu, and `nvm.sh` works out its own directory from
  `${BASH_SOURCE[0]}`. Under dash that is unset, so nvm falls back to the
  directory of `$0` — `/bin` — and unpacks Node under `/usr/bin/versions/node`.
  It reports success while doing it, so nothing failed until the next task
  looked for npm where it should have gone and reported
  `No such file or directory: .../.nvm/versions/node/v22.23.2/bin/npm`.
  The `creates:` guard never matched either, so the task re-ran on every pass.
- **`NVM_DIR` is now set explicitly in both nvm tasks.** It was left to default
  to `$HOME/.nvm`, which only agrees with `nikos_home` when the playbook is
  provisioning the account it is running as. It does not agree when NikOS is
  applied to an image being built rather than a live desktop, and a stray
  `NVM_DIR` already in the environment would have overridden it in either case.


## [0.6.2] — 2026-08-27

### Fixed
- **The documented one-liner install silently dropped the bundles it was asked
  for** - `_select_bundles_plain` printed its section headers to stdout and
  returned the selection on that same stdout, and the caller captured the lot
  with `read -ra SELECTED_BUNDLES <<< "$(_select_bundles_plain)"`. A here-string
  is multi-line and `read` takes one line, so the array was filled with the
  words of a header: `bitnet` never matched the tag loop and the role never ran.
  `_select_ai_tools_plain` had the identical shape, so the same run also dropped
  every AI tool into `SKIP_TAGS`. Nothing failed - the install exited 0, printed
  a success summary, and `_logfile "Selected bundles: ..."` faithfully recorded
  the corrupted array, so the log agreed with the wrong outcome. Both functions
  now fill the caller's array directly; with no capture there is no channel for
  the prose and the answer to share. A run that cannot ask, because there is no
  controlling terminal, now says so and stops instead of installing nothing and
  calling it success. (#53)
- **The same install showed raw Ansible output instead of the TUI it is
  documented to show** - the installer held three different tests for "is there
  a terminal" and they disagreed. `_can_use_dialog` required `-t 0 && -t 1`, and
  under `curl ... | bash` bash reads the script itself from stdin, so that gate
  was false by construction on every machine; everything behind it was skipped,
  including the playbook. The two gates guarding the checklists tested nothing at
  all, which is why those still rendered - into a pipe. And
  `nikos_progress_supported` already tested the right thing, `/dev/tty`
  writability, but sat behind the wrong gate and was never reached. All three now
  ask one `_have_tty` helper, mirroring `_nikos_progress_tty`; `install.sh` is
  fetched standalone by curl and runs before the clone exists, so it keeps its
  own copy rather than sourcing it. Dialogs that take keystrokes now read
  `0</dev/tty` explicitly, and the UI decision and its three inputs are written
  to the install log. (#52)
- **`nikos setup` and `nikos update` never had the gauge at all** -
  `scripts/nikos` ran `ansible-playbook ... | tee` and did not source
  `scripts/nikos-progress.sh`, so post-install runs showed raw `TASK [...]`
  output on any terminal. Same symptom as the install defect, a different cause.
  Both now run through `nikos_progress_run` when the gauge can be drawn.
  `--ask-become-pass` could not survive that move - Ansible's prompt reads
  `/dev/tty`, which the gauge is drawing on - so the password is collected first
  and passed in a mode-600 file, as `install.sh` does. The plain branches gained
  the `ANSIBLE_NOCOLOR` / `ANSIBLE_FORCE_COLOR` settings the dialog paths always
  set.
- **Cancelling a dialog was reported as success** - `_collect_become_password_dialog`
  and both timezone dialogs used `if ! var=$(dialog ...); then return $?; fi`.
  In the then-branch `$?` is the status of the `!` itself, which is 0, so Cancel
  and Esc returned success and the caller took the empty output for an answer:
  an empty sudo password handed to ansible, or an empty timezone written to
  `vars/local.yml`. The status is now captured from the assignment, the shape
  `_select_bundles_dialog` already used.
- **Input ending mid-prompt was treated as an answer** - a failed `read` became
  an empty string, which silently declines the bundle being asked about and
  accepts any default-enabled AI tool. That is the behaviour the plain path was
  changed to stop, reintroduced one level down. Input that ends with nothing
  captured now stops the installer; a partial line before EOF is still an answer.
  The message names what that leaves behind - the bootstrap packages, the
  checkout and the collections are already installed by then - rather than
  claiming nothing was.
- **The timezone prompt had the same defect, and `NIKOS_USE_DIALOG=0` wrote a
  menu into `vars/local.yml`** - `_select_timezone_plain` printed its menu and
  its answer to stdout, and the caller captured both with
  `_chosen_tz=$(_select_timezone_plain ...)`. Measured on the unfixed version,
  the captured value was five lines long: the heading, the option list and the
  timezone. Prose now goes to `/dev/tty` and the answer is assigned, as the
  bundle selectors do, and `tests/test_install_tui_gate.py` round-trips the auto,
  defaulted and custom answers.
- **`nikos update` drew a progress bar that did not report progress** -
  `nikos_progress_run` renders against the role list and task total that
  `nikos_progress_plan` produces, and that planner was never called, so
  `NIKOS_PROGRESS_TOTAL` stayed zero and the gauge sat at 0% until `PLAY RECAP`
  jumped it to 100. The playbook is now planned first, exactly as `install.sh`
  does, and a task list that cannot be produced drops the run to the plain view
  instead of drawing an empty gauge.
- **The sudo password file could be published without its permissions being
  confirmed** - `_collect_become_password` ignored the status of `chmod 600` and
  went on to write the password and report success. The caller reads a non-zero
  return as "fall back to `--ask-become-pass`" and calls it inside an `&&`
  condition, where bash suspends errexit for the whole list, so an unchecked
  failure there neither aborted nor returned - it carried on. Every step is now
  checked on its own, and the path is registered in `BECOME_PASSWORD_FILE` the
  moment the file exists, because the INT/TERM trap can only remove what that
  global names: holding it back until the password had been written would leave
  a window where Ctrl-C stranded a mode-600 file containing the sudo password on
  disk. Every failure after that point cleans up explicitly, so a failed
  collection still leaves nothing behind and still returns non-zero.
  The traps restore the terminal cursor as well, which `dialog` hides while the
  gauge draws - interrupting `nikos update` used to hand back a terminal with no
  visible cursor. `tests/test_become_password_file.py` covers the mode of the
  written file, a failing `chmod`, a temp file that cannot be created, that
  ordering, and the cursor after an interrupt.
- **Neither defect was catchable by the existing suites** - `tests/` had no
  coverage of the gate or the selection, and `./test` structurally cannot provide
  it: it drives the installer over `ssh -tt`, so a pty is always allocated and
  only the clone-and-run path is exercised.
  `tests/test_install_tui_gate.py` covers the gate on piped stdin with a real
  terminal, with no controlling terminal, with `NIKOS_USE_DIALOG=0` and with
  `dialog` absent, and round-trips a selection through the real dispatch. The
  harness is the load-bearing part: `script -qec 'bash prog'` gives the child a
  pty on all three descriptors, so the unfixed gate passes there; the pipe has to
  be on bash's own stdin, as `script -qec 'cat prog | bash'` arranges. Verified
  by re-introducing each defect.

## [0.6.1] — 2026-08-21

### Fixed
- **The BitNet install task failed every run, and took the whole optional
  playbook down with it** - `ansible.builtin.shell` runs its script with
  `/bin/sh`, which is dash on Debian and Ubuntu, and dash has no `pipefail`.
  The task died on its first line with `/bin/sh: 1: set: Illegal option -o
  pipefail`, before the copy it existed to perform, so the run ended `rc=2`
  with the CLI never installed. The task now declares
  `args: executable: /bin/bash`. It surfaced only now because the earlier
  configure and build steps had to start producing `llama-cli` before this one
  could run at all.
- **Tests now cover the whole class** - `tests/test_shell_task_interpreters.py`
  walks every playbook, in both YAML extensions and both task call forms, and
  fails any `shell` task written with bash-only syntax (`pipefail`, `[[`,
  process substitution, associative arrays) that is left on the default
  interpreter. Nothing about the failure was specific to BitNet, and it is
  invisible until the task runs. Verified by removing the fix above, which
  fails the suite.
- **Tagged releases were never published, so the repository advertised 0.4.2 as
  the latest** - `release.yml` triggers on a tag push, but the tag is created by
  the Auto Tag Release workflow, which pushes it with `GITHUB_TOKEN`. GitHub
  does not run workflows for pushes made with that token, so the trigger never
  fired: 0.5.0 and 0.6.0 were tagged with no GitHub Release behind them.
  ci-helpers documents the restriction in `auto-tag-release.yml`. The release is
  now built in the same run as the tag, by calling `release-build.yml` with the
  version the tag job reports, which keeps `install.sh` attached and needs no
  `actions: write`.
- **The manual tag path could not have worked either** - `release.yml` declared
  no permissions, so the reusable workflow it calls had no `contents: write` to
  create a release with. It now declares them, and takes a `workflow_dispatch`
  input so a release can be published for a tag that already exists.

## [0.6.0] — 2026-08-21

### Fixed
- **The menu editor entry pointed at software that was never installed** - both
  the Xubuntu whiskermenu defaults and the NikOS ones set
  `command-menueditor=menulibre` with the button shown, and menulibre is a
  Recommends of the full `xubuntu-desktop` only. On `xubuntu-desktop-minimal` it
  is absent, so the entry failed the same way "Edit Profile" did. menulibre is
  now installed with the other desktop packages. Found by auditing every menu
  command after the mugshot report, rather than by another click.
- **A menu favourite silently never appeared** - the favourites list named
  `xfce4-settings-manager.desktop`, but the file `xfce4-settings` ships is
  `xfce-settings-manager.desktop`, with no `4` after `xfce`. The binary *is*
  `xfce4-settings-manager`, which is what makes the wrong id easy to write and
  hard to notice: nothing errors, the favourite is just missing.
- **Tests now cover the whole class** - `tests/test_desktop_menu.py` checks that
  every displayed menu command has something installing its binary, that no
  shown button lacks a command, and that favourites are well-formed desktop ids.
  Verified against both defects above: removing menulibre from the package list
  or restoring the wrong desktop id fails the suite.
- **The install summary printed broken numbers and hid a real failure** - an
  install runs the playbook twice, once for the main run and once for the
  optional bundles, and each prints its own `PLAY RECAP`. The summary read them
  with a bare `grep`, which returns one line per recap, so `ok` became `177` and
  `10` on separate lines and the dialog box wrapped the remainder onto its own
  row. The same values fed `[[ "${failed}" -gt 0 ]]`, and bash raises a syntax
  error on a multi-line operand and evaluates it false, so a bundle that failed
  was reported as a clean install. The counts are now totalled across every
  recap, so they stay integers however many times the playbook ran.
- **`bitnet-cli` resolved its libraries through the build tree it was compiled
  in** - the CLI was installed by copying `llama-cli` into `~/.local/bin`, but
  that binary links against shared libraries produced by BitNet's build and
  carries a `RUNPATH` with that directory's absolute path baked in. `ldd` on the
  installed file pointed back into `Projects/bitnet.cpp/build/bin`, so the
  command worked only while the build tree stayed where it was built, under the
  home it was built with; a machine with more than one `Projects` tree resolved
  the wrong one. The binary and every `*.so*` beside it are now copied into
  `/usr/local/lib/nikos/bitnet`, with `/usr/local/bin/bitnet-cli` as the entry
  point, so the command is self-contained and the build tree is only needed to
  rebuild. Every library travels rather than just the ones `ldd` reports,
  because ggml loads its backends with `dlopen` and a dependency-only copy
  passes `ldd` and then fails when a backend is loaded. `cp -a` preserves the
  symlink chains, which a copy loop would dereference and triple in size. The
  earlier per-user `~/.local/bin/bitnet-cli` is removed, since that directory
  precedes `/usr/local/bin` on a default `PATH` and would otherwise keep
  shadowing the new entry point.
- **BitNet.cpp built no CLI, and the install step failed on the missing file** -
  the role built only shared libraries, then failed with `Source
  .../build/bin/llama-cli not found`. BitNet adds llama.cpp with
  `add_subdirectory`, which leaves `LLAMA_STANDALONE` off, and llama.cpp
  defaults `LLAMA_BUILD_COMMON` and `LLAMA_BUILD_TOOLS` to that value while
  guarding `add_subdirectory(tools)` on both. The configure step now sets them
  explicitly, and re-runs on an existing build tree rather than being skipped by
  a `creates:` guard, so a machine that already has the old cache is repaired
  instead of failing forever.
- **The menu's "Help" entry opened a file that was never installed** - Xubuntu's
  `xfhelp4.desktop` runs `exo-open` on `/usr/share/xubuntu-docs/index.html`, which
  comes from the `xubuntu-docs` package. The full `xubuntu-desktop` metapackage
  Recommends it; NikOS installs `xubuntu-desktop-minimal`, which does not, so Help
  opened a dead `file://` URL. Rather than pull in 78 MB of documentation that is
  still at version 22.04, Help now opens the NikOS help page, which links out to the
  current Xubuntu and Xfce documentation and says how to install the offline
  handbook. The override is installed to `/usr/share/xfce4/applications`, which
  `XDG_DATA_DIRS` resolves ahead of `/usr/share/xubuntu`, so nothing belonging to
  `xubuntu-default-settings` is modified.
- **Whisker Menu's "Edit Profile" failed with "Failed to execute child process
  `mugshot`"** - the menu shows that button by default and runs `mugshot` for
  it, but the plugin only *Suggests* mugshot, and Suggests are never installed.
  A stock Xubuntu has it because the full `xubuntu-desktop` metapackage
  Recommends it; NikOS installs `xubuntu-desktop-minimal`, which does not, so
  the button pointed at a binary that was never there. mugshot is now installed
  with the other desktop packages, and the post-install checklist probes for it.
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

### Documentation
- **The `bitnet` bundle never named the command it installs** - `bitnet-cli` was
  not mentioned in the README, the customization guide or the site, so the only
  way to discover it was to read the role. All three now name it, and
  `docs/debugging.md` gains an entry covering where it is installed, the copy an
  older NikOS may have left in `~/.local/bin` shadowing it, and why a build
  configured by an older NikOS produced no CLI.
- **Nothing explained the install summary** - `docs/debugging.md` now describes
  it, including why `ok=` does not match any single `PLAY RECAP` in the log: an
  install runs the playbook twice and the counts are totalled. It also records
  how a failed optional bundle could be reported as a clean install before
  0.6.0, and how to check the log on an older version.

### Licensing
- **The Plymouth boot splash is GPL-3.0-or-later, not MIT** - `nikos.script`
  was written by working from Xubuntu's `xubuntu-logo.script` and kept part of
  its implementation: `strlen()` is identical, `atoi()` differs only by a
  variable rename, and the status parsing loop is line-for-line identical apart
  from two more renames. That file is GPL-3-or-later, copyright The Xubuntu
  Community and Canonical, and those terms do not permit MIT redistribution.
  The upstream copyright and GPL notice are restored on the file, a full copy
  of the licence is included at `LICENSES/GPL-3.0-or-later.txt`, and the
  exception is recorded in `THIRD-PARTY-NOTICES.md`. Everything else in NikOS
  stays MIT.

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
