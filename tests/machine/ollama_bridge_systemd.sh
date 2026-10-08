#!/usr/bin/env bash
# SCRIPT: ollama_bridge_systemd.sh
# DESCRIPTION: Run the Ollama forwarder tasks for real under systemd on a stock Ubuntu: install, answer, refuse, re-run, remove.
# USAGE: bash tests/machine/ollama_bridge_systemd.sh [image]
# EXIT_CODES: 0 proved; 1 a step failed; 3 cannot run here (no Docker)
# ----------------------------------------------------
# The other checks write files or load the nftables rule by hand. This boots
# the image with systemd as PID 1 and runs roles/ai-stack/tasks/bridge.yml as
# the play does (apt, unit files, systemctl):
#   A. with a LAN at 172.20.0.0/24 (inside 172.16.0.0/12) the play refuses,
#      names it, and installs nothing;
#   B. with the LAN at 10.99.0.0/24 it installs; through the forwarder,
#      from_docker (behind docker0) gets the stand-in Ollama and from_lan, with
#      a route to the bridge address, gets nothing;
#   C. a second run changes nothing;
#   D. nikos_ollama_bridge=off removes every unit and file; nothing listens.
# A stand-in docker CLI names docker0 as Docker's bridge; there is no Docker
# daemon in the image.
set -euo pipefail

