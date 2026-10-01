# Profiles and layers

A single laptop with a screen is still the default and the complete NikOS
install. Nothing below has to be chosen to get it: pressing Enter at the
installer's profile prompt gives a desktop install, the same as before
profiles existed.

Every install declares one profile:

| Profile | For | Gets |
|---|---|---|
| `desktop` (default) | a workstation or laptop | core + desktop layer |
| `server` | Ubuntu Server 24.04, a headless box, a lab node | core only |

The installer asks once and writes the answer to `vars/local.yml`:

```yaml
nikos_profile: "server"
```

`nikos update`, `nikos setup` and `nikos add` read it from there and do not ask
again. Any value other than `desktop` or `server` stops the run with a message
naming `vars/local.yml`. To change profile later, edit that line and run
`nikos update`. Switching a desktop to `server` stops managing the desktop
roles; it does not uninstall what they already installed.

## Layers

Every role in `site.yml`, assigned to a layer:

| Layer | Roles | Runs on |
|---|---|---|
| core | `base`, `github-setup`, `ai-stack`, `cloud-ai-cli`, `agent-dev`, `dev-tools`, `network` | both profiles |
| desktop | `desktop`, `theming`, `editors`, `music`, `education` | `desktop` only |
| optional (named to run) | `neovim`, `java`, `podman`, `openclaw`, `bun`, `redis`, `postgres`, `mongodb`, `zsh`, `act`, `fabric`, `k8s-tools`, `qdrant`, `bitnet`, `mistral-rs`, `monitoring` | both profiles, when asked for |

The desktop-layer roles carry `when: nikos_profile == 'desktop'` in `site.yml`,
so a server run skips them even when they are named in `--tags`. On a desktop
they can also be left out for one run with
`--skip-tags desktop,theming,editors`.

On a server, `nikos add music` and `nikos add education` stop with an error
instead of reporting success for a role that would not run, and the installer
says when a desktop bundle was selected but will be skipped.

`base` holds only what makes sense with no screen. `inkscape` (wallpaper
export) lives in `theming` and `xfconf` (Xfce settings) in `desktop`.

## Optional roles that suit a services machine

`postgres`, `mongodb`, `redis`, `qdrant`, `podman`, `k8s-tools`, `monitoring`
and `mistral-rs` need no display. `neovim` and `zsh` are the editor and shell
for a machine reached over SSH.

## What a server install leaves out

No display manager, no Xfce or Xubuntu packages, no wallpaper, no Plymouth
theme, no GUI VS Code. It keeps the `nikos` command, the AI stack (Ollama on
`127.0.0.1:11434`), containers, the database bundles and SSH.

`nikos doctor` prints the profile it checks against, and on a server it skips
the VS Code, Nordic and Papirus checks instead of failing them.

## Inference endpoint

One process per machine owns the Ollama port. Set alongside the profile:

```yaml
nikos_ollama_mode: "local"            # local | remote
nikos_ollama_host: "127.0.0.1:11434"  # loopback only; Ollama has no auth
nikos_ollama_remote_url: ""           # required when the mode is remote
nikos_node_role: "workstation"        # workstation | inference | services
```

`local` writes `OLLAMA_HOST` into `/etc/systemd/system/ollama.service.d/nikos.conf`
and refuses to start when another process already holds the port. `remote`
installs no local Ollama. `nikos status` prints the mode, endpoint and node
role; `nikos doctor` sends a request to the endpoint and fails if it does not
answer.

## Verifying a profile in a VM

```bash
./test -b                     # Xubuntu 24.04, desktop profile
./test -b --profile=server    # Ubuntu Server 24.04, server profile
```

The server run uses its own VM (`NikOS-test-server`) and checklist, which
asserts the desktop artefacts are absent rather than only that the server ones
are present.
