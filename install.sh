#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] && { echo "ERROR: Do not run NikOS installer as root. Use a regular user account." >&2; exit 1; }

# Options:
# --dev            Run the checkout this script lives in, exactly as it stands,
#                  including uncommitted changes. No clone, fetch or pull.
# --ref <ref>      Install a specific branch or tag instead of the latest release.
# --help           Show usage and exit.
#
# Environment variables:
# NIKOS_REPO_URL: Custom Git repository URL to clone NikOS from
#                  (default: https://github.com/nikolareljin/nikos)
# NIKOS_REPO_REF: Branch/tag to check out in NIKOS_HOME before running the playbook
#                 (default: the latest release tag; same as --ref)
# NIKOS_DEV: Set to 1 for --dev
# NIKOS_HOME: Base installation directory for NikOS
#             (default: ${HOME}/.local/share/nikos)
# NIKOS_USE_DIALOG: Use dialog-based prompts when available; set to 0 for plain mode
#                   (default: 1)
# NIKOS_SKIP_REPO_SYNC: Skip repository synchronization/update logic when set to 1
#                       (default: 0)
REPO_URL="${NIKOS_REPO_URL:-https://github.com/nikolareljin/nikos}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
NIKOS_VERSION="$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null || echo "unknown")"
REPO_REF="${NIKOS_REPO_REF:-}"
NIKOS_HOME="${NIKOS_HOME:-${HOME}/.local/share/nikos}"
NIKOS_CONFIG_DIR="${HOME}/.config/nikos"
SELECTIONS_FILE="${NIKOS_CONFIG_DIR}/selected-options.env"
HELPERS="${NIKOS_HOME}/scripts/script-helpers/helpers.sh"
NIKOS_LOG_DIR="${NIKOS_CONFIG_DIR}/logs"
INSTALL_LOG="${NIKOS_LOG_DIR}/install-$(date +%Y%m%d-%H%M%S).log"
REPO_SYNC_HELPERS_REL="scripts/repo-sync.sh"
PROGRESS_LIB_REL="scripts/nikos-progress.sh"
USE_DIALOG="${NIKOS_USE_DIALOG:-1}"
# Read by _migrate_local_vars in scripts/repo-sync.sh, which is sourced at runtime.
# shellcheck disable=SC2034
MAIN_VARS_REL="vars/main.yml"
LOCAL_VARS_REL="vars/local.yml"
SKIP_REPO_SYNC="${NIKOS_SKIP_REPO_SYNC:-0}"
ANSIBLE_REQUIREMENTS_REL="requirements.yml"
MIN_ANSIBLE_VERSION="2.15.0"
BECOME_PASSWORD_FILE=""
DEV_MODE="${NIKOS_DEV:-0}"

_usage() {
  cat <<EOF
NikOS installer

Usage: install.sh [options]

Options:
  --dev            Run the checkout this script lives in, exactly as it stands,
                   including uncommitted changes. Nothing is cloned, fetched or
                   pulled, and ${HOME}/.local/share/nikos is left untouched.
  --ref <ref>      Install a specific branch or tag instead of the latest release.
  --help, -h       Show this message and exit.

With no options, the latest release tag is installed.
EOF
}

# Argument handling runs before any log, network or package work, so a bad
# invocation costs nothing.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)
      DEV_MODE=1
      shift
      ;;
    --ref)
      [[ $# -ge 2 ]] || { echo "ERROR: --ref needs a branch or tag." >&2; exit 2; }
      REPO_REF="$2"
      shift 2
      ;;
    --ref=*)
      REPO_REF="${1#--ref=}"
      shift
      ;;
    --help | -h)
      _usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option '$1'." >&2
      _usage >&2
      exit 2
      ;;
  esac
done

if [[ "${DEV_MODE}" == "1" ]]; then
  if [[ -n "${REPO_REF}" ]]; then
    echo "ERROR: --dev runs the current checkout, so it cannot be combined with --ref or NIKOS_REPO_REF." >&2
    exit 2
  fi
  if [[ ! -f "${SCRIPT_DIR}/site.yml" ]]; then
    echo "ERROR: --dev runs the checkout this script lives in, but ${SCRIPT_DIR} has no site.yml." >&2
    echo "Run it from a NikOS checkout, or drop --dev to install the latest release." >&2
    exit 2
  fi
  # Everything downstream keys off NIKOS_HOME, so pointing it at the checkout
  # is the whole of dev mode.
  NIKOS_HOME="${SCRIPT_DIR}"
  HELPERS="${NIKOS_HOME}/scripts/script-helpers/helpers.sh"
  SKIP_REPO_SYNC=1
fi

# Returns 0 if dialog is enabled, the binary is present, and stdin/stdout are connected to a TTY.
_can_use_dialog() {
  [[ "${USE_DIALOG}" != "0" ]] && command -v dialog &>/dev/null && [[ -t 0 ]] && [[ -t 1 ]]
}

# Log file helpers (available before script-helpers is sourced)
_logfile() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "${INSTALL_LOG}"
}

_safe_logfile() {
  _logfile "$@" 2>/dev/null || true
}

_restore_terminal_cursor() {
  if [[ -e /dev/tty ]] && { printf '' >/dev/tty; } 2>/dev/null; then
    { tput cnorm 2>/dev/null || printf '\033[?25h'; } >/dev/tty 2>/dev/null || true
  elif [[ -t 1 ]]; then
    tput cnorm 2>/dev/null || printf '\033[?25h' || true
  fi
}

_cleanup_become_password_file() {
  if [[ -n "${BECOME_PASSWORD_FILE:-}" && -f "${BECOME_PASSWORD_FILE}" ]]; then
    rm -f -- "${BECOME_PASSWORD_FILE}"
  fi
  BECOME_PASSWORD_FILE=""
}

_cleanup_install() {
  _cleanup_become_password_file
  _restore_terminal_cursor
}

