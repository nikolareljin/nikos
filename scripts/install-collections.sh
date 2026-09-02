#!/usr/bin/env bash
# Install the Ansible collections NikOS needs, and survive Galaxy having a bad
# day.
#
#   scripts/install-collections.sh [requirements.yml]
#
# galaxy.ansible.com fails in two ways that have nothing to do with this
# repository and everything to do with the moment you happened to ask:
#
#   Error when getting available collection versions for community.general
#   (HTTP Code: 504, Message: Gateway Timeout)
#
#   Missing expected 'results' in ansible-galaxy cache: {...}. This may
#   indicate cache corruption (for example, from concurrent ansible-galaxy
#   runs) ... Try running with --clear-response-cache or --no-cache
#
# Both took NikOS's CI red on a commit that changed nothing near them, and both
# would equally have failed somebody's install. --no-cache removes the second
# class outright, and retrying with a backoff covers the first.
set -euo pipefail

REQUIREMENTS="${1:-requirements.yml}"
ATTEMPTS="${NIKOS_GALAXY_ATTEMPTS:-4}"
DELAY="${NIKOS_GALAXY_RETRY_DELAY:-5}"

if [[ ! -f "$REQUIREMENTS" ]]; then
  echo "ERROR: collection requirements not found: $REQUIREMENTS" >&2
  exit 1
fi

# Retrying cannot conjure the tool, and the give-up message below would blame
# Galaxy for something that is plainly local.
if ! command -v ansible-galaxy >/dev/null 2>&1; then
  echo "ERROR: ansible-galaxy is not on PATH. Install ansible-core first." >&2
  exit 1
fi

attempt=1
while :; do
  if ansible-galaxy collection install --no-cache -r "$REQUIREMENTS"; then
    exit 0
  fi

  if (( attempt >= ATTEMPTS )); then
    echo "ERROR: could not install Ansible collections from $REQUIREMENTS after ${ATTEMPTS} attempts." >&2
    echo "       galaxy.ansible.com may be unavailable; this is not a fault in this repository." >&2
    exit 1
  fi

  echo "ansible-galaxy failed (attempt ${attempt}/${ATTEMPTS}); retrying in ${DELAY}s..." >&2
  sleep "$DELAY"
  attempt=$((attempt + 1))
  DELAY=$((DELAY * 2))
done
