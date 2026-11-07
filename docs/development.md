# Development Guide

## Repository structure

```
nikos/
├── install.sh                      # bootstrap: installs Ansible, clones repo, runs ansible-playbook
├── site.yml                        # top-level playbook — ordered roles
├── ansible.cfg                     # roles path, become method; applies when run from the repo root
├── plugins/become/nikos_sudo.py    # builtin sudo become plugin plus the sudo-rs password prompt
├── vars/main.yml                   # tracked defaults
├── vars/versions.yml               # every pinned external version, sha256, commit, key fingerprint
├── vars/local.yml                  # untracked local overrides (optional)
├── inventory/local                 # localhost ansible_connection=local
├── assets/wallpaper.svg            # Nord-palette wallpaper (exported to PNG on install)
├── scripts/nikos                   # nikos CLI (installed to /usr/local/bin/nikos)
├── scripts/nikos-progress.sh       # dialog mixedgauge rendering for playbook runs
├── roles/
│   ├── base/                       # apt, locale, timezone, flatpak
│   ├── desktop/                    # Xubuntu desktop, LightDM, display manager handover
│   ├── theming/                    # Nordic GTK, icons, GRUB, LightDM greeter, wallpaper
│   ├── github-setup/               # gh CLI, first-login wizard
│   ├── ai-stack/                   # Ollama, Miniforge, conda env, aider
│   ├── editors/                    # VS Code + extensions + settings
│   ├── cloud-ai-cli/               # Node.js, Gemini CLI, shell-gpt, glances
│   ├── agent-dev/                  # LangChain, LlamaIndex, Claude Code
│   ├── dev-tools/                  # distrodeck, image-view, vellum, git-lantern, ai-runner
│   └── optional/
│       ├── network/                # nmap, wireshark, OpenVPN
│       ├── music/                  # LMMS, Ardour, Audacity
│       ├── education/              # LibreOffice, draw.io, Anki
│       ├── neovim/                 # Neovim + starter lazy.nvim config
│       ├── java/                   # OpenJDK (nikos_java_versions, default 21)
│       ├── podman/                 # Podman container runtime
│       ├── bun/                    # Bun JavaScript runtime
│       ├── redis/                  # Redis server
│       ├── postgres/               # PostgreSQL + pgvector
│       ├── mongodb/                # MongoDB, mongosh, Atlas CLI
│       ├── qdrant/                 # Qdrant vector database
│       ├── zsh/                    # Zsh + Starship
│       ├── act/                    # Local GitHub Actions runner
│       ├── fabric/                 # Fabric AI pattern CLI
│       ├── k8s-tools/              # kubectl + Helm
│       ├── bitnet/                 # BitNet.cpp
│       ├── mistral-rs/             # mistral.rs server
│       ├── monitoring/             # Netdata
│       └── openclaw/               # OpenClaw CLI
├── tests/
│   └── test_github_wizard.py       # pytest tests for the first-login wizard
└── .github/workflows/
    ├── lint.yml                    # ansible-lint + shellcheck + pytest on every PR
    ├── test.yml                    # --check dry-run on Ubuntu 22.04, 24.04, 26.04
    └── release.yml                 # GitHub Release on tag push (X.Y.Z)
```

## Running tests locally

```bash
# Lint
ansible-lint site.yml
shellcheck install.sh scripts/nikos test

# Unit tests
python3 -m pytest tests/ -v

# Dry-run (needs ansible installed)
ansible-playbook site.yml -i inventory/local --check --skip-tags network,music,education -e nikos_update_mode=false
```

## Validating in a VM

`./test` installs NikOS in a VirtualBox guest and runs `nikos doctor` plus a
checklist there (`-b` creates the guest and installs the OS first). The
release and the guest's resources come from the environment:

| Variable | Default | Meaning |
|---|---|---|
| `NIKOS_TEST_RELEASE` | `24.04` | `24.04` or `26.04`; anything else is refused |
| `NIKOS_TEST_VM` | `NikOS-test`, `NikOS-test-server`; on 26.04 with `-26.04` appended | VM name (`--vm-name=` does the same) |
| `NIKOS_TEST_VM_RAM` | 4096 on 24.04, 6144 on 26.04 | guest RAM in MB |
| `NIKOS_TEST_VM_CPUS` | 2 | guest CPUs |
| `NIKOS_TEST_VM_DISK` | 40960 | guest disk in MB |
| `NIKOS_TEST_ISO` | `~/Downloads/<release ISO>` | ISO for the chosen profile |
| `NIKOS_TEST_ISO_URL` | the Ubuntu mirror for that ISO | downloaded to the ISO path when the file is missing or below the size floor set per release and profile in `test`; with `NIKOS_TEST_ISO` and no URL the file must exist and is used as is |

The RAM, CPU and disk variables apply only with `-b`, and setting one without it
is refused: an existing guest keeps its resources. `--show-config` prints what
`-b` would use. Each of the three must be a positive whole number. A run stops
before the installer if the guest's `VERSION_ID` differs from
`NIKOS_TEST_RELEASE`, and exits 1 if a checklist item fails.