# Strip ANSI escape codes from a stream, for the fallback progress view.
_strip_ansi_stream() {
  LC_ALL=C sed -u \
    -e 's|\x1b\][^\x07]*\x07||g' \
    -e 's|\x1b\[[0-9;:<=>?]*[ -/]*[@-~]||g' \
    -e 's|\x1b[()][A-Za-z0-9]||g' \
    -e 's|\r$||'
}

# Strip ANSI escape codes from the log after a tee'd run.
# LC_ALL=C keeps the [ -/] and [@-~] ranges byte-ordered; under a UTF-8 locale
# they follow collation order and silently stop matching.
_strip_ansi_from_log() {
  LC_ALL=C sed -i \
    -e 's|\x1b\][^\x07]*\x07||g' \
    -e 's|\x1b\[[0-9;:<=>?]*[ -/]*[@-~]||g' \
    -e 's|\x1b[()][A-Za-z0-9]||g' \
    "${INSTALL_LOG}" 2>/dev/null || true
}

_install_bootstrap_packages() {
  sudo apt-get update -qq
  sudo apt-get install -y "$@"
}

_create_become_password_file() {
  local password="$1"

  _cleanup_become_password_file
  BECOME_PASSWORD_FILE="$(mktemp "${TMPDIR:-/tmp}/nikos-become.XXXXXX")"
  chmod 600 "${BECOME_PASSWORD_FILE}"
  printf '%s\n' "${password}" > "${BECOME_PASSWORD_FILE}"
}

_os_release_value() {
  local key="$1"
  local line value

  [[ -r /etc/os-release ]] || return 1
  while IFS='=' read -r line value; do
    [[ "${line}" == "${key}" ]] || continue
    value="${value%\"}"
    value="${value#\"}"
    printf '%s\n' "${value}"
    return 0
  done < /etc/os-release

  return 1
}

_is_supported_ubuntu_system() {
  local os_id version_id

  os_id="$(_os_release_value ID || true)"
  version_id="$(_os_release_value VERSION_ID || true)"

  [[ "${os_id}" == "ubuntu" && "${version_id}" == "24.04" ]]
}

_ansible_playbook_version() {
  ansible-playbook --version 2>/dev/null | sed -n '1s/.* \([0-9][0-9.]*\).*/\1/p'
}

_version_at_least() {
  local current="$1"
  local required="$2"

  [[ "$(printf '%s\n%s\n' "${required}" "${current}" | sort -V | head -n 1)" == "${required}" ]]
}

_offer_ansible_upgrade() {
  local ansible_version="$1"
  local message=""
  local answer=""

  message="NikOS requires ansible-playbook ${MIN_ANSIBLE_VERSION} or newer; found ${ansible_version:-an unknown version}.

Upgrade Ansible from the Ansible Ubuntu PPA now?"
  if _can_use_dialog; then
    dialog --title "NikOS ${NIKOS_VERSION} - Ansible Upgrade Required" \
      --yesno "${message}" 11 72
    return $?
  fi

  echo "${message}"
  printf 'Upgrade Ansible now? [y/N] ' >&2
  if read -r answer 2>/dev/null </dev/tty; then
    :
  elif [[ -t 0 ]] && read -r answer; then
    :
  else
    return 1
  fi
  [[ "${answer,,}" == "y" || "${answer,,}" == "yes" ]]
}

_upgrade_ansible() {
  sudo apt-get update -qq
  sudo apt-get install -y software-properties-common
  sudo apt-add-repository --yes --update ppa:ansible/ansible
  sudo apt-get install -y ansible
}

_require_supported_ansible() {
  local ansible_version=""
  local message=""

  ansible_version="$(_ansible_playbook_version)"
  if [[ -n "${ansible_version}" ]] && _version_at_least "${ansible_version}" "${MIN_ANSIBLE_VERSION}"; then
    return 0
  fi

  if ! _offer_ansible_upgrade "${ansible_version}"; then
    message="NikOS requires ansible-playbook ${MIN_ANSIBLE_VERSION} or newer; found ${ansible_version:-an unknown version}. Upgrade Ansible, then rerun the installer."
    _safe_logfile "[FAILED] ${message}"
    echo "ERROR: ${message}" >&2
    exit 1
  fi

  _logfile "Upgrading Ansible from unsupported version: ${ansible_version:-unknown}"
  if _can_use_dialog; then
    dialog --title "NikOS ${NIKOS_VERSION} - Ansible Upgrade" \
      --infobox "Upgrading Ansible from the Ansible Ubuntu PPA..." 5 64 || true
    if _upgrade_ansible >> "${INSTALL_LOG}" 2>&1; then
      :
    else
      upgrade_rc=$?
      _show_logged_command_failure "Failed to upgrade Ansible from the Ansible Ubuntu PPA." "${upgrade_rc}"
      exit "${upgrade_rc}"
    fi
  else
    echo "Upgrading Ansible from the Ansible Ubuntu PPA..."
    _upgrade_ansible
  fi

  ansible_version="$(_ansible_playbook_version)"
  if [[ -n "${ansible_version}" ]] && _version_at_least "${ansible_version}" "${MIN_ANSIBLE_VERSION}"; then
    _logfile "Ansible upgraded OK: ${ansible_version}"
    return 0
  fi

  message="Ansible upgrade finished, but ansible-playbook ${ansible_version:-unknown} is still older than ${MIN_ANSIBLE_VERSION}. Upgrade Ansible, then rerun the installer."
  _safe_logfile "[FAILED] ${message}"
  if _can_use_dialog; then
    dialog --title "NikOS ${NIKOS_VERSION} - Ansible Upgrade Required" \
      --msgbox "${message}" 9 72 || true
  fi
  echo "ERROR: ${message}" >&2
  exit 1
}

_install_log_tail() {
  tail -n 10 "${INSTALL_LOG}" 2>/dev/null || true
}

