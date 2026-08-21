# Debugging

## nikos doctor

Run this first for any issue:

```bash
nikos doctor
```

It checks:
- ansible, dialog, gh, tmux, Ollama, VS Code, distrodeck, conda, Claude Code, Gemini CLI
- llama.cpp, shell-gpt, glances, and mkcert when present
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

If the playbook reports that Cargo is too old for `image-view`, update Rust via
distrodeck and rerun `nikos update`. The package dependencies require Cargo 1.85+
for Rust 2024 edition support.

### NikOS boot splash logo missing

The Plymouth logo is embedded into initramfs. If the install was interrupted or a
later task failed before handlers ran, rerun:

```bash
nikos update
sudo plymouth-set-default-theme nikos
sudo update-initramfs -u -k all
```

Then reboot and check the early boot splash again.

### Still booting into GNOME after installing on Ubuntu

The switch only takes effect after a reboot. If a reboot did not help, check
which unit owns the display manager alias:

```bash
readlink -f /etc/systemd/system/display-manager.service
```

It must resolve to `lightdm.service`. If it still points at `gdm3.service`:

```bash
sudo systemctl disable gdm3
sudo ln -sf /usr/lib/systemd/system/lightdm.service \
  /etc/systemd/system/display-manager.service
sudo systemctl daemon-reload
```

If the greeter is LightDM but the desktop is still GNOME, the account has a
session recorded from before the migration:

```bash
grep -i session /var/lib/AccountsService/users/"$USER"
ls /usr/share/xsessions
```

Both `Session` and `XSession` should name an entry from `/usr/share/xsessions`,
normally `xubuntu`. `/etc/lightdm/lightdm.conf.d/60-nikos.conf` holds the
system-wide default. You can also pick the session from the gear menu on the
login screen.

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

Note: role tags must be explicitly set in `site.yml`. The optional roles (`network`, `music`, `education`, `neovim`, `java`, `podman`) are tag-gated by default.
