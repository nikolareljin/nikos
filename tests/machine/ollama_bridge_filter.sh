#!/usr/bin/env bash
# SCRIPT: ollama_bridge_filter.sh
# DESCRIPTION: Prove the Ollama forwarder's interface filter: the bridge address answers a container's network and not a LAN in the same address range.
# USAGE: bash tests/machine/ollama_bridge_filter.sh <rendered ollama-bridge.nft>
# EXIT_CODES: 0 proved; 1 the filter let the LAN through, or blocked Docker; 2 usage; 3 cannot run here (no Docker, or no privileged containers)
# ----------------------------------------------------
# Inside one privileged container, two network namespaces stand for the two
# sides: from_docker, behind an interface named docker0, and from_lan, behind
# lan0 with an address INSIDE 172.16.0.0/12 (172.20.0.2), the case an address
# filter cannot tell apart. A listener on the bridge address answers both
# without the filter; with it, only from_docker gets an answer. The filter is
# the file the play writes, rendered by the test suite.
set -euo pipefail

nft_file="${1:-}"
[[ -f "${nft_file}" ]] || { echo "usage: $0 <rendered ollama-bridge.nft>" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "SKIP: no docker" >&2; exit 3; }

image="debian:bookworm-slim"
# The container's own interface must not sit in 172.17.0.0/16 (Docker's
# default network would put it there, and the test's replies would leave by
# it), so it gets a network of its own, outside 172.16.0.0/12, removed after.
net="nikos-bridge-filter-test-$$"
docker network create --subnet 10.250.42.0/24 "${net}" >/dev/null
trap 'docker network rm "${net}" >/dev/null 2>&1 || true' EXIT
docker run --rm --privileged --network "${net}" -v "$(cd "$(dirname "${nft_file}")" && pwd)/$(basename "${nft_file}"):/rules.nft:ro" \
  "${image}" bash -euo pipefail -c '
  apt-get update -qq >/dev/null && apt-get install -y -qq nftables iproute2 curl python3 >/dev/null
  ip netns add from_docker; ip netns add from_lan
  ip link add docker0 type veth peer name d1; ip link set d1 netns from_docker
  ip link add lan0 type veth peer name l1; ip link set l1 netns from_lan
  ip addr add 172.17.0.1/16 dev docker0; ip link set docker0 up
  ip addr add 172.20.0.1/24 dev lan0;    ip link set lan0 up
  ip -n from_docker addr add 172.17.0.2/16 dev d1; ip -n from_docker link set d1 up; ip -n from_docker link set lo up
  ip -n from_lan addr add 172.20.0.2/24 dev l1;   ip -n from_lan link set l1 up;   ip -n from_lan link set lo up
  # The LAN machine has a route to the bridge address through this host.
  ip -n from_lan route add 172.17.0.1/32 via 172.20.0.1
  python3 -m http.server 11434 --bind 172.17.0.1 >/dev/null 2>&1 &
  sleep 1
  ask() { ip netns exec "$1" curl -s -m 3 -o /dev/null -w "%{http_code}" http://172.17.0.1:11434/ || true; }
  without_docker="$(ask from_docker)"; without_lan="$(ask from_lan)"
  nft -f /rules.nft
  with_docker="$(ask from_docker)"; with_lan="$(ask from_lan)"
  echo "without the filter: docker0 -> ${without_docker}, lan0 -> ${without_lan}"
  echo "with the filter:    docker0 -> ${with_docker}, lan0 -> ${with_lan:-000}"
  [[ "${without_docker}" == 200 && "${without_lan}" == 200 ]] || { echo "FAIL: the test network does not work without the filter"; exit 1; }
  [[ "${with_docker}" == 200 ]] || { echo "FAIL: the filter blocked Docker"; exit 1; }
  [[ "${with_lan}" != 200 ]] || { echo "FAIL: the filter let a LAN machine in 172.16.0.0/12 through"; exit 1; }
  echo "ok: only the Docker side reaches the bridge address"
'