_show_logged_command_failure() {
  local message="$1"
  local rc="$2"
  local recent_output

  recent_output="$(_install_log_tail)"
  _safe_logfile "[FAILED] ${message} (rc=${rc})"

  if _can_use_dialog; then
    dialog --title "NikOS ${NIKOS_VERSION} — Error" \
      --msgbox "${message}\n\nSee log: ${INSTALL_LOG}\n\nRecent output:\n${recent_output:-No additional details captured.}" \
      18 76 || true
  fi

  echo "ERROR: ${message} See log: ${INSTALL_LOG}" >&2
}

_collect_become_password_dialog() {
  local pw
  if ! pw=$(
    dialog --stdout \
      --title "NikOS ${NIKOS_VERSION} — Sudo Password" \
      --passwordbox "Enter your sudo (become) password to run the Ansible playbook:" \
      8 62
  ); then
    return $?
  fi
  printf '%s\n' "${pw}"
}

# What the user has to do to land in the Xubuntu session. Switching the
# display manager only takes effect once the current graphical session ends,
# and a session started under GDM has to go all the way through a reboot.
_session_next_step() {
  local current="${XDG_CURRENT_DESKTOP:-${DESKTOP_SESSION:-unknown}}"
  case "${current,,}" in
    *xfce*|*xubuntu*)
      echo "Log out and back in to pick up the NikOS Xubuntu session."
      ;;
    *)
      echo "Reboot to finish switching to LightDM and the Xubuntu session (currently running ${current})."
      ;;
  esac
}

# Run ansible-playbook behind the dialog UI.
#
# Prefers the mixedgauge view from scripts/nikos-progress.sh: one row per role,
# an overall percentage and the current task as the caption. Falls back to an
# ANSI-stripped scrolling box when the library, dialog or the task list is
# unavailable. Returns the playbook's own exit status.
_run_playbook_dialog() {
  local title="$1"
  shift
  local -a opts=("$@")
  local -a pipe_status=()
  local rc=0

  _dialog_rc=0
  _tee_rc=0

  if [[ "${_PROGRESS_LIB_LOADED}" == "true" ]] && nikos_progress_supported; then
    dialog_init
    if nikos_progress_plan "${NIKOS_HOME}" "${NIKOS_HOME}/ansible.cfg" "${opts[@]}"; then
      nikos_progress_run "${title}" "${INSTALL_LOG}" \
        "${NIKOS_HOME}" "${NIKOS_HOME}/ansible.cfg" "${opts[@]}"
      rc=$?
      # Same treatment as a failing `tee` in the fallback path below: a run
      # whose log could not be written is reported, not silently accepted.
      _tee_rc="${NIKOS_PROGRESS_LOG_RC:-0}"
      # nikos_progress_run also folds that failure into its own exit status.
      # Hand it back through _tee_rc alone, so the caller prints the message
      # that names the log instead of reporting a bare playbook failure. The
      # optional-bundle gate below tests _tee_rc as well, so masking the rc
      # here does not let follow-on runs start on a host that lost its log.
      if (( _tee_rc != 0 )) && (( rc == _tee_rc )); then
        rc=0
      fi
      _restore_terminal_cursor
      return "${rc}"
    fi
    _safe_logfile "[WARNING] could not enumerate playbook tasks; using the plain progress view"
  fi

  (
    cd "${NIKOS_HOME}" || exit 127
    ANSIBLE_CONFIG="${NIKOS_HOME}/ansible.cfg" ANSIBLE_NOCOLOR=1 ANSIBLE_FORCE_COLOR=0 \
      PYTHONUNBUFFERED=1 ansible-playbook "${opts[@]}"
  ) 2>&1 \
    | _strip_ansi_stream \
    | tee -a "${INSTALL_LOG}" \
    | dialog --title "${title}" \
        --progressbox "Running Ansible playbook..." "${DIALOG_HEIGHT}" "${DIALOG_WIDTH}"
  pipe_status=("${PIPESTATUS[@]}")
  _restore_terminal_cursor
  _tee_rc=${pipe_status[2]:-0}
  _dialog_rc=${pipe_status[3]:-0}
  return "${pipe_status[0]}"
}

# Total one PLAY RECAP field across every recap in a log.
#
# An install can run the playbook more than once - the main run, then a second
# for the optional bundles - and each run prints its own PLAY RECAP. Reading
# them with a bare grep returned one line per recap, so `ok` became "177\n10"
# rather than a number: the summary box printed the remainder on its own line,
# and `[[ "0\n1" -gt 0 ]]` failed with a syntax error and evaluated false, which
# silently hid a real failure in the second run. Summing keeps the value an
# integer whatever the number of runs.
_recap_total() {
  local field="$1" file="$2"
  grep -A2 "^PLAY RECAP" "${file}" 2>/dev/null \
    | grep "localhost" \
    | grep -oP "${field}=\\K[0-9]+" \
    | awk '{ total += $1 } END { print total + 0 }'
}

