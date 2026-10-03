#!/usr/bin/env bash
# verify-key-fingerprint.sh - refuse an apt signing key that is not the pinned one.
#
#   scripts/verify-key-fingerprint.sh <key-file> <fingerprint>...
#
# Reads the key file (armored or binary) with `gpg --show-keys`, without
# importing it anywhere, and compares the set of primary key fingerprints with
# the pinned ones from vars/versions.yml. Any key missing, any extra key, or
# a file gpg cannot read exits 1 with the difference on stderr, so the key is
# never installed. Exits 2 on bad usage.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <key-file> <fingerprint>..." >&2
  exit 2
fi
key="$1"
shift

if [[ ! -r "${key}" ]]; then
  echo "verify-key-fingerprint: cannot read ${key}" >&2
  exit 1
fi

# A throwaway GNUPGHOME: --show-keys imports nothing, but gpg still wants a
# home directory, and root's must not be created or touched by this check.
gnupghome="$(mktemp -d)"
trap 'rm -rf "${gnupghome}"' EXIT

listing="$(GNUPGHOME="${gnupghome}" gpg --batch --show-keys --with-colons "${key}" 2>/dev/null)" || {
  echo "verify-key-fingerprint: gpg could not read ${key} as an OpenPGP key" >&2
  exit 1
}

# The fpr record right after each pub record is that primary key's fingerprint;
# fpr records after sub records belong to subkeys and are not compared.
have="$(printf '%s\n' "${listing}" | awk -F: '
  $1 == "pub" { want_fpr = 1; next }
  $1 == "sub" { want_fpr = 0; next }
  $1 == "fpr" && want_fpr { print toupper($10); want_fpr = 0 }
' | sort -u)"
want="$(printf '%s\n' "$@" | tr '[:lower:]' '[:upper:]' | tr -d ' ' | sort -u)"

if [[ -z "${have}" ]]; then
  echo "verify-key-fingerprint: no public key in ${key}" >&2
  exit 1
fi
if [[ "${have}" != "${want}" ]]; then
  echo "verify-key-fingerprint: ${key} does not hold the pinned keys" >&2
  echo "  pinned: $(printf '%s\n' "${want}" | paste -sd " ")" >&2
  echo "  found:  $(printf '%s\n' "${have}" | paste -sd " ")" >&2
  exit 1
fi
echo "verify-key-fingerprint: ${key} matches the pinned fingerprints"
