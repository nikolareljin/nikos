#!/usr/bin/env bash
# SCRIPT: clean-caches.sh
# DESCRIPTION: Free disk by removing caches nothing is using: old Docker build
#              cache, dangling Docker images, node_modules in idle projects,
#              and unused package-manager cache entries.
# USAGE: nikos clean [options]   (or scripts/clean-caches.sh [options])
# PARAMETERS:
#   --apply            Remove what is listed. Without it nothing is removed.
#   --yes              Do not ask before removing (needed with no terminal).
#   --keep-days N      Docker build cache and package cache entries used in the
#                      last N days are kept (default 7).
#   --idle-days N      node_modules is removed only in a git repository with no
#                      commit for N days and no uncommitted change (default 30).
#   --projects DIR     Where the repositories are (default ~/Projects).
#   --only LIST        Comma list of: docker, node, packages (default all).
#   --unused-images    Also remove tagged Docker images no container uses and
#                      created more than --keep-days ago. Off by default: they
#                      are downloaded again on the next start.
#   -h, --help         Show this help.
#
# NEVER removed, whatever the options: Docker volumes (they hold databases,
# indexes and models, also of projects not being worked on), containers,
# networks, virtual environments, build output, and anything git tracks.
# The script calls no `docker volume` and no `docker system prune` command.
set -euo pipefail

APPLY=false
YES=false
KEEP_DAYS=7
IDLE_DAYS=30
PROJECTS="${HOME}/Projects"
ONLY="docker,node,packages"
UNUSED_IMAGES=false

# The comment block at the top, up to the first line that is not a comment.
usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; }

need_number() { [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "$1 needs a whole number of days" >&2; exit 2; }; }
need_value() { [[ -n "${2:-}" && "${2:-}" != -* ]] || { echo "$1 needs a value (see --help)" >&2; exit 2; }; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true ;;
    --yes) YES=true ;;
    --keep-days) need_number "$1" "${2:-}"; KEEP_DAYS="$2"; shift ;;
    --idle-days) need_number "$1" "${2:-}"; IDLE_DAYS="$2"; shift ;;
    --projects) [[ -d "${2:-}" ]] || { echo "--projects needs a directory" >&2; exit 2; }; PROJECTS="$2"; shift ;;
    --only) need_value "$1" "${2:-}"; ONLY="$2"; shift ;;
    --unused-images) UNUSED_IMAGES=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
for part in ${ONLY//,/ }; do
  case "$part" in docker|node|packages) ;; *) echo "--only takes docker, node, packages; not: $part" >&2; exit 2 ;; esac
done
wants() { [[ ",${ONLY}," == *",$1,"* ]]; }

# What is planned, as "<what>|<size>|<command or path>", shown before anything runs.
PLAN=()
plan() { PLAN+=("$1|$2|$3"); }
human() { du -sh -- "$1" 2>/dev/null | cut -f1; }

# --- Docker -------------------------------------------------------------------
docker_up() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }
if wants docker; then
  if docker_up; then
    build="$(docker system df --format '{{.Type}}|{{.Reclaimable}}' 2>/dev/null | sed -n 's/^Build Cache|//p')"
    # Every builder: a docker-container builder (multi-arch builds) keeps its own
    # cache, which `docker builder prune` (the default builder) never sees.
    builders="$(docker buildx ls --format '{{.Name}}' 2>/dev/null | sed 's/\*$//' | sort -u)" || builders=""
    if [[ -n "$builders" ]]; then
      for b in $builders; do
        plan "Docker build cache of builder $b, not used in ${KEEP_DAYS} days" "up to ${build:-?}" \
          "docker buildx prune --builder $b -f --filter until=$((KEEP_DAYS * 24))h"
        build="(above)"
      done
    else
      plan "Docker build cache not used in ${KEEP_DAYS} days" "up to ${build:-?}" \
        "docker builder prune -f --filter until=$((KEEP_DAYS * 24))h"
    fi
    dangling="$(docker image ls -q -f dangling=true | wc -l | tr -d ' ')"
    plan "Docker images with no tag (${dangling})" "-" "docker image prune -f"
    if $UNUSED_IMAGES; then
      plan "Docker images no container uses, older than ${KEEP_DAYS} days" "-" \
        "docker image prune -a -f --filter until=$((KEEP_DAYS * 24))h"
    fi
  else
    echo "Docker: not running or not reachable; skipped."
  fi
