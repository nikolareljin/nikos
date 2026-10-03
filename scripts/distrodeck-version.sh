#!/usr/bin/env bash
# distrodeck-version.sh - turn distrodeck_version into the ref to check out.
#
#   scripts/distrodeck-version.sh <version|latest> [commit]
#
# An explicit version is a pin. Without a commit it is printed unchanged. With
# one (distrodeck_commit from vars/versions.yml) the remote tag is read and
# must point at that commit, which is then printed; a tag that moved, or a
# version overridden without its commit, exits 3 with the reason on stderr.
# "latest" (or empty) asks the remote for its tags and prints the highest
# plain X.Y.Z one; distrodeck tags carry no "v" prefix. Exits 1 with nothing
# on stdout when the remote cannot be read, so the caller can keep an
# existing clone.
set -euo pipefail

want="${1:-latest}"
commit="${2:-}"
url="${DISTRODECK_REPO_URL:-https://github.com/nikolareljin/distrodeck.git}"

if [[ "${want}" != "latest" ]]; then
  if [[ -z "${commit}" ]]; then
    printf '%s\n' "${want}"
    exit 0
  fi
  refs="$(GIT_TERMINAL_PROMPT=0 timeout 30 git ls-remote "${url}" "refs/tags/${want}" "refs/tags/${want}^{}" 2>/dev/null)" || exit 1
  # An annotated tag lists the tag object and then the peeled commit (^{});
  # the last line is the commit either way.
  have="$(printf '%s\n' "${refs}" | awk 'NF { sha = $1 } END { print sha }')"
  if [[ -z "${have}" ]]; then
    echo "distrodeck tag ${want} does not exist at ${url}." >&2
    exit 3
  fi
  if [[ "${have}" != "${commit}" ]]; then
    echo "distrodeck tag ${want} is commit ${have}, not the pinned ${commit}." >&2
    echo "Set distrodeck_version and distrodeck_commit together (vars/local.yml)." >&2
    exit 3
  fi
  printf '%s\n' "${commit}"
  exit 0
fi

refs="$(GIT_TERMINAL_PROMPT=0 timeout 30 git ls-remote --tags --refs "${url}" 2>/dev/null)" || exit 1
tag="$(printf '%s\n' "${refs}" | awk '{ sub("^refs/tags/", "", $2); print $2 }' |
  grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)"
[[ -n "${tag}" ]] || exit 1
printf '%s\n' "${tag}"