# Parse Ansible PLAY RECAP and print a summary to screen + log
_install_summary() {
  local rc="${1:-0}"

  _strip_ansi_from_log

  local ok changed failed unreachable
  ok=$(_recap_total ok "${INSTALL_LOG}")
  changed=$(_recap_total changed "${INSTALL_LOG}")
  failed=$(_recap_total failed "${INSTALL_LOG}")
  unreachable=$(_recap_total unreachable "${INSTALL_LOG}")

  echo ""
  echo "----------------------------------------"
  echo "NikOS ${NIKOS_VERSION} install summary"
  echo "  Tasks OK:       ${ok}"
  echo "  Tasks changed:  ${changed}"
  [[ "${failed}"      -gt 0 ]] && echo "  Tasks FAILED:   ${failed}"
  [[ "${unreachable}" -gt 0 ]] && echo "  Unreachable:    ${unreachable}"

  if [[ "${failed}" -gt 0 || "${unreachable}" -gt 0 ]]; then
    echo ""
    echo "Failed tasks:"
    awk '/^TASK \[/{task=$0} /fatal: \[/{print task}' "${INSTALL_LOG}" 2>/dev/null \
      | sed 's/^TASK \[//;s/\] \*.*$//' \
      | sort -u \
      | while IFS= read -r t; do echo "  - ${t}"; done
  fi

  echo ""
  echo "Full log: ${INSTALL_LOG}"
  echo "Latest:   ${NIKOS_LOG_DIR}/install-latest.log"
  echo "----------------------------------------"

  _logfile "[SUMMARY] rc=${rc} ok=${ok} changed=${changed} failed=${failed} unreachable=${unreachable}"
  if [[ "${rc}" -ne 0 ]]; then
    _logfile "[FAILED] Playbook exited with rc=${rc}"
  else
    _logfile "[DONE] Install complete"
  fi

  if _can_use_dialog; then
    local _dlg_body
    _dlg_body="NikOS ${NIKOS_VERSION} install summary

  Tasks OK:      ${ok}
  Tasks changed: ${changed}"
    [[ "${failed}"      -gt 0 ]] && _dlg_body+="
  Tasks FAILED:  ${failed}"
    [[ "${unreachable}" -gt 0 ]] && _dlg_body+="
  Unreachable:   ${unreachable}"
    _dlg_body+="

$(_session_next_step)

  Full log: ${INSTALL_LOG}"
    if [[ "${rc}" -eq 0 ]]; then
      dialog --title "NikOS ${NIKOS_VERSION} — Complete" --msgbox "${_dlg_body}" 17 76 || true
    else
      dialog --title "NikOS ${NIKOS_VERSION} — Failed" --msgbox "${_dlg_body}" 17 76 || true
    fi
  fi
}

mkdir -p "${NIKOS_LOG_DIR}"
ln -sf "${INSTALL_LOG}" "${NIKOS_LOG_DIR}/install-latest.log"
trap '_cleanup_install' EXIT
trap '_cleanup_install; exit 130' INT
trap '_cleanup_install; exit 143' TERM
# Resolved once the repo sync helpers are available: an explicit ref wins,
# otherwise the newest release tag. Empty in dev mode.
TARGET_REPO_REF="${REPO_REF}"
_logfile "=== NikOS ${NIKOS_VERSION} install started ==="
_logfile "User: $(id -un)   Host: $(hostname -s)"
if [[ "${DEV_MODE}" == "1" ]]; then
  _logfile "Mode: dev (running ${NIKOS_HOME} in place, no repo sync)"
elif [[ -n "${TARGET_REPO_REF}" ]]; then
  _logfile "Mode: pinned ref ${TARGET_REPO_REF}"
else
  _logfile "Mode: latest release tag"
fi

if _can_use_dialog; then
  if ! dialog --title "NikOS ${NIKOS_VERSION}" \
    --msgbox "Neural Innovation for Knowledge OS\n\nLight system. Heavy thinking.\n\nPress OK to begin installation." \
    10 52; then
    echo "Installation canceled." >&2
    exit 130
  fi
else
  echo "NikOS ${NIKOS_VERSION} — Neural Innovation for Knowledge OS"
  echo "Light system. Heavy thinking."
  echo ""
fi

# Ensure the installer is running on supported Ubuntu-family media.
if _can_use_dialog; then
  dialog --title "NikOS ${NIKOS_VERSION} — System Check" \
    --infobox "Checking system requirements..." 5 52 || true
fi
if ! _is_supported_ubuntu_system || ! command -v apt-get &>/dev/null; then
  if _can_use_dialog; then
    dialog --title "Error" \
      --msgbox "NikOS requires Xubuntu 24.04 LTS or Ubuntu 24.04 LTS." 7 56
  fi
  echo "ERROR: NikOS requires Xubuntu 24.04 LTS or Ubuntu 24.04 LTS." >&2
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
  if _can_use_dialog; then
    dialog --title "NikOS ${NIKOS_VERSION} — Bootstrap" \
      --infobox "Installing bootstrap packages:\n  ${_need_packages[*]}" 7 60 || true
  else
    echo "Installing bootstrap packages: ${_need_packages[*]}"
  fi
  _logfile "Bootstrap packages: ${_need_packages[*]}"
  if _can_use_dialog; then
    if _install_bootstrap_packages "${_need_packages[@]}" >> "${INSTALL_LOG}" 2>&1; then
      :
    else
      install_rc=$?
      _show_logged_command_failure "Failed to install bootstrap packages." "${install_rc}"
      exit "${install_rc}"
    fi
  else
    _install_bootstrap_packages "${_need_packages[@]}"
  fi
  _logfile "Bootstrap packages installed OK"
else
  _logfile "Bootstrap packages: none needed"
fi

_require_supported_ansible

# Source the repo sync helpers.
#
# The copy at NIKOS_HOME belongs to the *installed* version, which can predate
# this installer: upgrading from 0.4.2 would otherwise load a helper with no
# _sync_repo_to_ref in it. Each candidate is checked for the functions this
# installer actually needs, and a stale one is replaced from the remote rather
# than having its logic duplicated here.
_source_repo_sync_helpers() {
  local candidate=""
  local fresh=""
  local remote_head=""

  for candidate in "${NIKOS_HOME}/${REPO_SYNC_HELPERS_REL}" "${SCRIPT_DIR}/${REPO_SYNC_HELPERS_REL}"; do
    [[ -f "${candidate}" ]] || continue
    # shellcheck source=/dev/null
    source "${candidate}" || continue
    if declare -F _sync_repo_to_ref >/dev/null; then
      return 0
    fi
  done

  [[ -d "${NIKOS_HOME}/.git" ]] || return 1

  echo "Installed repo sync helpers are older than this installer; refreshing them..."
  git -C "${NIKOS_HOME}" fetch --quiet --prune --tags --force origin || return 1

  # Prefer the ref actually being installed, then the newest release, then the
  # remote's default branch.
  for remote_head in ${REPO_REF:+"${REPO_REF}"} \
    "$(git -C "${NIKOS_HOME}" tag --list | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1)" \
    origin/HEAD origin/main origin/master; do
    [[ -n "${remote_head}" ]] || continue
    git -C "${NIKOS_HOME}" rev-parse --verify --quiet "${remote_head}" >/dev/null || continue
    fresh="$(mktemp "${TMPDIR:-/tmp}/nikos-repo-sync.XXXXXX")"
    if git -C "${NIKOS_HOME}" show "${remote_head}:${REPO_SYNC_HELPERS_REL}" > "${fresh}" 2>/dev/null; then
      # shellcheck source=/dev/null
      source "${fresh}"
      rm -f "${fresh}"
      declare -F _sync_repo_to_ref >/dev/null && return 0
    fi
    rm -f "${fresh}"
  done

  return 1
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

  if _can_use_dialog; then
    dialog --title "NikOS ${NIKOS_VERSION}" \
      --infobox "Installing required Ansible collections..." 5 56 || true
    if ansible-galaxy collection install -r "${requirements_path}" >> "${INSTALL_LOG}" 2>&1; then
      :
    else
      collection_rc=$?
      _show_logged_command_failure "Failed to install required Ansible collections." "${collection_rc}"
      exit "${collection_rc}"
    fi
  else
    echo "Installing required Ansible collections..."
    ansible-galaxy collection install -r "${requirements_path}"
  fi
}