fi

# --- node_modules in idle repositories ----------------------------------------
# A repository is idle when its last commit is older than --idle-days, it has
# no uncommitted change, and nothing runs from it now: no process of this user
# has its working directory inside it, and no running container bind-mounts it
# (a service started a month ago and left running has no recent commit). Only a node_modules beside a package.json is removed
# (npm install puts it back), never one git tracks, and never one that belongs
# to a nested repository other than the one being looked at.
in_use() { # in_use <repo>: a running process or container uses it
  local r="$1" p
  # A process uses the repository it runs in: its working directory is inside.
  # (Not the other way round: a shell in ~/Projects uses none of them.)
  for p in ${IN_USE_CWD[@]+"${IN_USE_CWD[@]}"}; do
    [[ "$p" == "$r" || "$p" == "$r"/* ]] && return 0
  done
  # A bind mount reaches everything under its source, so a container that
  # mounts a parent directory may use this repository too.
  for p in ${IN_USE_MOUNT[@]+"${IN_USE_MOUNT[@]}"}; do
    [[ "$p" == "$r" || "$p" == "$r"/* || "$r" == "$p"/* ]] && return 0
  done
  return 1
}
if wants node; then
  now="$(date +%s)"
  IN_USE_CWD=() IN_USE_MOUNT=()
  proc="${CLEAN_PROC_DIR:-/proc}"   # a test seam
  if [[ -d "$proc" ]]; then
    for p in "$proc"/[0-9]*; do
      c="$(readlink "$p/cwd" 2>/dev/null)" || continue
      [[ -n "$c" ]] && IN_USE_CWD+=("$c")
    done
  elif command -v lsof >/dev/null 2>&1; then
    # macOS has no /proc: lsof lists each process's working directory.
    while IFS= read -r c; do [[ -n "$c" ]] && IN_USE_CWD+=("$c"); done \
      < <(lsof -a -d cwd -u "$(id -u)" -Fn 2>/dev/null | sed -n 's/^n//p')
  else
    echo "Cannot tell which repositories processes run in (no /proc, no lsof): node_modules is left alone." >&2
    IDLE_DAYS=999999
  fi
  if docker_up; then
    while IFS= read -r m; do [[ -n "$m" && "$m" != / ]] && IN_USE_MOUNT+=("$m"); done < <(docker ps -q | xargs -r docker inspect \
      -f '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}{{"\n"}}{{end}}{{end}}' 2>/dev/null)
  fi
  while IFS= read -r -d '' gitdir; do
    repo="$(dirname "$gitdir")"
    last="$(git -C "$repo" log -1 --format=%ct 2>/dev/null)" || continue
    [[ -n "$last" ]] || continue
    (( now - last > IDLE_DAYS * 86400 )) || continue
    [[ -z "$(git -C "$repo" status --porcelain 2>/dev/null)" ]] || continue
    repo="$(cd "$repo" && pwd -P)"
    if in_use "$repo"; then
      echo "Kept: $(basename "$repo") is in use (a process or container runs from it)."
      continue
    fi
    while IFS= read -r -d '' nm; do
      [[ -L "$nm" ]] && continue
      [[ -f "$(dirname "$nm")/package.json" ]] || continue
      [[ "$(git -C "$(dirname "$nm")" rev-parse --show-toplevel 2>/dev/null)" == "$(cd "$repo" && pwd -P)" ]] || continue
      [[ -z "$(git -C "$repo" ls-files -- "${nm#"$repo"/}" | head -n 1)" ]] || continue
      plan "node_modules, $(basename "$repo") idle since $(date -d "@$last" +%F 2>/dev/null || date -r "$last" +%F)" "$(human "$nm")" "$nm"
    done < <(find "$repo" -name node_modules -type d -prune -print0 2>/dev/null)
  done < <(find "$PROJECTS" -maxdepth 3 -name .git -print0 2>/dev/null)
fi

# --- package-manager caches: only what nothing uses ---------------------------
# npm's garbage collection and pnpm's store prune can remove what an install
# running at the same moment has written but not yet indexed. While one runs,
# those two are skipped; uv locks its cache, and pip's step only takes files
# unused for days.
installing() { # installing <name>...: a process with that exact name runs
  local n
  for n in "$@"; do pgrep -x "$n" >/dev/null 2>&1 && return 0; done
  return 1
}
if wants packages; then
  if command -v uv >/dev/null 2>&1; then
    plan "uv cache: entries no environment uses" "of $(human "$(uv cache dir 2>/dev/null)")" "uv cache prune"
  fi
  if installing npm pnpm yarn; then
    echo "npm and pnpm caches: skipped, an npm, pnpm or yarn process is running."
  else
    if command -v pnpm >/dev/null 2>&1; then
      plan "pnpm store: packages no project references" "-" "pnpm store prune"
    fi
    if command -v npm >/dev/null 2>&1; then
      plan "npm cache: garbage and unreferenced data" "of $(human "${HOME}/.npm/_cacache")" "npm cache verify"
    fi
  fi
  pip_cache="${HOME}/.cache/pip"
  if [[ -d "$pip_cache" ]]; then
    plan "pip cache: files not used in ${KEEP_DAYS} days" \
      "$(find "$pip_cache" -type f -atime +"$KEEP_DAYS" -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {printf "%.1fG", s/1073741824}')" \
      "find $pip_cache -type f -atime +$KEEP_DAYS -delete"
  fi
fi

# --- show, ask, run ------------------------------------------------------------
if [[ ${#PLAN[@]} -eq 0 ]]; then
  echo "Nothing to clean."
  exit 0
fi
echo "Kept, always: Docker volumes, containers, virtual environments, build output, tracked files."
echo
printf '%-62s %10s\n' "WHAT" "SIZE"
for item in "${PLAN[@]}"; do
  IFS='|' read -r what size _ <<<"$item"
  printf '%-62s %10s\n' "$what" "$size"
done
echo
before="$(df -Pk / | awk 'NR==2 {print $4}')"
if ! $APPLY; then
  echo "Dry run: nothing was removed. Run with --apply to remove the above."
  exit 0
fi
if ! $YES; then
  if [[ ! -t 0 ]]; then
    echo "No terminal to ask on: pass --yes to remove without asking." >&2
    exit 1
  fi
  read -r -p "Remove the above? [y/N] " answer
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]] || { echo "Nothing removed."; exit 0; }
fi

failed=0
for item in "${PLAN[@]}"; do
  IFS='|' read -r what _ action <<<"$item"
  echo "-> $what"
  if [[ "$action" == /* ]]; then
    # A path: only a node_modules directory, checked again right before.
    if [[ "$(basename "$action")" == node_modules && -d "$action" && ! -L "$action" ]]; then
      rm -rf -- "$action" || failed=1
    else
      echo "   skipped: not a node_modules directory any more" >&2
    fi
  else
    # shellcheck disable=SC2086  # the planned command, split into words on purpose
    $action >/dev/null || { echo "   failed: $action" >&2; failed=1; }
  fi
done
after="$(df -Pk / | awk 'NR==2 {print $4}')"
echo
echo "Freed on /: $(( (after - before) / 1048576 )) GB ($(df -h / | awk 'NR==2 {print $5}') used now)."
exit "$failed"
