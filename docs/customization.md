# Customization

All user-facing knobs live in `vars/main.yml`. Edit before running the playbook, or fork the repo and change defaults.

## vars/main.yml reference

```yaml
# ── Version ──────────────────────────────────────────
nikos_version: "0.1.0"

# ── System ───────────────────────────────────────────
nikos_timezone: "Europe/Belgrade"   # any tz from timedatectl list-timezones
nikos_locale: "en_US.UTF-8"

# ── Theme ─────────────────────────────────────────────
nordic_gtk_url: "https://github.com/EliverLara/Nordic/releases/..."

# ── Ollama ────────────────────────────────────────────
ollama_default_model: "qwen2.5-coder:7b"
# Other good choices: llama3.2, mistral, codellama, phi3

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

## Changing the Ollama model

Edit `vars/main.yml`:

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

Add extension IDs (from the VS Code Marketplace URL) to `nikos_vscode_extensions` in `vars/main.yml`, then run `nikos update`.

## Adding optional bundles

```bash
nikos add network    # nmap, wireshark, OpenVPN, traceroute, tcpdump
nikos add music      # LMMS, Ardour (Flatpak), Audacity
nikos add education  # LibreOffice, draw.io (Flatpak), Anki
```

## Changing the wallpaper

The wallpaper is `assets/wallpaper.svg` — a vector file exported to PNG on install. Edit the SVG directly and run `nikos update` to re-export and apply.

## Changing the timezone

```yaml
nikos_timezone: "America/New_York"
```

Run `nikos update` to apply.

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

Or change the `REPO_URL` in `install.sh` and `scripts/nikos` to point to your fork.