_persist_skip_tags() {
  mkdir -p "${NIKOS_CONFIG_DIR}"
  printf 'NIKOS_SKIP_TAGS_SAVED=%q\n' "${1}" > "${SELECTIONS_FILE}"
}

# ── Timezone helpers ──────────────────────────────────────────────────────────

_detect_system_timezone() {
  local tz=""
  tz=$(timedatectl show --property=Timezone --value 2>/dev/null) || true
  if [[ -z "${tz}" ]]; then
    tz=$(tr -d '[:space:]' < /etc/timezone 2>/dev/null) || true
  fi
  printf '%s\n' "${tz:-Europe/London}"
}

_get_configured_timezone() {
  local file="${NIKOS_HOME}/${LOCAL_VARS_REL}"
  if [[ -f "${file}" ]]; then
    grep -oP '^nikos_timezone:\s*["\x27]?\K[^"\x27\s]+' "${file}" 2>/dev/null || true
  fi
}

_set_timezone_in_local_vars() {
  local tz="$1"
  local file="${NIKOS_HOME}/${LOCAL_VARS_REL}"

  mkdir -p "$(dirname "${file}")"
  if [[ ! -f "${file}" ]]; then
    printf -- '---\nnikos_timezone: "%s"\n' "${tz}" > "${file}"
    return
  fi
  if grep -q '^nikos_timezone:' "${file}"; then
    sed -i "s|^nikos_timezone:.*|nikos_timezone: \"${tz}\"|" "${file}"
  else
    printf 'nikos_timezone: "%s"\n' "${tz}" >> "${file}"
  fi
}

_select_timezone_dialog() {
  local detected_tz="$1" configured_tz="$2"
  dialog_init

  # Build menu items (tag + description pairs)
  local items=()
  items+=("auto"   "Auto: use system timezone (${detected_tz})")
  if [[ -n "${configured_tz}" && "${configured_tz}" != "${detected_tz}" ]]; then
    items+=("keep"   "Keep configured: ${configured_tz}")
  fi
  items+=("custom" "Enter a specific timezone")

  local n_items=$(( ${#items[@]} / 2 ))
  local default_item="auto"
  [[ -n "${configured_tz}" && "${configured_tz}" != "${detected_tz}" ]] && default_item="keep"

  local choice
  if ! choice=$(
    dialog --stdout \
      --title "NikOS ${NIKOS_VERSION} — Timezone" \
      --default-item "${default_item}" \
      --menu "System timezone: ${detected_tz}" \
      "${DIALOG_HEIGHT}" "${DIALOG_WIDTH}" "${n_items}" \
      "${items[@]}"
  ); then
    return $?
  fi

  case "${choice}" in
    auto)   printf '%s\n' "${detected_tz}" ;;
    keep)   printf '%s\n' "${configured_tz}" ;;
    custom)
      local default_input="${configured_tz:-${detected_tz}}"
      local custom_tz
      if ! custom_tz=$(
        dialog --stdout \
          --title "NikOS ${NIKOS_VERSION} — Custom Timezone" \
          --inputbox "Enter IANA timezone (e.g. America/New_York, Asia/Tokyo):" \
          8 60 "${default_input}"
      ); then
        return $?
      fi
      printf '%s\n' "${custom_tz:-${detected_tz}}"
      ;;
  esac
}

