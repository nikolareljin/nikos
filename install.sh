#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] && { echo "ERROR: Do not run NikOS installer as root. Use a regular user account." >&2; exit 1; }

# Environment variables:
# NIKOS_REPO_URL: Custom Git repository URL to clone NikOS from
#                  (default: https://github.com/nikolareljin/nikos)
# NIKOS_HOME: Base installation directory for NikOS
#             (default: ${HOME}/.local/share/nikos)
# NIKOS_USE_DIALOG: Use dialog-based prompts when available; set to 0 for plain mode
#                   (default: 1)
# NIKOS_SKIP_REPO_SYNC: Skip repository synchronization/update logic when set to 1
#                       (default: 0)
REPO_URL="${NIKOS_REPO_URL:-https://github.com/nikolareljin/nikos}"
NIKOS_VERSION="0.2.0"
NIKOS_HOME="${NIKOS_HOME:-${HOME}/.local/share/nikos}"
HELPERS="${NIKOS_HOME}/scripts/script-helpers/helpers.sh"
REPO_SYNC_HELPERS_REL="scripts/repo-sync.sh"
USE_DIALOG="${NIKOS_USE_DIALOG:-1}"
MAIN_VARS_REL="vars/main.yml"
LOCAL_VARS_REL="vars/local.yml"
SKIP_REPO_SYNC="${NIKOS_SKIP_REPO_SYNC:-0}"
ANSIBLE_REQUIREMENTS_REL="requirements.yml"

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

# Source repo sync helpers if available, to reuse the git stash/pop logic for smoother updates if the installer is re-run
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

# Check if script-helpers is present, which indicates the repo and submodules are properly staged
_ensure_script_helpers() {
  if [[ -f "${HELPERS}" ]]; then
    return 0
  fi

  if [[ -d "${NIKOS_HOME}/.git" ]]; then
    echo "Ensuring NikOS submodules are initialized..."
    git -C "${NIKOS_HOME}" submodule sync --recursive
    git -C "${NIKOS_HOME}" submodule update --init --recursive
  fi

  [[ -f "${HELPERS}" ]]
}

_ensure_ansible_collections() {
  local requirements_path=""
  local script_dir=""

  if [[ -f "${NIKOS_HOME}/${ANSIBLE_REQUIREMENTS_REL}" ]]; then
    requirements_path="${NIKOS_HOME}/${ANSIBLE_REQUIREMENTS_REL}"
  else
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "${script_dir}/${ANSIBLE_REQUIREMENTS_REL}" ]]; then
      requirements_path="${script_dir}/${ANSIBLE_REQUIREMENTS_REL}"
    fi
  fi

  if [[ -z "${requirements_path}" ]]; then
    echo "ERROR: Ansible collection requirements file not found. Expected ${ANSIBLE_REQUIREMENTS_REL}." >&2
    exit 1
  fi

  echo "Installing required Ansible collections..."
  ansible-galaxy collection install -r "${requirements_path}"
}

# Pull repo updates with stashing if needed, for smoother experience when re-running the installer
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

  if ! git -C "${NIKOS_HOME}" pull --ff-only; then
    echo "ERROR: Failed to pull updates for ${NIKOS_HOME}." >&2
    echo "This can happen because of a non-fast-forward branch state, network/authentication issues, or a repository problem." >&2
    echo "Review the git output above, resolve the issue in ${NIKOS_HOME}, then rerun the installer or 'nikos update'." >&2
    exit 2
  fi

  if ! git -C "${NIKOS_HOME}" submodule update --init --recursive; then
    echo "ERROR: Failed to update NikOS submodules in ${NIKOS_HOME}." >&2
    echo "Review the git output above, verify network access and repository state, then rerun the installer or 'nikos update'." >&2
    exit 3
  fi

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
if [[ "${SKIP_REPO_SYNC}" == "1" ]]; then
  echo "Using NikOS source already staged at ${NIKOS_HOME}..."
  if [[ ! -f "${NIKOS_HOME}/site.yml" ]]; then
    echo "ERROR: ${NIKOS_HOME} does not look like a NikOS checkout. Stage the repo there or unset NIKOS_SKIP_REPO_SYNC." >&2
    exit 1
  fi
else
  if [[ -e "${NIKOS_HOME}" && ! -d "${NIKOS_HOME}/.git" ]]; then
    echo "ERROR: ${NIKOS_HOME} exists but is not a git checkout. Move or remove that directory, then rerun the installer." >&2
    exit 1
  fi

  if [[ -d "${NIKOS_HOME}/.git" ]]; then
    echo "Updating NikOS repo at ${NIKOS_HOME}..."
    if _source_repo_sync_helpers; then
      if _pull_repo_updates "nikos-install-autostash"; then
        :
      else
        update_rc=$?
        case "${update_rc}" in
          1)
            echo "ERROR: Updates were pulled, but local changes did not reapply cleanly. Resolve the git conflicts in ${NIKOS_HOME}, then rerun the installer or 'nikos update'." >&2
            ;;
          2)
            echo "ERROR: Failed to pull updates for ${NIKOS_HOME}. Review the git output above, resolve the issue, then rerun the installer or 'nikos update'." >&2
            ;;
          3)
            echo "ERROR: Failed to update NikOS submodules in ${NIKOS_HOME}. Review the git output above, resolve the issue, then rerun the installer or 'nikos update'." >&2
            ;;
          *)
            echo "ERROR: Failed to update NikOS repo at ${NIKOS_HOME}. Review the git output above, then rerun the installer or 'nikos update'." >&2
            ;;
        esac
        exit 1
      fi
    else
      _pull_repo_updates_bootstrap
    fi
  else
    echo "Cloning NikOS repo to ${NIKOS_HOME}..."
    git clone --recurse-submodules "${REPO_URL}" "${NIKOS_HOME}"
  fi
