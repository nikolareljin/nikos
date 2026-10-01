#!/usr/bin/env bash
# shellcheck disable=SC2034  # NIKOS_SELECTED_TOOLS is the return channel
# nikos-tools.sh - pick distrodeck tools by category. Sourced by install.sh and
# scripts/nikos.
#
# NikOS keeps no tool catalog of its own. It asks the distrodeck it is about to
# use for one:
#
#   distrodeck install-tools --list-catalog --format tsv
#   category_id<TAB>category_label<TAB>tool<TAB>label<TAB>opt_in(0|1)<TAB>installed(0|1)
#
# A distrodeck that predates that flag makes nikos_tools_catalog fail, and the
# caller skips the screen with one line rather than failing the install.
#
# Selections are returned in NIKOS_SELECTED_TOOLS (comma separated) in the
# caller's scope. Prompts go to /dev/tty, never to stdout: under `curl | bash`
# stdin is the script itself, and a selector that printed its prose on the
# channel it returned its answer on has already lost answers once (#53).

# nikos_tools_catalog <distrodeck command...>
# Prints the validated catalog. Returns 1 when the flag is unsupported or the
# output is not the documented shape: at least six columns (distrodeck only
# ever appends), and a tool name that is safe in a comma-separated list.
nikos_tools_catalog() {
  local out
  out="$("$@" install-tools --list-catalog --format tsv 2>/dev/null)" || return 1
  [[ -n "${out}" ]] || return 1
  printf '%s\n' "${out}" | awk -F'\t' '
    NF == 0 { next }
    NF < 6 || $3 !~ /^[A-Za-z0-9._+-]+$/ || ($5 != "0" && $5 != "1") || ($6 != "0" && $6 != "1") { bad = 1 }
    END { exit bad }
  ' || return 1
  printf '%s\n' "${out}"
}

# nikos_tools_names <tsv> - every tool name, one per line.
nikos_tools_names() {
  printf '%s\n' "$1" | awk -F'\t' 'NF >= 6 { print $3 }'
}

# nikos_tools_default <tsv> <saved csv> - what is preselected: the saved list
# when there is one, otherwise what is already installed.
nikos_tools_default() {
  local tsv="$1" saved="$2"
  if [[ -n "${saved}" ]]; then
    printf '%s\n' "${saved}"
    return 0
  fi
  printf '%s\n' "${tsv}" | awk -F'\t' 'NF >= 6 && $6 == "1" { printf "%s%s", sep, $3; sep = "," } END { print "" }'
}

# nikos_tools_filter <tsv> <csv> - keeps only names the catalog knows, in
# catalog order, so a stale saved name cannot reach distrodeck.
nikos_tools_filter() {
  local tsv="$1" csv="$2"
  printf '%s\n' "${tsv}" | awk -F'\t' -v want=",${csv}," '
    NF >= 6 && index(want, "," $3 ",") { printf "%s%s", sep, $3; sep = "," }
    END { print "" }'
}

# nikos_tools_with_needs <tsv> <csv> - adds what a chosen tool cannot install
# without, then filters. distrodeck fails the whole --tools run (exit 1) when a
# container tool finds no docker or podman, or a Claude Code plugin finds no
# claude, so a selection of qdrant alone would fail every later setup. The TSV
# carries no dependency column: container tools are the ones whose label says
# "(container)", plugins are the plugin-* names. Notes go to stderr.
nikos_tools_with_needs() {
  local tsv="$1" csv="$2" have
  # Selected, or already installed on this machine.
  have=",${csv},$(printf '%s\n' "${tsv}" | awk -F'\t' 'NF >= 6 && $6 == "1" { printf "%s,", $3 }')"
  if printf '%s\n' "${tsv}" | awk -F'\t' -v want=",${csv}," '
      NF >= 6 && index(want, "," $3 ",") && $4 ~ /\(container\)/ { found = 1 }
      END { exit !found }' &&
    [[ "${have}" != *",docker,"* && "${have}" != *",podman,"* ]] &&
    printf '%s\n' "${tsv}" | awk -F'\t' '$3 == "docker" { found = 1 } END { exit !found }'; then
    echo "NOTE: adding docker: a selected container tool needs docker or podman." >&2
    csv="${csv},docker"
  fi
  if [[ ",${csv}," == *",plugin-"* && "${have}" != *",claude-code,"* ]] && ! command -v claude >/dev/null 2>&1 &&
    printf '%s\n' "${tsv}" | awk -F'\t' '$3 == "claude-code" { found = 1 } END { exit !found }'; then
    echo "NOTE: adding claude-code: the selected Claude Code plugins need it." >&2
    csv="${csv},claude-code"
  fi
  nikos_tools_filter "${tsv}" "${csv}"
}