_select_timezone_plain() {
  local detected_tz="$1" configured_tz="$2"

  echo "Timezone setup:"
  echo "  System timezone (NTP): ${detected_tz}"
  if [[ -n "${configured_tz}" && "${configured_tz}" != "${detected_tz}" ]]; then
    echo "  Configured timezone:   ${configured_tz}"
  fi
  echo ""

  # Build numbered option list
  local -a opts=()
  opts+=("1) Auto: use system timezone (${detected_tz})")
  local keep_n=""
  if [[ -n "${configured_tz}" && "${configured_tz}" != "${detected_tz}" ]]; then
    opts+=("2) Keep configured: ${configured_tz}")
    keep_n="2"
    opts+=("3) Enter a specific timezone")
  else
    opts+=("2) Enter a specific timezone")
  fi

  for o in "${opts[@]}"; do echo "  ${o}"; done

  local default_n="1"
  [[ -n "${keep_n}" ]] && default_n="${keep_n}"

  local choice
  read -r -p "  Choice [${default_n}]: " choice </dev/tty
  choice="${choice:-${default_n}}"

  case "${choice}" in
    1)
      printf '%s\n' "${detected_tz}"
      ;;
    "${keep_n}")
      printf '%s\n' "${configured_tz}"
      ;;
    *)
      local custom_tz
      read -r -p "  Enter IANA timezone (e.g. America/New_York): " custom_tz </dev/tty
      printf '%s\n' "${custom_tz:-${detected_tz}}"
      ;;
  esac
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
    # Allow git clone into an existing empty directory
    if [[ ! -d "${NIKOS_HOME}" ]] || [[ -n "$(ls -A "${NIKOS_HOME}" 2>/dev/null)" ]]; then
      echo "ERROR: ${NIKOS_HOME} exists but is not a git checkout. Move or remove that directory, then rerun the installer." >&2
      exit 1
    fi
  fi

  # A fresh install clones the default branch first. Both the repo sync helpers
  # and the tag list live inside the clone, so the release to install cannot be
  # resolved until it exists.
  if [[ ! -d "${NIKOS_HOME}/.git" ]]; then
    if _can_use_dialog; then
      dialog --title "NikOS ${NIKOS_VERSION}" \
        --infobox "Cloning NikOS repo to ${NIKOS_HOME}..." 5 72 || true
    else
      echo "Cloning NikOS repo to ${NIKOS_HOME}..."
    fi
    _logfile "Cloning repo from ${REPO_URL} to ${NIKOS_HOME}"
    if _can_use_dialog; then
      if git clone --recurse-submodules "${REPO_URL}" "${NIKOS_HOME}" >> "${INSTALL_LOG}" 2>&1; then
        _logfile "Repo cloned OK"
      else
        clone_rc=$?
        _show_logged_command_failure "Failed to clone NikOS repository." "${clone_rc}"
        exit "${clone_rc}"
      fi
    else
      if git clone --recurse-submodules "${REPO_URL}" "${NIKOS_HOME}"; then
        _logfile "Repo cloned OK"
      else
        clone_rc=$?
        echo "ERROR: Failed to clone NikOS repository. See log: ${INSTALL_LOG}" >&2
        exit "${clone_rc}"
      fi
    fi
  fi

  if ! _source_repo_sync_helpers; then
    echo "ERROR: Repo sync helpers not found (${REPO_SYNC_HELPERS_REL}) in ${NIKOS_HOME} or ${SCRIPT_DIR}." >&2
    echo "Move or remove ${NIKOS_HOME} so the installer can re-clone it, or rerun with --dev to use the current checkout." >&2
    exit 1
  fi

  # An explicit --ref/NIKOS_REPO_REF wins; otherwise install the latest release.
  if [[ -z "${TARGET_REPO_REF}" ]]; then
    TARGET_REPO_REF="$(_resolve_release_ref "${REPO_URL}" "${NIKOS_HOME}")"
    if [[ -z "${TARGET_REPO_REF}" ]]; then
      echo "ERROR: No NikOS release tag could be found on ${REPO_URL} or in ${NIKOS_HOME}." >&2
      echo "Check network access, or pick a ref explicitly with --ref, or rerun with --dev." >&2
      exit 1
    fi
    echo "Latest NikOS release: ${TARGET_REPO_REF}"
  fi
  _logfile "Target repo ref: ${TARGET_REPO_REF}"

  if _can_use_dialog; then
    dialog --title "NikOS ${NIKOS_VERSION}" \
      --infobox "Updating NikOS repo at ${NIKOS_HOME} to ${TARGET_REPO_REF}..." 5 72 || true
  else
    echo "Updating NikOS repo at ${NIKOS_HOME} to ${TARGET_REPO_REF}..."
  fi
  _logfile "Syncing repo at ${NIKOS_HOME} to ${TARGET_REPO_REF}"

  update_rc=0
  if _can_use_dialog; then
    _sync_repo_to_ref "${TARGET_REPO_REF}" "nikos-install-autostash" >> "${INSTALL_LOG}" 2>&1 || update_rc=$?
  else
    _sync_repo_to_ref "${TARGET_REPO_REF}" "nikos-install-autostash" || update_rc=$?
  fi
  if [[ "${update_rc}" -ne 0 ]]; then
    case "${update_rc}" in
      1)
        update_message="Updates were applied, but local changes did not reapply cleanly. Resolve the git conflicts in ${NIKOS_HOME}, then rerun the installer or 'nikos update'."
        ;;
      2)
        update_message="Failed to move ${NIKOS_HOME} to ${TARGET_REPO_REF}. Review the git output, resolve the issue, then rerun the installer or 'nikos update'."
        ;;
      3)
        update_message="Failed to update NikOS submodules in ${NIKOS_HOME}. Review the git output, resolve the issue, then rerun the installer or 'nikos update'."
        ;;
      *)
        update_message="Failed to update NikOS repo at ${NIKOS_HOME}. Review the git output, then rerun the installer or 'nikos update'."
        ;;
    esac
    if _can_use_dialog; then
      _show_logged_command_failure "${update_message}" "${update_rc}"
    else
      echo "ERROR: ${update_message}" >&2
    fi
    exit "${update_rc}"
  fi

  # The banner so far reported the installer's own version. From here the
  # checkout decides what is actually being installed.
  NIKOS_VERSION="$(cat "${NIKOS_HOME}/VERSION" 2>/dev/null || echo "${NIKOS_VERSION}")"
  _logfile "Installing NikOS ${NIKOS_VERSION} from ${TARGET_REPO_REF}"
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

# Progress rendering library. Optional: without it the installer falls back to
# the plain scrolling view.
_PROGRESS_LIB_LOADED=false
for _progress_lib in "${NIKOS_HOME}/${PROGRESS_LIB_REL}" "${SCRIPT_DIR}/${PROGRESS_LIB_REL}"; do
  if [[ -f "${_progress_lib}" ]]; then
    # shellcheck source=scripts/nikos-progress.sh
    source "${_progress_lib}"
    _PROGRESS_LIB_LOADED=true
    break
  fi
done
unset _progress_lib
[[ "${_PROGRESS_LIB_LOADED}" == "true" ]] || \
  _safe_logfile "[WARNING] ${PROGRESS_LIB_REL} not found; using the plain progress view"

_ensure_ansible_collections