fi

# Source script-helpers
if _ensure_script_helpers; then
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
  echo "ERROR: script-helpers is missing from ${NIKOS_HOME}. Check the git/submodule output above and rerun the installer." >&2
  exit 1
fi

_ensure_ansible_collections

# Bundle selection ─────────────────────────────────────────────────
_select_bundles_dialog() {
  dialog_init
  local result dialog_status
  if result=$(
    dialog --stdout \
      --title "NikOS ${NIKOS_VERSION} — Optional Bundles" \
      --checklist "Space to toggle, Enter to confirm:" \
      "${DIALOG_HEIGHT}" "${DIALOG_WIDTH}" 3 \
      "network"   "Network tools (nmap, wireshark, OpenVPN)"         off \
      "music"     "Music tools (LMMS, Ardour, Audacity)"             off \
      "education" "Education tools (LibreOffice, draw.io, Anki)"     off
  ); then
    echo "${result}"
    return 0
  else
    dialog_status=$?
  fi

  return "${dialog_status}"
}

_select_ai_tools_dialog() {
  dialog_init
  local result dialog_status
  if result=$(
    dialog --stdout \
      --title "NikOS ${NIKOS_VERSION} — AI Tools" \
      --checklist "Space to toggle, Enter to confirm:" \
      "${DIALOG_HEIGHT}" "${DIALOG_WIDTH}" 6 \
      "ai-local"        "Ollama, Miniforge, nikos-ai env, aider, agent SDKs" on \
      "ai-gemini"       "Gemini CLI"                                           on \
      "ai-claude"       "Claude Code CLI"                                      on \
      "ai-copilot-cli"  "GitHub Copilot CLI extension"                         on \
      "ai-runner"       "ai-runner local model UI"                             on \
      "ai-vscode"       "AI VS Code extensions (Continue, Copilot)"            on
  ); then
    echo "${result}"
    return 0
  else
    dialog_status=$?
  fi

  return "${dialog_status}"
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

_select_ai_tools_plain() {
  local _selected=()
  echo "AI tools (press Enter to accept the default Yes):"
  read -r -p "  Install Ollama, Miniforge, nikos-ai env, aider, and agent SDKs? [Y/n] " opt_ai_local </dev/tty
  read -r -p "  Install Gemini CLI? [Y/n] " opt_ai_gemini </dev/tty
  read -r -p "  Install Claude Code CLI? [Y/n] " opt_ai_claude </dev/tty
  read -r -p "  Install GitHub Copilot CLI extension? [Y/n] " opt_ai_copilot_cli </dev/tty
  read -r -p "  Install ai-runner local model UI? [Y/n] " opt_ai_runner </dev/tty
  read -r -p "  Install AI VS Code extensions (Continue, Copilot)? [Y/n] " opt_ai_vscode </dev/tty
  [[ -z "${opt_ai_local}" || "${opt_ai_local,,}" == "y" ]] && _selected+=("ai-local")
  [[ -z "${opt_ai_gemini}" || "${opt_ai_gemini,,}" == "y" ]] && _selected+=("ai-gemini")
  [[ -z "${opt_ai_claude}" || "${opt_ai_claude,,}" == "y" ]] && _selected+=("ai-claude")
  [[ -z "${opt_ai_copilot_cli}" || "${opt_ai_copilot_cli,,}" == "y" ]] && _selected+=("ai-copilot-cli")
  [[ -z "${opt_ai_runner}" || "${opt_ai_runner,,}" == "y" ]] && _selected+=("ai-runner")
  [[ -z "${opt_ai_vscode}" || "${opt_ai_vscode,,}" == "y" ]] && _selected+=("ai-vscode")
  echo "${_selected[*]}"
}

if [[ "${_USE_DIALOG}" == "true" ]] && check_if_dialog_installed 2>/dev/null; then
  if ! _raw=$(_select_bundles_dialog); then
    echo "Installer canceled during optional bundle selection." >&2
    exit 130
  fi
  # dialog --checklist returns space-separated quoted tokens; normalize
  _raw=${_raw//\"/}
  read -ra SELECTED_BUNDLES <<< "${_raw}"
  if ! _raw=$(_select_ai_tools_dialog); then
    echo "Installer canceled during AI tool selection." >&2
    exit 130
  fi
  _raw=${_raw//\"/}
  read -ra SELECTED_AI_TOOLS <<< "${_raw}"
else
  read -ra SELECTED_BUNDLES <<< "$(_select_bundles_plain)"
  read -ra SELECTED_AI_TOOLS <<< "$(_select_ai_tools_plain)"
fi

# Build ansible tag args ───────────────────────────────────────────
SKIP_TAGS=""
for _bundle in network music education; do
  if ! printf '%s\n' "${SELECTED_BUNDLES[@]}" | grep -qx "${_bundle}"; then
    SKIP_TAGS="${SKIP_TAGS},${_bundle}"
  fi
done
for _tool in ai-local ai-gemini ai-claude ai-copilot-cli ai-runner ai-vscode; do
  if ! printf '%s\n' "${SELECTED_AI_TOOLS[@]}" | grep -qx "${_tool}"; then
    SKIP_TAGS="${SKIP_TAGS},${_tool}"
  fi
done

if ! printf '%s\n' "${SELECTED_AI_TOOLS[@]}" | grep -Eqx 'ai-gemini|ai-claude'; then
  SKIP_TAGS="${SKIP_TAGS},ai-node"
fi

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
