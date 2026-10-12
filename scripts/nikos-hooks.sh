#!/usr/bin/env bash
# SCRIPT: nikos-hooks.sh
# DESCRIPTION: Security hooks on this machine: script-helpers per-repository git
#              hooks in your clones (through git-lantern), the machine-wide hooks
#              (opt-in), and one folder that carries the setup to another computer
#              (lantern for git hooks, agentvault for AI tool rules and hooks).
# USAGE: nikos hooks [status|apply|repair|remove|export DIR|import DIR] [options]
#        nikos hooks --global [--uninstall]
# PARAMETERS:
#   status             What is set up (the default): tools, owners, every clone.
#   apply              Set up the hooks in every clone under --root whose origin is
#                      under your owners. Other clones are never changed.
#     --dry-run        Print the plan, change nothing.
#     --batch N        Set up at most N clones this run.
#     --agents LIST    Also the AI agent hooks: claude,codex,gemini,copilot,cursor or all.
#     --only LIST      Only these clones (directory names or paths).
#   repair [--only]    Re-chain clones another tool took over (husky and the like).
#   remove [--agents LIST] [--only LIST]
#                      Take ours out; the hooks that ran before run again.
#   export DIR         Write lantern-hooks.json and agentvault.avbundle into DIR.
#   import DIR         Read them back: owners (only if unset here), the hooks in
#                      every clone of each exported repository, and agentvault.
#   --global           Machine-wide git hooks (global core.hooksPath). Explicit
#                      opt-in: install and update never run it. --uninstall undoes it.
#   --root DIR         Where the clones are (default $NIKOS_HOOKS_ROOT, else ~/Projects).
#   -h, --help         Show this help.
# Exit codes: 0 done, 1 a step failed, 2 bad usage or a missing tool (nothing changed).
set -euo pipefail

NIKOS_HOME="${NIKOS_HOME:-${HOME}/.local/share/nikos}"
ROOT="${NIKOS_HOOKS_ROOT:-${HOME}/Projects}"
LANTERN_FILE="lantern-hooks.json"
VAULT_FILE="agentvault.avbundle"

usage() { sed -n '2,/^# Exit codes/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"; }
die() { echo "nikos hooks: $*" >&2; exit 2; }
info() { echo "$*"; }

# script-helpers to use: the configured home, else the copy NikOS pins.
helpers_home() {
  local home
  home="$(git config --global --get script-helpers.home 2>/dev/null || true)"
  printf '%s\n' "${home:-${NIKOS_HOME}/scripts/script-helpers}"
}

# lantern with the same script-helpers this script reports: without it lantern
# would look for its own vendored copy, which an installed lantern lacks.
run_lantern() { SCRIPT_HELPERS_HOME="$(helpers_home)" lantern "$@"; }

need_lantern() {
  command -v lantern >/dev/null 2>&1 || die "git-lantern is not installed (nikos update installs it)"
  lantern hooks --help >/dev/null 2>&1 || die "this git-lantern has no 'hooks' command; run nikos update"
}

cmd_status() {
  local home owners global
  home="$(helpers_home)"
  owners="$(git config --global --get script-helpers.owners 2>/dev/null || true)"
  global="$(git config --global --get core.hooksPath 2>/dev/null || true)"
  info "script-helpers: ${home} ($(cat "${home}/VERSION" 2>/dev/null || echo "missing"))"
  info "owners:         ${owners:-unset (git config --global script-helpers.owners <user-or-org>)}"
  info "git-lantern:    $(lantern --version 2>/dev/null || echo "not installed")"
  info "agentvault:     $(agentvault version 2>/dev/null | head -n 1 || true)"
  command -v agentvault >/dev/null 2>&1 || info "                not installed"
  info "gitleaks:       $(gitleaks version 2>/dev/null || echo "not installed")"
  info "machine-wide:   ${global:-off (nikos hooks --global)}"
  info ""
  need_lantern
  run_lantern hooks status --root "${ROOT}" "$@"
}

# The options each lantern sub-command takes; anything else is refused before
# lantern runs, so a typo changes nothing.
check_opts() {
  local allowed="$1"; shift
  while [[ $# -gt 0 ]]; do
    case " ${allowed} " in
      *" $1= "*) [[ $# -ge 2 && -n "$2" ]] || die "$1 needs a value"; shift 2 ;;
      *" $1 "*) shift ;;
      *) die "unknown option for this command: $1" ;;
    esac
  done
}

cmd_lantern() {
  local sub="$1"; shift
  case "${sub}" in
    apply)  check_opts "--dry-run --batch= --agents= --only=" "$@" ;;
    repair) check_opts "--only=" "$@" ;;
    remove) check_opts "--agents= --only=" "$@" ;;
    status) check_opts "--only=" "$@" ;;
  esac
  need_lantern
  if [[ "${sub}" == status ]]; then
    cmd_status "$@"
  else
    run_lantern hooks "${sub}" --root "${ROOT}" "$@"
  fi
}

