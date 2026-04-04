# Development Guide

## Repository structure

```
nikos/
├── install.sh                      # bootstrap: installs Ansible, clones repo, runs ansible-playbook
├── site.yml                        # top-level playbook — ordered roles
├── vars/main.yml                   # tracked defaults
├── vars/local.yml                  # untracked local overrides (optional)
├── inventory/local                 # localhost ansible_connection=local
├── assets/wallpaper.svg            # Nord-palette wallpaper (exported to PNG on install)
├── scripts/nikos                   # nikos CLI (installed to /usr/local/bin/nikos)
├── roles/
│   ├── base/                       # apt, locale, timezone, flatpak
│   ├── desktop/                    # Xfce 4, LightDM
│   ├── theming/                    # Nordic GTK, icons, GRUB, LightDM greeter, wallpaper
│   ├── github-setup/               # gh CLI, first-login wizard
│   ├── ai-stack/                   # Ollama, Miniforge, conda env, aider
│   ├── editors/                    # VS Code + extensions + settings
│   ├── cloud-ai-cli/               # Node.js, Gemini CLI, Copilot extension
│   ├── agent-dev/                  # LangChain, LlamaIndex, Claude Code
│   ├── dev-tools/                  # distrodeck, image-view, git-lantern, ai-runner
│   └── optional/
│       ├── network/                # nmap, wireshark, OpenVPN
│       ├── music/                  # LMMS, Ardour, Audacity
│       └── education/              # LibreOffice, draw.io, Anki
├── tests/
│   └── test_github_wizard.py       # pytest tests for the first-login wizard
└── .github/workflows/
    ├── lint.yml                    # ansible-lint + shellcheck + pytest on every PR
    ├── test.yml                    # --check dry-run on Ubuntu 24.04 Docker
    └── release.yml                 # GitHub Release on tag push (X.Y.Z)
```

## Running tests locally

```bash
# Lint
ansible-lint site.yml
shellcheck install.sh scripts/nikos

# Unit tests
python3 -m pytest tests/ -v

# Dry-run (needs ansible installed)
ansible-playbook site.yml -i inventory/local --check --skip-tags network,music,education
```

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
# Bump version in vars/main.yml, install.sh, and scripts/nikos
# Commit: "chore: bump version to X.Y.Z"
git tag X.Y.Z
git push origin main --tags
```

The `release.yml` workflow creates a GitHub Release automatically with a changelog and `install.sh` as a release asset.

## Versioning

Strict semver `X.Y.Z` — no `v` prefix. Keep the shipped version in sync across `vars/main.yml`,
`install.sh`, and `scripts/nikos`.

## CI overview

| Workflow | Trigger | Checks |
|---|---|---|
| `lint.yml` | Every PR + push to main/dev | ansible-lint, shellcheck, pytest |
| `test.yml` | Every PR + push to main | ansible-playbook --check on Ubuntu 24.04 |
| `release.yml` | Tag push (`X.Y.Z`) | Creates GitHub Release with changelog |
