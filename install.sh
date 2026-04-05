#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] && { echo "ERROR: Do not run NikOS installer as root. Use a regular user account." >&2; exit 1; }

REPO_URL="https://github.com/nikolareljin/nikos"
NIKOS_VERSION="0.2.0"
NIKOS_HOME="${HOME}/.local/share/nikos"
HELPERS="${NIKOS_HOME}/scripts/script-helpers/helpers.sh"
REPO_SYNC_HELPERS_REL="scripts/repo-sync.sh"
USE_DIALOG="${NIKOS_USE_DIALOG:-1}"
MAIN_VARS_REL="vars/main.yml"
LOCAL_VARS_REL="vars/local.yml"

echo "NikOS ${NIKOS_VERSION} — Neural Innovation for Knowledge OS"
echo "Light system. Heavy thinking."
echo ""

# Ensure apt-based system
if ! command -v apt-get &>/dev/null; then
  echo "ERROR: NikOS requires an apt-based system (Ubuntu 24.04 LTS)." >&2
  exit 1
fi

# Install core bootstrap deps (git, ansible, and dialog unless plain mode is forced)
_need_packages=()
command -v git             &>/dev/null || _need_packages+=(git)
command -v ansible-playbook &>/dev/null || _need_packages+=(ansible)
if [[ "${USE_DIALOG}" != "0" ]]; then
  command -v dialog &>/dev/null || _need_packages+=(dialog)
fi

if [[ ${#_need_packages[@]} -gt 0 ]]; then
  echo "Installing bootstrap packages: ${_need_packages[*]}"
  sudo apt-get update -qq
  sudo apt-get install -y "${_need_packages[@]}"
fi

_source_repo_sync_helpers() {
  local helpers_path=""
  local script_dir

  if [[ -f "${NIKOS_HOME}/${REPO_SYNC_HELPERS_REL}" ]]; then
    helpers_path="${NIKOS_HOME}/${REPO_SYNC_HELPERS_REL}"
  else
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "${script_dir}/${REPO_SYNC_HELPERS_REL}" ]]; then
      helpers_path="${script_dir}/${REPO_SYNC_HELPERS_REL}"
    fi
  fi

  if [[ -z "${helpers_path}" ]]; then
    return 1
  fi

  # shellcheck source=/dev/null
  source "${helpers_path}"
}

_pull_repo_updates_bootstrap() {
  local stash_ref=""

  if [[ -f "${NIKOS_HOME}/${LOCAL_VARS_REL}" ]]; then
    :
  elif ! git -C "${NIKOS_HOME}" diff --quiet -- "${MAIN_VARS_REL}" || \
       ! git -C "${NIKOS_HOME}" diff --cached --quiet -- "${MAIN_VARS_REL}"; then
    echo "Migrating local vars/main.yml customizations to vars/local.yml..."
    cp "${NIKOS_HOME}/${MAIN_VARS_REL}" "${NIKOS_HOME}/${LOCAL_VARS_REL}"
    git -C "${NIKOS_HOME}" restore --staged --worktree --source=HEAD -- "${MAIN_VARS_REL}"
  fi

  if ! git -C "${NIKOS_HOME}" diff --quiet || \
     ! git -C "${NIKOS_HOME}" diff --cached --quiet || \
     [[ -n "$(git -C "${NIKOS_HOME}" ls-files --others --exclude-standard)" ]]; then
    echo "Temporarily stashing local changes before pulling updates..."
    git -C "${NIKOS_HOME}" stash push --include-untracked --message "nikos-install-autostash" >/dev/null
    stash_ref="stash@{0}"
  fi

  git -C "${NIKOS_HOME}" pull --ff-only
  git -C "${NIKOS_HOME}" submodule update --init --recursive

  if [[ -n "${stash_ref}" ]]; then
    echo "Re-applying local changes..."
    if ! git -C "${NIKOS_HOME}" stash pop --index "${stash_ref}" >/dev/null; then
      echo "ERROR: Updates were pulled, but local changes did not reapply cleanly. Resolve the git conflicts in ${NIKOS_HOME}, then rerun the installer or 'nikos update'." >&2
      exit 1
    fi
  fi
}

# Clone (or update) the repo with submodules to a persistent location
mkdir -p "$(dirname "${NIKOS_HOME}")"
if [[ -e "${NIKOS_HOME}" && ! -d "${NIKOS_HOME}/.git" ]]; then
  echo "ERROR: ${NIKOS_HOME} exists but is not a git checkout. Move or remove that directory, then rerun the installer." >&2
  exit 1
fi

if [[ -d "${NIKOS_HOME}/.git" ]]; then
  echo "Updating NikOS repo at ${NIKOS_HOME}..."
  if _source_repo_sync_helpers; then
    if ! _pull_repo_updates "nikos-install-autostash"; then
      echo "ERROR: Updates were pulled, but local changes did not reapply cleanly. Resolve the git conflicts in ${NIKOS_HOME}, then rerun the installer or 'nikos update'." >&2
      exit 1
    fi
  else
    _pull_repo_updates_bootstrap
  fi
else
  echo "Cloning NikOS repo to ${NIKOS_HOME}..."
  git clone --recurse-submodules "${REPO_URL}" "${NIKOS_HOME}"
fi

# Source script-helpers
if [[ -f "${HELPERS}" ]]; then
  # shellcheck source=/dev/null
  source "${HELPERS}"
  if [[ "${USE_DIALOG}" == "0" ]]; then
    shlib_import logging
    _USE_DIALOG=false
  else
    shlib_import logging dialog
    _USE_DIALOG=true
  fi
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
      "education" "Education tools (LibreOffice, draw.io, Anki)"     off
  ) || result=""
  echo "${result}"
}

_select_bundles_plain() {
  local _selected=()
  echo "Optional app bundles (press Enter to skip each):"
  read -r -p "  Install network tools? (nmap, wireshark, OpenVPN) [y/N] " opt_network </dev/tty
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

(
  cd "${NIKOS_HOME}"
  ANSIBLE_CONFIG="${NIKOS_HOME}/ansible.cfg" ansible-playbook "${PLAY_OPTS[@]}"
)

echo ""
echo "NikOS ${NIKOS_VERSION} installation complete."
echo "Log out and back in to start Xfce."
