#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/nikolareljin/nikos-os"
NIKOS_VERSION="0.1.0"

echo "NikOS ${NIKOS_VERSION} — Neural Innovation for Knowledge OS"
echo "Light system. Heavy thinking."
echo ""

# Prompt for optional roles
echo "Optional app bundles (press Enter to skip each):"
read -r -p "  Install network tools? (nmap, wireshark) [y/N] " opt_network
read -r -p "  Install music tools? (LMMS, Ardour, Audacity) [y/N] " opt_music
read -r -p "  Install education tools? (LibreOffice, draw.io, Anki) [y/N] " opt_education

TAGS="all"
SKIP_TAGS=""

[[ "${opt_network,,}" != "y" ]] && SKIP_TAGS="${SKIP_TAGS},network"
[[ "${opt_music,,}" != "y" ]] && SKIP_TAGS="${SKIP_TAGS},music"
[[ "${opt_education,,}" != "y" ]] && SKIP_TAGS="${SKIP_TAGS},education"

# Install Ansible if not present
if ! command -v ansible-playbook &>/dev/null; then
  echo "Installing Ansible..."
  sudo apt-get update -qq
  sudo apt-get install -y ansible
fi

echo "Running NikOS playbook via ansible-pull..."
PULL_OPTS="-U ${REPO_URL} site.yml"
if [[ -n "${SKIP_TAGS}" ]]; then
  # remove leading comma
  SKIP_TAGS="${SKIP_TAGS#,}"
  PULL_OPTS="${PULL_OPTS} --skip-tags ${SKIP_TAGS}"
fi

# shellcheck disable=SC2086
ansible-pull ${PULL_OPTS}

echo ""
echo "NikOS ${NIKOS_VERSION} installation complete."
echo "Log out and back in to start Xfce."
