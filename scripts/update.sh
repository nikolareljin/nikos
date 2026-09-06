#!/usr/bin/env bash
# SCRIPT: update.sh
# DESCRIPTION: Sync and initialize pinned submodule revisions from this repository.
# USAGE: ./scripts/update.sh
# PARAMETERS: No required parameters.
# EXAMPLE: ./scripts/update.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
submodule_path="scripts/script-helpers"

git -C "$repo_root" submodule sync --recursive
git -C "$repo_root" submodule update --init --recursive "$submodule_path"