# Bundle selection ─────────────────────────────────────────────────
_select_bundles_dialog() {
  dialog_init
  local result dialog_status
  if result=$(
    dialog --stdout \
      --title "NikOS ${NIKOS_VERSION} — Optional Bundles" \
      --checklist "Space to toggle, Enter to confirm:" \
      "${DIALOG_HEIGHT}" "${DIALOG_WIDTH}" 19 \
      "network"       "Network tools (nmap, wireshark, OpenVPN)"     off \
      "music"         "Music tools (LMMS, Ardour, Audacity)"         off \
      "education"     "Education tools (LibreOffice, draw.io, Anki)" off \
      "neovim"        "Neovim with lazy.nvim starter config"         off \
      "zsh"           "Zsh with Starship prompt"                     off \
      "java"          "OpenJDK 21"                                   off \
      "bun"           "Bun JavaScript runtime"                       off \
      "openclaw"      "OpenClaw LLM gateway CLI"                     off \
      "ollama-models" "Optional Ollama models, about 26 GB"          off \
      "postgres"      "PostgreSQL with pgvector"                     off \
      "redis"         "Redis server and Python client"               off \
      "qdrant"        "Qdrant vector database container"             off \
      "k8s-tools"     "kubectl and Helm"                             off \
      "podman"        "Podman container runtime"                     off \
      "act"           "Run GitHub Actions locally"                   off \
      "fabric"        "Fabric AI pattern CLI"                        off \
      "bitnet"        "BitNet.cpp 1-bit LLM inference"               off \
      "mistral-rs"    "mistral.rs Rust LLM server"                   off \
      "monitoring"    "Netdata monitoring dashboard"                 off
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
  echo ""
  echo "Dev environment:"
  read -r -p "  Install Neovim? [y/N] " opt_neovim </dev/tty
  read -r -p "  Install Zsh + Starship? [y/N] " opt_zsh </dev/tty
  read -r -p "  Install Java 21? [y/N] " opt_java </dev/tty
  read -r -p "  Install Bun? [y/N] " opt_bun </dev/tty
  echo ""
  echo "LLM tools:"
  read -r -p "  Install OpenClaw? [y/N] " opt_openclaw </dev/tty
  read -r -p "  Pre-pull optional Ollama models? (~26 GB) [y/N] " opt_ollama_models </dev/tty
  read -r -p "  Install BitNet.cpp? [y/N] " opt_bitnet </dev/tty
  read -r -p "  Install mistral.rs? [y/N] " opt_mistral_rs </dev/tty
  echo ""
  echo "Databases:"
  read -r -p "  Install PostgreSQL + pgvector? [y/N] " opt_postgres </dev/tty
  read -r -p "  Install Redis? [y/N] " opt_redis </dev/tty
  read -r -p "  Install Qdrant? [y/N] " opt_qdrant </dev/tty
  echo ""
  echo "Containers / Kubernetes:"
  read -r -p "  Install kubectl + Helm? [y/N] " opt_k8s_tools </dev/tty
  read -r -p "  Install Podman? [y/N] " opt_podman </dev/tty
  read -r -p "  Install act? [y/N] " opt_act </dev/tty
  echo ""
  echo "Monitoring:"
  read -r -p "  Install Netdata? [y/N] " opt_monitoring </dev/tty
  read -r -p "  Install Fabric AI pattern CLI? [y/N] " opt_fabric </dev/tty
  [[ "${opt_network,,}"   == "y" ]] && _selected+=("network")
  [[ "${opt_music,,}"     == "y" ]] && _selected+=("music")
  [[ "${opt_education,,}" == "y" ]] && _selected+=("education")
  [[ "${opt_neovim,,}" == "y" ]] && _selected+=("neovim")
  [[ "${opt_zsh,,}" == "y" ]] && _selected+=("zsh")
  [[ "${opt_java,,}" == "y" ]] && _selected+=("java")
  [[ "${opt_bun,,}" == "y" ]] && _selected+=("bun")
  [[ "${opt_openclaw,,}" == "y" ]] && _selected+=("openclaw")
  [[ "${opt_ollama_models,,}" == "y" ]] && _selected+=("ollama-models")
  [[ "${opt_bitnet,,}" == "y" ]] && _selected+=("bitnet")
  [[ "${opt_mistral_rs,,}" == "y" ]] && _selected+=("mistral-rs")
  [[ "${opt_postgres,,}" == "y" ]] && _selected+=("postgres")
  [[ "${opt_redis,,}" == "y" ]] && _selected+=("redis")
  [[ "${opt_qdrant,,}" == "y" ]] && _selected+=("qdrant")
  [[ "${opt_k8s_tools,,}" == "y" ]] && _selected+=("k8s-tools")
  [[ "${opt_podman,,}" == "y" ]] && _selected+=("podman")
  [[ "${opt_act,,}" == "y" ]] && _selected+=("act")
  [[ "${opt_monitoring,,}" == "y" ]] && _selected+=("monitoring")
  [[ "${opt_fabric,,}" == "y" ]] && _selected+=("fabric")
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

# Timezone ─────────────────────────────────────────────────────────
_detected_tz=$(_detect_system_timezone)
_configured_tz=$(_get_configured_timezone)

if [[ "${_USE_DIALOG}" == "true" ]] && check_if_dialog_installed 2>/dev/null; then
  if ! _chosen_tz=$(_select_timezone_dialog "${_detected_tz}" "${_configured_tz}"); then
    echo "Installer canceled during timezone selection." >&2
    exit 130
  fi
else
  _chosen_tz=$(_select_timezone_plain "${_detected_tz}" "${_configured_tz}")
fi

_set_timezone_in_local_vars "${_chosen_tz}"
_logfile "Timezone: ${_chosen_tz} (detected: ${_detected_tz}, was: ${_configured_tz:-unset})"

# Build ansible tag args ───────────────────────────────────────────
SKIP_TAGS=""
for _bundle in network music education; do
  if ! printf '%s\n' "${SELECTED_BUNDLES[@]}" | grep -qx "${_bundle}"; then
    SKIP_TAGS="${SKIP_TAGS},${_bundle}"
  fi
done

EXPLICIT_OPTIONAL_TAGS=""
for _bundle in neovim java bun redis postgres qdrant k8s-tools podman zsh act fabric bitnet mistral-rs monitoring ollama-models openclaw; do
  if printf '%s\n' "${SELECTED_BUNDLES[@]}" | grep -qx "${_bundle}"; then
    EXPLICIT_OPTIONAL_TAGS="${EXPLICIT_OPTIONAL_TAGS},${_bundle}"
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

_persist_skip_tags "${SKIP_TAGS#,}"
_logfile "Selected bundles: ${SELECTED_BUNDLES[*]:-none}"
_logfile "Selected AI tools: ${SELECTED_AI_TOOLS[*]:-none}"
_logfile "Skip tags: ${SKIP_TAGS#,}"
_logfile "Explicit optional tags: ${EXPLICIT_OPTIONAL_TAGS#,}"

# Run the playbook from local clone ───────────────────────────────
_playbook_rc=0
_ansible_rc=0
_tee_rc=0
_pipe_status=()

if _can_use_dialog; then
  print_info "Running NikOS ${NIKOS_VERSION} playbook..."
  dialog_init
  if ! _become_pass=$(_collect_become_password_dialog); then
    echo "Installer canceled at sudo password prompt." >&2
    exit 130
  fi
  _create_become_password_file "${_become_pass}"
  unset _become_pass
  PLAY_OPTS=(-i "${NIKOS_HOME}/inventory/local" "${NIKOS_HOME}/site.yml")
  PLAY_OPTS+=(--become-password-file "${BECOME_PASSWORD_FILE}")
  [[ -n "${SKIP_TAGS}" ]] && PLAY_OPTS+=(--skip-tags "${SKIP_TAGS#,}")
  _logfile "Playbook: ansible-playbook ${PLAY_OPTS[*]}"
  _logfile "--- ansible-playbook output start ---"
  set +e
  _run_playbook_dialog "NikOS ${NIKOS_VERSION} — Installing" "${PLAY_OPTS[@]}"
  _ansible_rc=$?
  set -e
else
  echo "Running NikOS ${NIKOS_VERSION} playbook..."
  PLAY_OPTS=(-i "${NIKOS_HOME}/inventory/local" "${NIKOS_HOME}/site.yml" --ask-become-pass)
  [[ -n "${SKIP_TAGS}" ]] && PLAY_OPTS+=(--skip-tags "${SKIP_TAGS#,}")
  _logfile "Playbook: ansible-playbook ${PLAY_OPTS[*]}"
  _logfile "--- ansible-playbook output start ---"
  set +e
  (
    cd "${NIKOS_HOME}"
    ANSIBLE_CONFIG="${NIKOS_HOME}/ansible.cfg" ansible-playbook "${PLAY_OPTS[@]}"
  ) 2>&1 | tee -a "${INSTALL_LOG}"
  _pipe_status=("${PIPESTATUS[@]}")
  set -e
  _ansible_rc=${_pipe_status[0]}
  _tee_rc=${_pipe_status[1]}
fi

# _tee_rc guards the optional bundles too: once the install log is unwritable
# the run is already in a fatal state, so there is nothing to gain from
# starting another playbook that cannot be recorded either.
if [[ "${_ansible_rc}" -eq 0 && "${_tee_rc}" -eq 0 && -n "${EXPLICIT_OPTIONAL_TAGS}" ]]; then
  print_info "Installing selected optional bundles: ${EXPLICIT_OPTIONAL_TAGS#,}"
  OPTIONAL_PLAY_OPTS=(-i "${NIKOS_HOME}/inventory/local" "${NIKOS_HOME}/site.yml" --tags "${EXPLICIT_OPTIONAL_TAGS#,}")
  if [[ -n "${BECOME_PASSWORD_FILE:-}" ]]; then
    OPTIONAL_PLAY_OPTS+=(--become-password-file "${BECOME_PASSWORD_FILE}")
  else
    OPTIONAL_PLAY_OPTS+=(--ask-become-pass)
  fi
  _logfile "Optional playbook: ansible-playbook ${OPTIONAL_PLAY_OPTS[*]}"
  _logfile "--- optional playbook output start ---"
  set +e
  if _can_use_dialog; then
    _run_playbook_dialog "NikOS ${NIKOS_VERSION} — Optional Bundles" "${OPTIONAL_PLAY_OPTS[@]}"
    _ansible_rc=$?
  else
    (
      cd "${NIKOS_HOME}"
      ANSIBLE_CONFIG="${NIKOS_HOME}/ansible.cfg" ansible-playbook "${OPTIONAL_PLAY_OPTS[@]}"
    ) 2>&1 | tee -a "${INSTALL_LOG}"
    _pipe_status=("${PIPESTATUS[@]}")
    _ansible_rc=${_pipe_status[0]}
    _tee_rc=${_pipe_status[1]}
  fi
  set -e
  _logfile "--- optional playbook output end ---"
fi

_cleanup_become_password_file

if [[ "${_ansible_rc}" -ne 0 ]]; then
  _playbook_rc="${_ansible_rc}"
elif [[ "${_tee_rc}" -ne 0 ]]; then
  echo "ERROR: Failed to write installer log to ${INSTALL_LOG}." >&2
  _safe_logfile "[FAILED] tee could not write ${INSTALL_LOG} (rc=${_tee_rc})"
  _playbook_rc="${_tee_rc}"
elif [[ -n "${_dialog_rc:-}" ]] && [[ "${_dialog_rc}" -ne 0 ]]; then
  echo "WARNING: dialog UI exited with rc=${_dialog_rc}; playbook output may be incomplete." >&2
  _safe_logfile "[WARNING] dialog exited with rc=${_dialog_rc}"
fi

_logfile "--- ansible-playbook output end ---"

_install_summary "${_playbook_rc}"

echo ""
if [[ "${_playbook_rc}" -eq 0 ]]; then
  echo "NikOS ${NIKOS_VERSION} installation complete."
  _session_next_step
else
  echo "NikOS ${NIKOS_VERSION} installation finished with errors (rc=${_playbook_rc})."
  echo "Review the log above or: cat ${INSTALL_LOG}"
  exit "${_playbook_rc}"
fi