image="${1:-ubuntu:24.04}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v docker >/dev/null 2>&1 || { echo "SKIP: no docker" >&2; exit 3; }
name="nikos-bridge-systemd-$$"
net="nikos-bridge-systemd-net-$$"
cleanup() {
  docker rm -f "${name}" >/dev/null 2>&1 || true
  docker network rm "${net}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Outside 172.16.0.0/12, so the container's own address is not in the range.
docker network create --subnet 10.250.43.0/24 "${net}" >/dev/null
docker run -d --name "${name}" --network "${net}" --privileged --cgroupns=host \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw --tmpfs /run --tmpfs /run/lock \
  -v "${root}:/nikos:ro" "${image}" bash -c '
    apt-get update -qq >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq systemd ansible-core iproute2 curl python3 >/dev/null 2>&1
    exec /lib/systemd/systemd' >/dev/null

inside() { docker exec "${name}" bash -euo pipefail -c "$1"; }
for _ in $(seq 1 120); do
  state="$(docker exec "${name}" systemctl is-system-running 2>/dev/null || true)"
  [[ "${state}" == running || "${state}" == degraded ]] && break
  sleep 2
done
[[ "${state:-}" == running || "${state:-}" == degraded ]] || { echo "FAIL: systemd did not come up (${state:-none})"; exit 1; }

inside '
  ip netns add from_docker; ip netns add from_lan
  ip link add docker0 type veth peer name d1; ip link set d1 netns from_docker
  ip link add lan0 type veth peer name l1; ip link set l1 netns from_lan
  ip addr add 172.17.0.1/16 dev docker0; ip link set docker0 up
  ip addr add 172.20.0.1/24 dev lan0;    ip link set lan0 up
  ip -n from_docker addr add 172.17.0.2/16 dev d1; ip -n from_docker link set d1 up
  ip -n from_lan addr add 172.20.0.2/24 dev l1;   ip -n from_lan link set l1 up
  ip -n from_lan route add 172.17.0.1/32 via 172.20.0.1
  # A stand-in docker CLI: one bridge network, named docker0.
  printf "%s\n" "#!/bin/sh" "case \"\$*\" in *\"network ls\"*) echo aaaaaaaaaaaa ;; *\"network inspect\"*) echo docker0 ;; esac" > /usr/local/bin/docker
  chmod +x /usr/local/bin/docker
  # The stand-in Ollama, on loopback only.
  systemd-run --unit fake-ollama python3 -m http.server 11434 --bind 127.0.0.1 >/dev/null
'

play() { # play <nikos_ollama_bridge>
  inside "cat > /tmp/play.yml <<YML
- hosts: localhost
  connection: local
  gather_facts: false
  vars:
    nikos_ollama_mode: local
    nikos_ollama_host: 127.0.0.1:11434
    nikos_ollama_bridge: \"$1\"
  tasks:
    # As site.yml runs it: inside the role, so the role's files/ is searched.
    - ansible.builtin.include_role:
        name: ai-stack
        tasks_from: bridge.yml
YML
  cd /tmp && ANSIBLE_NOCOLOR=1 ANSIBLE_ROLES_PATH=/nikos/roles ansible-playbook -i localhost, play.yml"
}
ask() { inside "ip netns exec $1 curl -s -m 5 -o /dev/null -w '%{http_code}' http://172.17.0.1:11434/ || true"; }

# A. A LAN inside the range: refused, nothing installed.
if refused="$(play 172.17.0.1 2>&1)"; then echo "FAIL: a LAN in 172.16.0.0/12 did not refuse the forwarder"; exit 1; fi
echo "${refused}" | grep -q "Not running the Ollama forwarder: lan0 172.20.0.1/24" \
  || { echo "${refused}" | tail -10; echo "FAIL: the refusal did not name the LAN"; exit 1; }
inside '[ ! -e /etc/systemd/system/nikos-ollama-bridge.socket ]' || { echo "FAIL: a refused run installed the socket"; exit 1; }
echo "A: a LAN in the range refuses the forwarder, nothing installed"

# B. The LAN moves outside the range; it keeps a route to the bridge address.
inside '
  ip addr flush dev lan0; ip addr add 10.99.0.1/24 dev lan0
  ip -n from_lan addr flush dev l1; ip -n from_lan addr add 10.99.0.2/24 dev l1
  ip -n from_lan route add 172.17.0.1/32 via 10.99.0.1
'
out="$(play 172.17.0.1 2>&1)" || { echo "${out}" | tail -30; echo "FAIL: the install run failed"; exit 1; }
echo "${out}" | grep -E "^localhost" || true
inside 'systemctl is-active nikos-ollama-bridge.socket nikos-ollama-bridge-filter.service' \
  || { echo "FAIL: the forwarder units are not active"; exit 1; }
docker_code="$(ask from_docker)"; lan_code="$(ask from_lan)"
echo "B: through the forwarder: docker0 -> ${docker_code}, lan0 -> ${lan_code:-000}"
[[ "${docker_code}" == 200 ]] || { inside 'journalctl -u nikos-ollama-bridge.service -n 20 --no-pager' || true; echo "FAIL: a container got no answer"; exit 1; }
[[ "${lan_code}" != 200 ]] || { echo "FAIL: a LAN machine in 172.16.0.0/12 got an answer"; exit 1; }

again="$(play 172.17.0.1 2>&1)" || { echo "${again}" | tail -20; echo "FAIL: the second run failed"; exit 1; }
changed="$(echo "${again}" | sed -n 's/.*changed=\([0-9]*\).*/\1/p' | head -1)"
echo "C: second run: changed=${changed}"
[[ "${changed}" == 0 ]] || { echo "${again}" | grep -B1 "changed:" | head -20; echo "FAIL: a second run changed something"; exit 1; }

off="$(play off 2>&1)" || { echo "${off}" | tail -20; echo "FAIL: the run with off failed"; exit 1; }
# shellcheck disable=SC2016  # expanded inside the container
inside 'for f in /etc/systemd/system/nikos-ollama-bridge.socket /etc/systemd/system/nikos-ollama-bridge.service \
           /etc/systemd/system/nikos-ollama-bridge-filter.service /etc/nikos/ollama-bridge.nft \
           /usr/local/libexec/nikos-ollama-bridge-check; do [ ! -e "$f" ] || { echo "left: $f"; exit 1; }; done
    ! ss -Hltn "( sport = :11434 )" | grep -q 172.17.0.1
    ! nft list table inet nikos_ollama_bridge >/dev/null 2>&1' \
  || { echo "FAIL: off left something behind"; exit 1; }
echo "D: off removed every unit and file"
echo "ok: refused a shared range, installed, answered a container, refused the LAN, idempotent, removed by off"
