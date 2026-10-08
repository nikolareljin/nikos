#!/usr/bin/env bash
# SCRIPT: ollama_bridge_files.sh
# DESCRIPTION: Run the Ollama forwarder's file-writing tasks as root on a stock Ubuntu image.
# USAGE: bash tests/machine/ollama_bridge_files.sh [image]
# EXIT_CODES: 0 every file written; 1 a task failed; 3 cannot run here (no Docker)
# ----------------------------------------------------
# The unit tests write to temporary directories and never meet a real
# filesystem. This runs the tasks from roles/ai-stack/tasks/bridge.yml that
# create directories and copy files, as root, on a stock image, which is where
# "Destination directory /usr/local/libexec does not exist" was found. The
# systemd and apt tasks are left out: the image has no systemd.
set -euo pipefail

image="${1:-ubuntu:24.04}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v docker >/dev/null 2>&1 || { echo "SKIP: no docker" >&2; exit 3; }
work="$(mktemp -d)"
trap 'rm -rf -- "${work:?}"' EXIT

python3 - "${root}" "${work}" <<'PY'
import sys, yaml
from pathlib import Path
root, work = Path(sys.argv[1]), Path(sys.argv[2])
tasks = yaml.safe_load((root / "roles/ai-stack/tasks/bridge.yml").read_text())
keep = [{k: v for k, v in t.items() if k != "become"} for t in tasks
        if {"ansible.builtin.copy", "ansible.builtin.file"} & set(t)]
play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
         "vars": {"nikos_ollama_host": "127.0.0.1:11434", "ai_stack_bridge_addr": "172.17.0.1",
                  "ai_stack_bridge_port": "11434", "ai_stack_bridge_wanted": True},
         "tasks": keep}]
(work / "play.yml").write_text(yaml.safe_dump(play))
PY

docker run --rm -v "${root}/roles/ai-stack/files:/p/files:ro" -v "${work}/play.yml:/p/play.yml:ro" "${image}" bash -euo pipefail -c '
  apt-get update -qq >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ansible-core >/dev/null 2>&1
  cd /p
  ANSIBLE_NOCOLOR=1 ansible-playbook -i localhost, play.yml | grep -E "fatal|ok=" || true
  for f in /usr/local/libexec/nikos-ollama-bridge-check /etc/nikos/ollama-bridge.nft \
           /etc/systemd/system/nikos-ollama-bridge.socket /etc/systemd/system/nikos-ollama-bridge.service \
           /etc/systemd/system/nikos-ollama-bridge-filter.service; do
    [ -f "$f" ] || { echo "FAIL: $f was not written"; exit 1; }
  done
  [ -x /usr/local/libexec/nikos-ollama-bridge-check ] || { echo "FAIL: the check is not executable"; exit 1; }
  echo "ok: every forwarder file written on a stock image"
'
