#!/usr/bin/env bash
# distrodeck-version.sh - turn distrodeck_version into a release tag.
#
#   scripts/distrodeck-version.sh <version|latest>
#
# An explicit version is printed unchanged: it is a pin. "latest" (or empty)
# asks the remote for its tags and prints the highest plain X.Y.Z one;
# distrodeck tags carry no "v" prefix. Exits 1 with nothing on stdout when the
# remote cannot be read, so the caller can keep an existing clone.
set -euo pipefail

want="${1:-latest}"
url="${DISTRODECK_REPO_URL:-https://github.com/nikolareljin/distrodeck.git}"

if [[ "${want}" != "latest" ]]; then
  printf '%s\n' "${want}"
  exit 0
fi

refs="$(GIT_TERMINAL_PROMPT=0 timeout 30 git ls-remote --tags --refs "${url}" 2>/dev/null)" || exit 1
tag="$(printf '%s\n' "${refs}" | awk '{ sub("^refs/tags/", "", $2); print $2 }' |
  grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)"
[[ -n "${tag}" ]] || exit 1
printf '%s\n' "${tag}"
