#!/usr/bin/env bash
# SCRIPT: ollama_bridge_filter.sh
# DESCRIPTION: Prove the Ollama forwarder's interface filter: the bridge address answers a container's network and not a LAN in the same address range.
# USAGE: bash tests/machine/ollama_bridge_filter.sh <rendered ollama-bridge.nft>
# EXIT_CODES: 0 proved; 1 the filter let the LAN through, or blocked Docker; 2 usage; 3 cannot run here (no Docker, or no privileged containers)
# ----------------------------------------------------
# Inside one privileged container, two network namespaces stand for the two
# sides: from_docker, behind an interface named docker0, and from_lan, behind
# lan0 with an address INSIDE 172.16.0.0/12 (172.20.0.2), the case an address
# filter cannot tell apart. Two more stand for a VPN (wg0, peer 172.16.99.9,
# as a WireGuard VPN does) and a libvirt/LXC bridge named br-x in the range that
# Docker did not create. A listener on the bridge address answers all of them
# without the filter; with it, only from_docker gets an answer. The filter is
# the file the play writes, rendered by the test suite; its Docker set is
# filled with docker0 as nikos-ollama-bridge-refresh would.
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
  ip netns add from_docker; ip netns add from_lan; ip netns add from_vpn; ip netns add from_brx; ip netns add from_pool; ip netns add from_lan192
  ip link add docker0 type veth peer name d1; ip link set d1 netns from_docker
  ip link add lan0 type veth peer name l1; ip link set l1 netns from_lan
  ip link add wg0 type veth peer name v1; ip link set v1 netns from_vpn
  ip link add br-x type veth peer name b1; ip link set b1 netns from_brx
  # A Docker network from the 192.168 pool (as git-pulse got 192.168.16.0/20),
  # and a home LAN in 192.168 on an interface Docker does not own.
  ip link add br-pool type veth peer name p1; ip link set p1 netns from_pool
  ip link add eth9 type veth peer name e1; ip link set e1 netns from_lan192
  ip addr add 192.168.16.1/20 dev br-pool; ip link set br-pool up
  ip addr add 192.168.1.1/24 dev eth9; ip link set eth9 up
  ip -n from_pool addr add 192.168.16.2/20 dev p1; ip -n from_pool link set p1 up; ip -n from_pool route add 172.17.0.1/32 via 192.168.16.1
  ip -n from_lan192 addr add 192.168.1.50/24 dev e1; ip -n from_lan192 link set e1 up; ip -n from_lan192 route add 172.17.0.1/32 via 192.168.1.1
  ip addr add 172.16.0.1/32 dev wg0; ip link set wg0 up; ip route add 172.16.99.9/32 dev wg0
  ip addr add 172.16.50.1/24 dev br-x; ip link set br-x up
  ip -n from_vpn addr add 172.16.99.9/32 dev v1; ip -n from_vpn link set v1 up; ip -n from_vpn link set lo up
  ip -n from_vpn route add 172.16.0.1/32 dev v1; ip -n from_vpn route add 172.17.0.1/32 via 172.16.0.1
  ip -n from_brx addr add 172.16.50.2/24 dev b1; ip -n from_brx link set b1 up; ip -n from_brx link set lo up
  ip -n from_brx route add 172.17.0.1/32 via 172.16.50.1
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
  without_vpn="$(ask from_vpn)"; without_brx="$(ask from_brx)"
  without_lan192="$(ask from_lan192)"
  nft -f /rules.nft
  nft add element inet nikos_ollama_bridge docker_ifs "{ \"docker0\", \"br-pool\" }"
  with_docker="$(ask from_docker)"; with_lan="$(ask from_lan)"
  with_vpn="$(ask from_vpn)"; with_brx="$(ask from_brx)"
  with_pool="$(ask from_pool)"; with_lan192="$(ask from_lan192)"
  echo "192.168 pool bridge -> ${with_pool}, 192.168 LAN -> ${with_lan192:-000}"
  echo "without the filter: docker0 -> ${without_docker}, lan0 -> ${without_lan}, wg0 -> ${without_vpn}, br-x -> ${without_brx}"
  echo "with the filter:    docker0 -> ${with_docker}, lan0 -> ${with_lan:-000}, wg0 -> ${with_vpn:-000}, br-x -> ${with_brx:-000}"
  for v in "${without_docker}" "${without_lan}" "${without_vpn}" "${without_brx}" "${without_lan192}"; do
    [[ "${v}" == 200 ]] || { echo "FAIL: the test network does not work without the filter"; exit 1; }
  done
  [[ "${with_docker}" == 200 ]] || { echo "FAIL: the filter blocked Docker"; exit 1; }
  [[ "${with_lan}" != 200 ]] || { echo "FAIL: the filter let a LAN machine in 172.16.0.0/12 through"; exit 1; }
  [[ "${with_vpn}" != 200 ]] || { echo "FAIL: the filter let a VPN peer (172.16.99.9 on wg0) through"; exit 1; }
  [[ "${with_pool}" == 200 ]] || { echo "FAIL: the filter blocked a Docker bridge from the 192.168 pool"; exit 1; }
  [[ "${with_lan192}" != 200 ]] || { echo "FAIL: the filter let a 192.168 LAN on eth9 through"; exit 1; }
  [[ "${with_brx}" != 200 ]] || { echo "FAIL: the filter let a non-Docker br-x through"; exit 1; }
  echo "ok: only the Docker side reaches the bridge address"
'
