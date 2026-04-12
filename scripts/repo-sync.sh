#!/usr/bin/env bash

_repo_sync_print_info() {
  if declare -F print_info >/dev/null; then
    print_info "$@"
  else
    echo "$@"
  fi
}

_repo_sync_print_stash_recovery() {
  local stash_ref="$1"

  [[ -z "${stash_ref}" ]] && return 0

  _repo_sync_print_info "Your local changes were preserved in ${stash_ref}."
  _repo_sync_print_info "Recover them with:"
  _repo_sync_print_info "  git -C ${NIKOS_HOME} stash apply ${stash_ref}"
  _repo_sync_print_info "or:"
  _repo_sync_print_info "  git -C ${NIKOS_HOME} stash pop ${stash_ref}"
}

_migrate_local_vars() {
  local main_vars_path="${NIKOS_HOME}/${MAIN_VARS_REL}"
  local local_vars_path="${NIKOS_HOME}/${LOCAL_VARS_REL}"

  if [[ -f "${local_vars_path}" ]]; then
    return 0
  fi

  if ! git -C "${NIKOS_HOME}" diff --quiet -- "${MAIN_VARS_REL}" || \
     ! git -C "${NIKOS_HOME}" diff --cached --quiet -- "${MAIN_VARS_REL}"; then
    _repo_sync_print_info "Migrating local vars/main.yml customizations to vars/local.yml..."
    cp "${main_vars_path}" "${local_vars_path}"
    git -C "${NIKOS_HOME}" restore --staged --worktree --source=HEAD -- "${MAIN_VARS_REL}"
  fi

  return 0
}

_pull_repo_updates() {
  local stash_label="${1:-nikos-update-autostash}"
  local stash_ref=""

  _migrate_local_vars

  if ! git -C "${NIKOS_HOME}" diff --quiet || \
     ! git -C "${NIKOS_HOME}" diff --cached --quiet || \
     [[ -n "$(git -C "${NIKOS_HOME}" ls-files --others --exclude-standard)" ]]; then
    _repo_sync_print_info "Temporarily stashing local changes before pulling updates..."
    git -C "${NIKOS_HOME}" stash push --include-untracked --message "${stash_label}" >/dev/null
    stash_ref="stash@{0}"
  fi

  if ! git -C "${NIKOS_HOME}" pull --ff-only; then
    _repo_sync_print_info "Failed to pull updates in ${NIKOS_HOME}; repository was not updated."
    _repo_sync_print_stash_recovery "${stash_ref}"
    return 2
  fi

  if ! git -C "${NIKOS_HOME}" submodule update --init --recursive; then
    _repo_sync_print_info "Failed to update git submodules in ${NIKOS_HOME}; resolve the issue before continuing."
    _repo_sync_print_stash_recovery "${stash_ref}"
    return 3
  fi

  if [[ -n "${stash_ref}" ]]; then
    _repo_sync_print_info "Re-applying local changes..."
    if ! git -C "${NIKOS_HOME}" stash pop --index "${stash_ref}" >/dev/null; then
      _repo_sync_print_info "Local changes did not reapply cleanly; resolve git conflicts in ${NIKOS_HOME}."
      return 1
    fi
  fi

  return 0
}
