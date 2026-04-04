#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] && { echo "ERROR: Do not run NikOS installer as root. Use a regular user account." >&2; exit 1; }

REPO_URL="https://github.com/nikolareljin/nikos"
NIKOS_VERSION="0.1.0"

echo "NikOS ${NIKOS_VERSION} — Neural Innovation for Knowledge OS"
echo "Light system. Heavy thinking."
echo ""

# Prompt for optional roles
echo "Optional app bundles (press Enter to skip each):"
read -r -p "  Install network tools? (nmap, wireshark) [y/N] " opt_network </dev/tty
read -r -p "  Install music tools? (LMMS, Ardour, Audacity) [y/N] " opt_music </dev/tty
read -r -p "  Install education tools? (LibreOffice, draw.io, Anki) [y/N] " opt_education </dev/tty

SKIP_TAGS=""

[[ "${opt_network,,}" != "y" ]] && SKIP_TAGS="${SKIP_TAGS},network"
[[ "${opt_music,,}" != "y" ]] && SKIP_TAGS="${SKIP_TAGS},music"
[[ "${opt_education,,}" != "y" ]] && SKIP_TAGS="${SKIP_TAGS},education"

# Ensure we're on an apt-based system
if ! command -v apt-get &>/dev/null; then
  echo "ERROR: NikOS requires an apt-based system (Ubuntu 24.04 LTS)." >&2
  exit 1
fi

# Install Ansible if not present
if ! command -v ansible-playbook &>/dev/null; then
  echo "Installing Ansible..."
  sudo apt-get update -qq
  sudo apt-get install -y ansible
  if ! command -v ansible-pull &>/dev/null; then
    echo "ERROR: ansible-pull not found after Ansible installation." >&2
    exit 1
  fi
fi

echo "Running NikOS playbook via ansible-pull..."
PULL_OPTS=(-U "${REPO_URL}" site.yml -i inventory/local --ask-become-pass)
[[ -n "${SKIP_TAGS}" ]] && PULL_OPTS+=(--skip-tags "${SKIP_TAGS#,}")

ansible-pull "${PULL_OPTS[@]}"

echo ""
echo "NikOS ${NIKOS_VERSION} installation complete."
echo "Log out and back in to start Xfce."