# nikos_tools_select_plain <tsv> <saved csv>
# One prompt per category. Enter keeps the preselection, "-" clears it, "*"
# takes the whole category, otherwise a space or comma separated list of names.
nikos_tools_select_plain() {
  local tsv="$1" default cat_ids cat label tools line answer name chosen="" pre ok
  # Answers are split on spaces below; "*" or "?" must not expand to file names.
  local -
  set -f
  default="$(nikos_tools_default "${tsv}" "$2")"
  cat_ids="$(printf '%s\n' "${tsv}" | awk -F'\t' 'NF >= 6 && !seen[$1]++ { print $1 }')"

  printf '%s\n' "distrodeck tools, by category (Enter keeps the [preselection], - for none, * for all):" >/dev/tty
  while IFS= read -r cat; do
    [[ -n "${cat}" ]] || continue
    label="$(printf '%s\n' "${tsv}" | awk -F'\t' -v c="${cat}" '$1 == c { print $2; exit }')"
    tools="$(printf '%s\n' "${tsv}" | awk -F'\t' -v c="${cat}" '$1 == c { print $3 }')"
    pre="$(printf '%s\n' "${tsv}" | awk -F'\t' -v c="${cat}" -v want=",${default}," '
      $1 == c && index(want, "," $3 ",") { printf "%s%s", sep, $3; sep = " " }')"
    printf '\n%s:\n' "${label}" >/dev/tty
    printf '%s\n' "${tsv}" | awk -F'\t' -v c="${cat}" '$1 == c {
      printf "  %-18s %s%s%s\n", $3, $4, ($5 == "1" ? " (opt-in)" : ""), ($6 == "1" ? " [installed]" : "") }' >/dev/tty
    while :; do
      printf '  Install [%s]: ' "${pre}" >/dev/tty
      if ! IFS= read -r answer </dev/tty && [[ -z "${answer}" ]]; then
        printf '\n' >/dev/tty 2>/dev/null || true
        echo "ERROR: input ended while choosing distrodeck tools; nothing was installed." >&2
        return 130
      fi
      case "${answer}" in
        "") line="${pre}" ;;
        -) line="" ;;
        "*") line="$(printf '%s\n' "${tools}" | tr '\n' ' ')" ;;
        *) line="${answer//,/ }" ;;
      esac
      ok=1
      for name in ${line}; do
        if ! printf '%s\n' "${tools}" | grep -qxF -- "${name}"; then
          printf '  Not in %s: %s\n' "${label}" "${name}" >/dev/tty
          ok=0
        fi
      done
      [[ "${ok}" == "1" ]] && break
    done
    for name in ${line}; do chosen="${chosen:+${chosen},}${name}"; done
  done <<< "${cat_ids}"

  NIKOS_SELECTED_TOOLS="$(nikos_tools_with_needs "${tsv}" "${chosen}")"
  return 0
}

# nikos_tools_select_dialog <tsv> <saved csv> - one checklist, category in the
# description. Returns dialog's status; a cancel is not an empty selection.
nikos_tools_select_dialog() {
  local tsv="$1" default result status=0 n
  local -a items=()
  default="$(nikos_tools_default "${tsv}" "$2")"
  # Tab is IFS whitespace, so read would merge an empty label column into the
  # next one; split on the unit separator instead, which is not.
  while IFS=$'\037' read -r _cat cat_label tool label opt_in _installed; do
    [[ -n "${tool}" ]] || continue
    local state=off
    [[ ",${default}," == *",${tool},"* ]] && state=on
    [[ "${opt_in}" == "1" ]] && label="${label} (opt-in)"
    items+=("${tool}" "[${cat_label}] ${label}" "${state}")
  done <<< "${tsv//$'\t'/$'\037'}"
  n=$(( ${#items[@]} / 3 ))
  result=$(
    dialog --stdout \
      --title "NikOS - distrodeck tools" \
      --checklist "Space to toggle, Enter to confirm:" \
      "${DIALOG_HEIGHT:-20}" "${DIALOG_WIDTH:-70}" "$(( n < 15 ? n : 15 ))" \
      "${items[@]}" 0</dev/tty
  ) || status=$?
  (( status == 0 )) || return "${status}"
  result="${result//\"/}"
  NIKOS_SELECTED_TOOLS="$(nikos_tools_with_needs "${tsv}" "${result// /,}")"
  return 0
}
