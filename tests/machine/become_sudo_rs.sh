#!/usr/bin/env bash
# SCRIPT: become_sudo_rs.sh
# DESCRIPTION: Run site.yml's Gathering Facts under become through real sudo-rs with a password.
# USAGE: NIKOS_MACHINE_SUDO_RS=1 bash tests/machine/become_sudo_rs.sh
# EXIT_CODES: 0 become worked through sudo-rs; 1 it did not; 3 cannot run here
# ----------------------------------------------------
# tests/test_become_sudo_rs.py drives the become plugin with a fake sudo. This
# installs the sudo-rs package, which becomes /usr/bin/sudo as on an Ubuntu
# 26.04 desktop, adds a user with a password, and runs the playbook's first
# play as that user with --become-password-file, the way `nikos update` does.
# It changes the machine (a package, a user), so it runs only with
# NIKOS_MACHINE_SUDO_RS=1, which the ubuntu-26.04 CI leg sets. The caller's
# sudo must not ask for a password.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
user="nikos-become-test"
work=""

skip() { echo "SKIP: $*" >&2; exit 3; }
fail() { echo "FAIL: $*" >&2; exit 1; }

[[ "${NIKOS_MACHINE_SUDO_RS:-}" == "1" ]] || skip "set NIKOS_MACHINE_SUDO_RS=1 to install sudo-rs and add a user on this machine"
command -v apt-get >/dev/null 2>&1 || skip "no apt-get"
command -v ansible-playbook >/dev/null 2>&1 || skip "no ansible-playbook"
sudo -n true >/dev/null 2>&1 || skip "sudo asks for a password here"

cleanup() {
  sudo -n userdel -r "${user}" >/dev/null 2>&1 || true
  [[ -z "${work}" ]] || sudo -n rm -rf -- "${work}"
  # Put the classic sudo back in front when it is installed, so later steps
  # see the sudo they started with.
  if [[ -x /usr/bin/sudo.ws ]]; then
    sudo -n update-alternatives --set sudo /usr/bin/sudo.ws >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! command -v sudo-rs >/dev/null 2>&1; then
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y sudo-rs >/dev/null || skip "sudo-rs could not be installed"
fi
# The package registers itself as the sudo alternative at a higher priority
# than classic sudo. If a machine has it installed but not selected, select it.
if [[ "$(readlink -f "$(command -v sudo)")" != "$(readlink -f "$(command -v sudo-rs)")" ]]; then
  sudo -n update-alternatives --set sudo "$(readlink -f "$(command -v sudo-rs)")" >/dev/null 2>&1 || true
fi
[[ "$(readlink -f "$(command -v sudo)")" == "$(readlink -f "$(command -v sudo-rs)")" ]] ||
  skip "sudo is not sudo-rs: $(readlink -f "$(command -v sudo)")"
echo "sudo: $(sudo --version 2>&1 | head -1)"
echo "ansible: $(ansible-playbook --version | head -1)"

password="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"
id "${user}" >/dev/null 2>&1 || sudo -n useradd -m -s /bin/bash -G sudo "${user}"
printf '%s:%s\n' "${user}" "${password}" | sudo -n chpasswd

work="$(mktemp -d)"
cp -r "${root}" "${work}/nikos"
printf '%s\n' "${password}" > "${work}/pw"
printf 'not-the-password\n' > "${work}/wrong"
chmod 600 "${work}/pw" "${work}/wrong"
sudo -n chown -R "${user}:" "${work}"
chmod 755 "${work}"

# as_user <password file> [ansible-playbook args...]: the first play of site.yml,
# which gathers facts under become, with no task selected.
as_user() {
  local pw="$1"; shift
  sudo -n -u "${user}" -H env -C "${work}/nikos" \
    ANSIBLE_CONFIG="${work}/nikos/ansible.cfg" ANSIBLE_NOCOLOR=1 ANSIBLE_FORCE_COLOR=0 \
    "$@" ansible-playbook site.yml -i inventory/local --check --tags no_such_tag \
    --become-password-file "${pw}"
}

sudo -n -u "${user}" -H env -C "${work}/nikos" bash scripts/install-collections.sh requirements.yml >/dev/null

echo "--- builtin sudo plugin (information only; passes from ansible-core 2.20.11)"
out="$(as_user "${work}/pw" ANSIBLE_BECOME_METHOD=sudo 2>&1)" && echo "builtin: ok" || echo "builtin: $(grep -m1 -o 'Timed out waiting for become[^"]*' <<<"${out}" || echo "failed")"

echo "--- nikos_sudo, right password"
out="$(as_user "${work}/pw" 2>&1)" || fail "Gathering Facts under become failed:${out}"
grep -q '^ok: \[localhost\]' <<<"${out}" || fail "no ok task in:${out}"

echo "--- nikos_sudo, wrong password"
if out="$(as_user "${work}/wrong" 2>&1)"; then fail "a wrong password was accepted:${out}"; fi
grep -q 'Timed out waiting for become' <<<"${out}" && fail "a wrong password waited for the timeout:${out}"

echo "OK: become through sudo-rs with a password"
