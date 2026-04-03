# Debugging

## nikos doctor

Run this first for any issue:

```bash
nikos doctor
```

It checks:
- ansible, gh, Ollama, VS Code, distrodeck, conda, Claude Code, Gemini CLI
- Nordic GTK theme files
- Papirus icon files
- GitHub wizard completion flag

Any `[!!]` items indicate missing or broken components. Run `nikos update` to attempt repair.

## Common issues

### Xfce doesn't start after install

LightDM may not be set as the default display manager.

```bash
sudo systemctl status lightdm
sudo systemctl enable --now lightdm
cat /etc/X11/default-display-manager   # should contain /usr/sbin/lightdm
```

### Nordic theme not applied

```bash
ls /usr/share/themes/Nordic          # should exist
ls /usr/share/icons/Papirus-Dark     # should exist
```

If missing, re-run theming:

```bash
ansible-playbook ~/nikos/site.yml -i ~/nikos/inventory/local --tags theming
```

### Ollama model not found

```bash
ollama list
ollama pull qwen2.5-coder:7b
```

Check the service:
```bash
systemctl --user status ollama
systemctl --user restart ollama
```

### GitHub wizard re-run

```bash
rm ~/.config/nikos/github-configured
# Open a new terminal — the wizard will run automatically
```

### VS Code extensions not installed

```bash
code --list-extensions
code --install-extension Continue.continue --force
```

### conda / nikos-ai env missing

```bash
~/miniforge3/bin/conda env list
~/miniforge3/bin/conda create -n nikos-ai python=3.11 -y
~/miniforge3/bin/conda run -n nikos-ai pip install torch transformers jupyter
```

### image-view not found

`image-view` installs to `~/.local/bin/`. Ensure that's in your PATH:

```bash
echo $PATH | grep -q ".local/bin" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
image-view --help
```

### git-lantern / lantern not found

```bash
which lantern
ls /usr/local/bin/lantern
# Reinstall if missing:
sudo ~/Projects/git-lantern/install --prefix /opt/git-lantern --bin-link /usr/local/bin/lantern
```

## Ansible logs

Run the playbook directly with verbose output:

```bash
ansible-playbook ~/nikos/site.yml -i ~/nikos/inventory/local -v
```

Use `-vvv` for full debug output including module arguments.

## Check mode (dry-run)

Preview what would change without applying:

```bash
ansible-playbook ~/nikos/site.yml -i ~/nikos/inventory/local --check
```

## Re-running a single role

```bash
ansible-playbook ~/nikos/site.yml -i ~/nikos/inventory/local --tags theming
ansible-playbook ~/nikos/site.yml -i ~/nikos/inventory/local --tags ai-stack
```

Note: role tags must be explicitly set in `site.yml`. The optional roles (`network`, `music`, `education`) are tag-gated by default.