The ISOs are point releases, named in `test`: `xubuntu-24.04.4-desktop-amd64.iso`
and `ubuntu-24.04.5-live-server-amd64.iso` for 24.04,
`xubuntu-26.04.1-desktop-amd64.iso` and `ubuntu-26.04.1-live-server-amd64.iso`
for 26.04.

```bash
./test --show-config                            # what a run would use; nothing starts
NIKOS_TEST_RELEASE=26.04 ./test --show-config
./test -b                                       # Xubuntu 24.04, desktop profile
NIKOS_TEST_RELEASE=26.04 ./test -b              # Xubuntu 26.04, desktop profile
NIKOS_TEST_RELEASE=26.04 NIKOS_TEST_VM_RAM=8192 ./test -b --profile=server
```

`tests/test_harness_config.py` checks the resolved settings through
`--show-config`, and `tests/test_harness_run.py` drives the harness against stub
`VBoxManage` and `ssh` commands. What the guest does after that (the unattended install, the
desktop, the checklist) is only known from a real run.

## Pinned versions

Every external download is pinned in `vars/versions.yml`, with a one-line
source comment and an entry in `nikos_pin_sources` that `scripts/bump-versions.py`
reads. `tests/test_pinned_sources.py` fails on `curl | sh`, `releases/latest`,
`@latest`, a branch checkout, a `get_url` without a sha256, or an apt key that
is not fingerprint-checked. Roles install a pin when the tool is missing or
older (`roles/pin-gate`): for an existing install the pin is a minimum.

```bash
export GITHUB_TOKEN=$(gh auth token)         # optional, lifts the GitHub API limit
python3 scripts/bump-versions.py             # --check: current, newest eligible, status
python3 scripts/bump-versions.py --bump      # every pin: new version + sha256, cross-checked, then tests
python3 scripts/bump-versions.py --bump act  # one pin
python3 scripts/bump-versions.py --verify    # re-download every pin and compare (slow: ~3 GB)
```

Eligible means not a draft or pre-release and at least `--min-age-days` (3)
old. `--bump` never changes an apt key fingerprint or a pin whose artifact has
no vendor checksum (mkcert, agentvault, Nordic, the nvm script): it says what is newer, and
a person updates those by hand and proves them with `--verify`.

The Python packages share one env, so `--bump` moves them as a set (needs
[uv](https://docs.astral.sh/uv/)): every package goes to its newest release
that installs on each Python in `python:` of the `nikos_pip_pins` source, and
the set must still resolve with `uv pip compile` on each of them. A package
whose newest release breaks the set is held back and named in the output.
`--bump nikos_pip_pins.<package>` moves one without that check.

## Writing a new role

1. Create the role directory:

```bash
mkdir -p roles/my-feature/tasks
```

2. Write `roles/my-feature/tasks/main.yml` — use FQCN throughout:

```yaml
---
- name: Install my package
  ansible.builtin.apt:
    name: my-package
    state: present
  become: true
```

3. Add it to `site.yml`:

```yaml
roles:
  - role: my-feature
    become: false   # if user-context tasks only
```

4. Lint before committing:

```bash
ansible-lint roles/my-feature/
```

## Ansible conventions

- **FQCN always**: `ansible.builtin.apt`, not `apt`
- **Registered vars**: prefix with role name — `base_flathub_result`, not `result`
- **Handlers**: start uppercase — `Theming_update_grub`
- **User home**: use `{{ nikos_home }}` (defined in `site.yml` via `lookup('env', 'HOME')`)
- **Root-needing tasks**: explicit `become: true` per task, not assumed from play level
- **Check mode**: add `when: not ansible_check_mode` to tasks that depend on files created by earlier tasks (unarchive, symlinks, cargo builds)

## Branching strategy

```
main      — stable, always installable, tagged releases
dev       — integration branch, PRs target here
feature/* — individual role or feature work
```

PRs go to `dev`. `dev` merges to `main` when stable. Tag `main` to release.

## Releasing

```bash
# Create release/X.Y.Z, bump VERSION, update changelog/docs, then merge to main.
# The ci-helpers @production release tag gate blocks duplicate release tags on PRs to main.
# The ci-helpers @production auto-tag workflow tags main when a release/X.Y.Z PR is merged.
```

The `release.yml` workflow creates a GitHub Release automatically with a changelog and `install.sh` as a release asset.

## Versioning

Strict semver `X.Y.Z` with no `v` prefix. Keep `VERSION`, README, and CHANGELOG in sync.

## CI overview

| Workflow | Trigger | Checks |
|---|---|---|
| `lint.yml` | Every PR + push to main/dev | ansible-lint, shellcheck, pytest |
| `test.yml` | Every PR + push to main | ansible-playbook --check on Ubuntu 22.04, 24.04 and 26.04 runners |
| `release-tag-gate.yml` | Every PR | Blocks duplicate release tags for release PRs to main |
| `release.yml` | Tag push (`X.Y.Z`) | Creates GitHub Release with changelog |
