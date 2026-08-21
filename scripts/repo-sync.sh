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
  local quoted_nikos_home

  [[ -z "${stash_ref}" ]] && return 0

  printf -v quoted_nikos_home '%q' "${NIKOS_HOME}"

  _repo_sync_print_info "Your local changes were preserved in ${stash_ref}."
  _repo_sync_print_info "Recover them with:"
  _repo_sync_print_info "  git -C ${quoted_nikos_home} stash apply ${stash_ref}"
  _repo_sync_print_info "or:"
  _repo_sync_print_info "  git -C ${quoted_nikos_home} stash pop ${stash_ref}"
}

# Read candidate tag names on stdin, print the highest release version.
# Prints nothing when no line is a bare X.Y.Z release tag.
_pick_latest_semver() {
  { grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' || true; } | sort -V | tail -n 1
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

# Highest release tag published by a remote. Empty when the remote is
# unreachable or publishes no release tags.
_latest_semver_tag() {
  local url="${1:-${REPO_URL:-}}"

  [[ -z "${url}" ]] && return 0

  { git ls-remote --tags --refs "${url}" 2>/dev/null || true; } \
    | awk '{print $2}' \
    | sed 's#^refs/tags/##' \
    | _pick_latest_semver
}

# Highest release tag already present in a local checkout. Used when the
# remote cannot be reached.
_latest_local_semver_tag() {
  local repo_dir="${1:-${NIKOS_HOME:-}}"

  [[ -z "${repo_dir}" ]] && return 0

  { git -C "${repo_dir}" tag --list 2>/dev/null || true; } | _pick_latest_semver
}

# The release to install: newest tag the remote publishes, falling back to the
# newest tag already fetched into a local checkout when the remote is
# unreachable. Empty when neither source offers a release tag.
_resolve_release_ref() {
  local url="${1:-${REPO_URL:-}}"
  local repo_dir="${2:-${NIKOS_HOME:-}}"
  local tag=""

  tag="$(_latest_semver_tag "${url}")"
  if [[ -z "${tag}" && -n "${repo_dir}" && -d "${repo_dir}/.git" ]]; then
    tag="$(_latest_local_semver_tag "${repo_dir}")"
  fi

  printf '%s\n' "${tag}"
}

# The ref `nikos update` should move to, printed on stdout. Empty means
# "stay where you are".
#
# A branch install keeps its branch, so an update never drags a newer branch
# back to an older release. A tag install advances to the newest release, and
# only when that release is actually newer.
_resolve_update_ref() {
  local url="${1:-${REPO_URL:-}}"
  local repo_dir="${2:-${NIKOS_HOME:-}}"
  local branch="" current="" latest=""

  branch="$(git -C "${repo_dir}" branch --show-current 2>/dev/null || true)"
  if [[ -n "${branch}" ]]; then
    printf '%s\n' "${branch}"
    return 0
  fi

  latest="$(_resolve_release_ref "${url}" "${repo_dir}")"
  [[ -z "${latest}" ]] && return 0

  current="$(git -C "${repo_dir}" describe --tags --exact-match 2>/dev/null || true)"
  # Only a release tag is comparable; anything else (a floating tag, a bare
  # commit) is treated as "not a release" and upgraded.
  if [[ "${current}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    if [[ "$(printf '%s\n%s\n' "${current}" "${latest}" | sort -V | tail -n 1)" == "${current}" ]]; then
      return 0
    fi
  fi

  printf '%s\n' "${latest}"
}

# Move the checkout onto a branch, remote branch or tag. Tags land on a
# detached HEAD by design.
_repo_switch_to_ref() {
  local target_ref="$1"
  local current_branch=""

  current_branch="$(git -C "${NIKOS_HOME}" branch --show-current 2>/dev/null || true)"
  if [[ -n "${current_branch}" && "${current_branch}" == "${target_ref}" ]]; then
    return 0
  fi

  _repo_sync_print_info "Switching ${NIKOS_HOME} to ${target_ref}..."
  if git -C "${NIKOS_HOME}" show-ref --verify --quiet "refs/heads/${target_ref}"; then
    git -C "${NIKOS_HOME}" switch "${target_ref}"
  elif git -C "${NIKOS_HOME}" show-ref --verify --quiet "refs/remotes/origin/${target_ref}"; then
    git -C "${NIKOS_HOME}" switch --track "origin/${target_ref}"
  elif git -C "${NIKOS_HOME}" show-ref --verify --quiet "refs/tags/${target_ref}"; then
    git -C "${NIKOS_HOME}" switch --detach "${target_ref}"
  else
    _repo_sync_print_info "Requested NikOS ref '${target_ref}' was not found in ${NIKOS_HOME}."
    _repo_sync_print_info "Set NIKOS_REPO_REF to an existing branch or tag, or run the installer with --dev to use the current checkout."
    return 1
  fi
}

# Bring NIKOS_HOME to target_ref, preserving local work.
#
# Fetch happens before the switch: a ref cannot be resolved before it has been
# fetched, and fetch is the only network step that is safe on a detached HEAD.
# The fast-forward is skipped unless HEAD is on a branch with an upstream,
# which is what a tag install always leaves behind.
#
# An empty target_ref means "stay on whatever ref is checked out".
#
# Returns: 0 ok, 1 stash did not reapply, 2 fetch or switch failed,
#          3 submodules failed, 4 could not stash local changes.
_sync_repo_to_ref() {
  local target_ref="${1:-}"
  local stash_label="${2:-nikos-update-autostash}"
  local stash_ref=""
  local current_branch=""

  _migrate_local_vars

  if ! git -C "${NIKOS_HOME}" diff --quiet || \
     ! git -C "${NIKOS_HOME}" diff --cached --quiet || \
     [[ -n "$(git -C "${NIKOS_HOME}" ls-files --others --exclude-standard)" ]]; then
    _repo_sync_print_info "Temporarily stashing local changes before updating..."
    if ! git -C "${NIKOS_HOME}" stash push --include-untracked --message "${stash_label}" >/dev/null; then
      _repo_sync_print_info "Failed to stash local changes in ${NIKOS_HOME}; repository was not updated."
      return 4
    fi
    stash_ref="stash@{0}"
  fi

  if ! git -C "${NIKOS_HOME}" fetch --prune --tags --force origin; then
    _repo_sync_print_info "Failed to fetch updates in ${NIKOS_HOME}; repository was not updated."
    _repo_sync_print_stash_recovery "${stash_ref}"
    return 2
  fi

  if [[ -n "${target_ref}" ]]; then
    if ! _repo_switch_to_ref "${target_ref}"; then
      _repo_sync_print_stash_recovery "${stash_ref}"
      return 2
    fi
  fi

  current_branch="$(git -C "${NIKOS_HOME}" branch --show-current 2>/dev/null || true)"
  if [[ -n "${current_branch}" ]] && \
     git -C "${NIKOS_HOME}" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    if ! git -C "${NIKOS_HOME}" merge --ff-only '@{u}'; then
      _repo_sync_print_info "Failed to fast-forward ${current_branch} in ${NIKOS_HOME}; repository was not updated."
      _repo_sync_print_stash_recovery "${stash_ref}"
      return 2
    fi
  fi

  if ! git -C "${NIKOS_HOME}" submodule update --init --recursive; then
    _repo_sync_print_info "Failed to update git submodules in ${NIKOS_HOME}; resolve the issue before continuing."
    _repo_sync_print_stash_recovery "${stash_ref}"
    return 3
  fi

  if [[ -n "${stash_ref}" ]]; then
    _repo_sync_print_info "Re-applying local changes..."
    if ! git -C "${NIKOS_HOME}" stash pop --index "${stash_ref}"; then
      _repo_sync_print_info "Local changes did not reapply cleanly; resolve git conflicts in ${NIKOS_HOME}."
      _repo_sync_print_stash_recovery "${stash_ref}"
      return 1
    fi
  fi

  return 0
}

# Update the checkout in place, without changing which ref it is on.
_pull_repo_updates() {
  _sync_repo_to_ref "" "${1:-nikos-update-autostash}"
}