cmd_global() {
  local home script
  [[ $# -eq 0 || ( $# -eq 1 && "$1" == "--uninstall" ) ]] || die "--global takes only --uninstall"
  home="$(helpers_home)"
  script="${home}/scripts/setup-hooks.sh"
  [[ -f "${script}" ]] || die "no setup-hooks.sh in ${home}"
  bash "${script}" --global "$@"
}

cmd_export() {
  local dir="${1:-}" rc=0
  [[ $# -eq 1 && -n "${dir}" ]] || die "export needs one folder: nikos hooks export DIR"
  need_lantern
  mkdir -p "${dir}"
  run_lantern hooks export "${dir}/${LANTERN_FILE}" --root "${ROOT}" || return 1
  if command -v agentvault >/dev/null 2>&1; then
    agentvault export "${dir}/${VAULT_FILE}" || rc=1
  else
    echo "nikos hooks: agentvault not installed; AI tool rules and hooks were not exported" >&2
    rc=1
  fi
  [[ ${rc} -eq 0 ]] && info "exported to ${dir}"
  return "${rc}"
}

cmd_import() {
  local dir="${1:-}" file owners rc=0
  [[ $# -eq 1 && -n "${dir}" ]] || die "import needs one folder: nikos hooks import DIR"
  file="${dir}/${LANTERN_FILE}"
  [[ -f "${file}" ]] || die "no ${LANTERN_FILE} in ${dir}"
  need_lantern
  # The owners travel in the export; set them only where none are configured,
  # never over a value this machine already has.
  if [[ -z "$(git config --global --get script-helpers.owners 2>/dev/null || true)" ]]; then
    owners="$(python3 -I -c 'import json,sys; print(",".join(json.load(open(sys.argv[1])).get("owners") or []))' "${file}")" \
      || die "${file} is not a lantern hooks export"
    [[ -n "${owners}" ]] || die "${file} names no owners; set them: git config --global script-helpers.owners <user-or-org>"
    git config --global script-helpers.owners "${owners}"
    info "owners set to ${owners}"
  fi
  run_lantern hooks import "${file}" --root "${ROOT}" || rc=1
  if [[ -f "${dir}/${VAULT_FILE}" ]]; then
    if command -v agentvault >/dev/null 2>&1; then
      agentvault import "${dir}/${VAULT_FILE}" || rc=1
    else
      echo "nikos hooks: agentvault not installed; ${VAULT_FILE} was not imported" >&2
      rc=1
    fi
  fi
  return "${rc}"
}

main() {
  local args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --root) [[ $# -ge 2 && -n "$2" ]] || die "--root needs a folder"; ROOT="$2"; shift 2 ;;
      --root=*) ROOT="${1#--root=}"; [[ -n "${ROOT}" ]] || die "--root needs a folder"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  set -- "${args[@]+"${args[@]}"}"
  case "${1:-status}" in
    status|apply|repair|remove) local sub="${1:-status}"; [[ $# -gt 0 ]] && shift; cmd_lantern "${sub}" "$@" ;;
    export) shift; cmd_export "$@" ;;
    import) shift; cmd_import "$@" ;;
    --global) shift; cmd_global "$@" ;;
    *) die "unknown command or option: $1 (nikos hooks --help)" ;;
  esac
}

main "$@"
