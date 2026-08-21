#!/usr/bin/env bash
# Apply the NikOS wallpaper to every backdrop xfdesktop registered for this user.
#
# xfdesktop only creates the per-connector backdrop properties
# (monitorHDMI-A-0, monitorDisplayPort-2, ...) once an Xfce session is running,
# and it seeds them from the system defaults it can see at that moment. The
# playbook runs before any session exists, so it cannot reach those properties.
# This script runs from /etc/xdg/autostart at login and does the work there.
#
# Every monitor gets the same artwork. Monitors in portrait orientation get the
# portrait cut of it. The image is Scaled rather than Zoomed, so nothing is
# cropped, and the backdrop colour is set to #2e3440 - the flat base colour of
# both wallpapers - so whatever the aspect ratio does not cover reads as part
# of the image.
#
# The marker file records the monitor layout the wallpaper was last applied to.
# An unchanged layout means there is nothing to do. A changed layout (a monitor
# added, removed or rotated) re-applies, but only over backdrops still holding a
# NikOS wallpaper, so a wallpaper the user picked themselves is left alone.
set -euo pipefail

WALLPAPER="${NIKOS_WALLPAPER:-/usr/share/nikos/wallpaper.png}"
WALLPAPER_VERTICAL="${NIKOS_WALLPAPER_VERTICAL:-/usr/share/nikos/wallpaper-vertical.png}"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/nikos"
MARKER="${STATE_DIR}/wallpaper-applied"

# image-style int values: 0=None 1=Centered 2=Tiled 3=Stretched 4=Scaled 5=Zoomed
IMAGE_STYLE=4
# color-style int values: 0=Solid 1=Horizontal gradient 2=Vertical gradient 3=Transparent
COLOR_STYLE=0
# #2e3440 as GdkRGBA components, the colour xfdesktop stores in rgba1.
RGBA1=(0.180392 0.203922 0.250980 1.000000)

if [[ ! -f "${WALLPAPER}" ]]; then
  exit 0
fi

if ! command -v xfconf-query >/dev/null 2>&1; then
  exit 0
fi

# -- Monitor orientation -----------------------------------------------------
# `xrandr --listmonitors` prints one row per active monitor:
#   0: +DisplayPort-2 3440/797x1440/334+0+0  DisplayPort-2
# The last field is the connector name xfdesktop uses in its property paths.
# Rotation is already reflected in the geometry, so a portrait monitor reports
# its height as the larger number whichever way it was turned.
declare -A MONITOR_VERTICAL=()

monitor_rows() {
  command -v xrandr >/dev/null 2>&1 || return 0
  xrandr --listmonitors 2>/dev/null | tail -n +2
}

collect_monitor_orientation() {
  local index geometry connector width height rest
  while read -r index _ geometry connector rest; do
    [[ "${index}" == *: ]] || continue
    [[ -n "${connector}" ]] || continue
    width="${geometry%%/*}"
    rest="${geometry#*x}"
    height="${rest%%/*}"
    [[ "${width}" =~ ^[0-9]+$ && "${height}" =~ ^[0-9]+$ ]] || continue
    if (( height > width )); then
      MONITOR_VERTICAL["${connector}"]=1
    else
      MONITOR_VERTICAL["${connector}"]=0
    fi
  done < <(monitor_rows)
}

monitor_signature() {
  local connector
  {
    for connector in "${!MONITOR_VERTICAL[@]}"; do
      printf '%s:%s\n' "${connector}" "${MONITOR_VERTICAL[${connector}]}"
    done
  } | sort | tr '\n' ' '
}

image_for_monitor() {
  local connector="$1"
  if [[ "${MONITOR_VERTICAL[${connector}]:-0}" == "1" && -f "${WALLPAPER_VERTICAL}" ]]; then
    printf '%s\n' "${WALLPAPER_VERTICAL}"
  else
    printf '%s\n' "${WALLPAPER}"
  fi
}

# Set a property, creating it with the given type when it does not exist yet.
set_int() {
  local prop="$1" value="$2"
  xfconf-query -c xfce4-desktop -p "${prop}" -s "${value}" 2>/dev/null && return 0
  xfconf-query -c xfce4-desktop -p "${prop}" --create --type int -s "${value}" 2>/dev/null || true
}

set_rgba() {
  local prop="$1"
  xfconf-query -c xfce4-desktop -p "${prop}" \
    -s "${RGBA1[0]}" -s "${RGBA1[1]}" -s "${RGBA1[2]}" -s "${RGBA1[3]}" 2>/dev/null && return 0
  xfconf-query -c xfce4-desktop -p "${prop}" --create \
    --type double --type double --type double --type double \
    -s "${RGBA1[0]}" -s "${RGBA1[1]}" -s "${RGBA1[2]}" -s "${RGBA1[3]}" 2>/dev/null || true
}

# The layout comes from xrandr, which needs no wait, so decide whether there is
# anything to do before waiting on xfdesktop. On the usual login, where nothing
# has changed since the last run, this exits immediately.
collect_monitor_orientation
signature="$(monitor_signature)"
# Without xrandr there is no layout to compare. Record a constant instead, so a
# second login still short-circuits rather than reapplying every time.
[[ -n "${signature}" ]] || signature="unknown-layout"

previous=""
if [[ -f "${MARKER}" ]]; then
  previous="$(cat "${MARKER}" 2>/dev/null || true)"
fi

if [[ -n "${previous}" && "${previous}" == "${signature}" ]]; then
  exit 0
fi

# xfdesktop registers its backdrop properties a moment after the session starts.
for _ in $(seq 1 30); do
  if xfconf-query -c xfce4-desktop -l 2>/dev/null | grep -qE '/(last-image|image-path)$'; then
    break
  fi
  sleep 1
done

# Without a usable marker this is the first run after an install: claim every
# backdrop. With one, the layout changed, so only NikOS-owned backdrops move.
first_run=1
if [[ -n "${previous}" ]]; then
  first_run=0
fi

applied=0
while read -r prop; do
  [[ -n "${prop}" ]] || continue
  base="${prop%/*}"
  connector="${prop#/backdrop/screen0/monitor}"
  connector="${connector%%/*}"
  image="$(image_for_monitor "${connector}")"

  if (( first_run == 0 )); then
    current="$(xfconf-query -c xfce4-desktop -p "${prop}" 2>/dev/null || true)"
    if [[ "${current}" != "${WALLPAPER}" && "${current}" != "${WALLPAPER_VERTICAL}" ]]; then
      continue
    fi
    if [[ "${current}" == "${image}" ]]; then
      applied=1
      continue
    fi
  fi

  xfconf-query -c xfce4-desktop -p "${prop}" -s "${image}" 2>/dev/null || continue
  set_int "${base}/image-style" "${IMAGE_STYLE}"
  set_int "${base}/color-style" "${COLOR_STYLE}"
  set_rgba "${base}/rgba1"
  applied=1
done < <(xfconf-query -c xfce4-desktop -l 2>/dev/null | grep -E '/(last-image|image-path)$' || true)

if [[ "${applied}" -ne 1 ]]; then
  exit 0
fi

mkdir -p "${STATE_DIR}"
printf '%s\n' "${signature}" > "${MARKER}"
