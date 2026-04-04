#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] && { echo "ERROR: Do not run NikOS installer as root. Use a regular user account." >&2; exit 1; }

REPO_URL="https://github.com/nikolareljin/nikos"
NIKOS_VERSION="0.2.0"
NIKOS_HOME="${HOME}/.local/share/nikos"
HELPERS="${NIKOS_HOME}/scripts/script-helpers/helpers.sh"

echo "NikOS ${NIKOS_VERSION} — Neural Innovation for Knowledge OS"
echo "Light system. Heavy thinking."
echo ""

# Ensure apt-based system
if ! command -v apt-get &>/dev/null; then
  echo "ERROR: NikOS requires an apt-based system (Ubuntu 24.04 LTS)." >&2
  exit 1
fi

# Install core bootstrap deps (git, dialog, ansible)
_need_packages=()
command -v git             &>/dev/null || _need_packages+=(git)
command -v dialog          &>/dev/null || _need_packages+=(dialog)
command -v ansible-playbook &>/dev/null || _need_packages+=(ansible)

if [[ ${#_need_packages[@]} -gt 0 ]]; then
  echo "Installing bootstrap packages: ${_need_packages[*]}"
  sudo apt-get update -qq
  sudo apt-get install -y "${_need_packages[@]}"
fi

# Clone (or update) the repo with submodules to a persistent location
if [[ -d "${NIKOS_HOME}/.git" ]]; then
  echo "Updating NikOS repo at ${NIKOS_HOME}..."
  git -C "${NIKOS_HOME}" pull --ff-only
  git -C "${NIKOS_HOME}" submodule update --init --recursive
else
  echo "Cloning NikOS repo to ${NIKOS_HOME}..."
  git clone --recurse-submodules "${REPO_URL}" "${NIKOS_HOME}"
fi

# Source script-helpers
if [[ -f "${HELPERS}" ]]; then
  # shellcheck source=/dev/null
  source "${HELPERS}"
  shlib_import logging dialog
  _USE_DIALOG=true
else
  echo "WARNING: script-helpers not found; falling back to plain prompts." >&2
  _USE_DIALOG=false
fi

# Bundle selection ─────────────────────────────────────────────────
_select_bundles_dialog() {
  local _cols _rows
  dialog_init
  local result
  result=$(
    dialog --stdout \
      --title "NikOS ${NIKOS_VERSION} — Optional Bundles" \
      --checklist "Space to toggle, Enter to confirm:" \
      "${DIALOG_HEIGHT}" "${DIALOG_WIDTH}" 3 \
      "network"   "Network tools (nmap, wireshark, OpenVPN)"         off \
      "music"     "Music tools (LMMS, Ardour, Audacity)"             off \
      "education" "Education tools (LibreOffice, draw.io, Anki)"     off \
    2>/dev/null
  ) || result=""
  echo "${result}"
}

_select_bundles_plain() {
  local _selected=()
  echo "Optional app bundles (press Enter to skip each):"
  read -r -p "  Install network tools? (nmap, wireshark) [y/N] " opt_network </dev/tty
  read -r -p "  Install music tools? (LMMS, Ardour, Audacity) [y/N] " opt_music </dev/tty
  read -r -p "  Install education tools? (LibreOffice, draw.io, Anki) [y/N] " opt_education </dev/tty
  [[ "${opt_network,,}"   == "y" ]] && _selected+=("network")
  [[ "${opt_music,,}"     == "y" ]] && _selected+=("music")
  [[ "${opt_education,,}" == "y" ]] && _selected+=("education")
  echo "${_selected[*]}"
}

if [[ "${_USE_DIALOG}" == "true" ]] && check_if_dialog_installed 2>/dev/null; then
  _raw=$(_select_bundles_dialog)
  # dialog --checklist returns space-separated quoted tokens; normalize
  _raw=${_raw//\"/}
  read -ra SELECTED_BUNDLES <<< "${_raw}"
else
  read -ra SELECTED_BUNDLES <<< "$(_select_bundles_plain)"
fi

# Build ansible tag args ───────────────────────────────────────────
SKIP_TAGS=""
for _bundle in network music education; do
  if ! printf '%s\n' "${SELECTED_BUNDLES[@]}" | grep -qx "${_bundle}"; then
    SKIP_TAGS="${SKIP_TAGS},${_bundle}"
  fi
done

# Run the playbook from local clone ───────────────────────────────
if [[ "${_USE_DIALOG}" == "true" ]]; then
  print_info "Running NikOS ${NIKOS_VERSION} playbook..."
else
  echo "Running NikOS ${NIKOS_VERSION} playbook..."
fi

PLAY_OPTS=(-i "${NIKOS_HOME}/inventory/local" "${NIKOS_HOME}/site.yml" --ask-become-pass)
[[ -n "${SKIP_TAGS}" ]] && PLAY_OPTS+=(--skip-tags "${SKIP_TAGS#,}")

ansible-playbook "${PLAY_OPTS[@]}"

echo ""
echo "NikOS ${NIKOS_VERSION} installation complete."
echo "Log out and back in to start Xfce."
