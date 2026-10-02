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
# Tools NikOS installs itself, never through distrodeck: Ollama (ai-stack, the
# one owner of the inference port) and MongoDB (`nikos add mongodb`). Keep in
# step with nikos_distrodeck_owned_tools in vars/main.yml; a test checks it.
NIKOS_DISTRODECK_OWNED_TOOLS="${NIKOS_DISTRODECK_OWNED_TOOLS:-ollama,mongodb}"

nikos_tools_catalog() {
  local out
  out="$("$@" install-tools --list-catalog --format tsv 2>/dev/null)" || return 1
  [[ -n "${out}" ]] || return 1
  printf '%s\n' "${out}" | awk -F'\t' '
    NF == 0 { next }
    NF < 6 || $3 !~ /^[A-Za-z0-9._+-]+$/ || ($5 != "0" && $5 != "1") || ($6 != "0" && $6 != "1") { bad = 1 }
    END { exit bad }
  ' || return 1
  # Owned tools never reach a selection screen.
  printf '%s\n' "${out}" | awk -F'\t' -v owned=",${NIKOS_DISTRODECK_OWNED_TOOLS}," '
    NF == 0 || !index(owned, "," $3 ",")'
}

# nikos_tools_drop_owned <csv> - the saved list without NikOS-owned tools, with
# a note naming where each one comes from instead.
nikos_tools_drop_owned() {
  local csv="$1" name out=""
  local -a names=()
  IFS=, read -r -a names <<< "${csv}"
  for name in "${names[@]}"; do
    [[ -n "${name}" ]] || continue
    if [[ ",${NIKOS_DISTRODECK_OWNED_TOOLS}," == *",${name},"* ]]; then
      case "${name}" in
        ollama) echo "NOTE: dropping distrodeck's ollama: NikOS installs Ollama itself (ai-stack role)." >&2 ;;
        mongodb) echo "NOTE: dropping distrodeck's mongodb: use 'nikos add mongodb' instead." >&2 ;;
        *) echo "NOTE: dropping distrodeck's ${name}: NikOS installs it itself." >&2 ;;
      esac
      continue
    fi
    out="${out:+${out},}${name}"
  done
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
# without, then filters. distrodeck fails the whole --tools run (exit 1) when,
# say, a container tool finds no docker or podman. A catalog with a 7th column
# names the needs (comma list, "-" for none; "docker" is any container runtime,
# so podman satisfies it). A 6-column catalog has no such column, and the label
# is the only hint: "(container)" needs docker, plugin-* needs claude-code.
# A need is met when chosen, installed, or owned by NikOS. Notes go to stderr.
# An opt-in need (column 5 == 1: distrodeck holds it out of --all, because it
# runs an upstream installer or is a server, IDE or database) is added only when
# the user says yes on the terminal; otherwise the tool that needs it is dropped.
#
# _nikos_tools_confirm_optin <tool> <need> - 0 when the user agrees to add the
# need. No terminal means no.
_nikos_tools_confirm_optin() {
  local answer=""
  [[ -e /dev/tty ]] && { : >/dev/tty; } 2>/dev/null || return 1
  printf '%s needs %s, an opt-in tool. Add %s? [y/N]: ' "$1" "$2" "$2" >/dev/tty
  IFS= read -r answer </dev/tty || return 1
  [[ "${answer}" =~ ^[Yy]([Ee][Ss])?$ ]]
}

nikos_tools_with_needs() {
  local tsv="$1" csv="$2" have added=1 rows need tool dropped=","
  have=",${csv},${NIKOS_DISTRODECK_OWNED_TOOLS},$(printf '%s\n' "${tsv}" | awk -F'\t' 'NF >= 6 && $6 == "1" { printf "%s,", $3 }')"
  while (( added )); do
    added=0
    # "tool<TAB>need" for every need of every chosen tool.
    rows="$(printf '%s\n' "${tsv}" | awk -F'\t' -v want=",${csv}," '
      NF < 6 || !index(want, "," $3 ",") { next }
      NF >= 7 { if ($7 != "-" && $7 != "") { n = split($7, a, ","); for (i = 1; i <= n; i++) print $3 "\t" a[i] }; next }
      $4 ~ /\(container\)/ { print $3 "\tdocker" }
      $3 ~ /^plugin-/ { print $3 "\tclaude-code" }')"
    while IFS=$'\t' read -r tool need; do
      [[ -n "${need}" ]] || continue
      # A tool resting on one that was just dropped goes too.
      if [[ "${dropped}" == *",${need},"* && "${dropped}" != *",${tool},"* ]]; then
        echo "NOTE: dropping ${tool}: it needs ${need}, which was dropped." >&2
        dropped="${dropped}${tool},"
        added=1
        continue
      fi
      [[ "${have}" == *",${need},"* ]] && continue
      [[ "${need}" == "docker" && "${have}" == *",podman,"* ]] && continue
      [[ "${need}" == "claude-code" ]] && command -v claude >/dev/null 2>&1 && continue
      printf '%s\n' "${tsv}" | awk -F'\t' -v n="${need}" '$3 == n { f = 1 } END { exit !f }' || continue
      if printf '%s\n' "${tsv}" | awk -F'\t' -v n="${need}" '$3 == n && $5 == "1" { f = 1 } END { exit !f }' &&
        ! _nikos_tools_confirm_optin "${tool}" "${need}"; then
        if [[ "${dropped}" != *",${tool},"* ]]; then
          echo "NOTE: ${tool} needs ${need}, an opt-in tool; pick it too to install ${tool}." >&2
          dropped="${dropped}${tool},"
          added=1
        fi
        continue
      fi
      echo "NOTE: adding ${need}: ${tool} needs it." >&2
      csv="${csv:+${csv},}${need}"
      have="${have}${need},"
      added=1
    done <<< "${rows}"
  done
  if [[ "${dropped}" != "," ]]; then
    csv="$(printf '%s\n' "${csv//,/$'\n'}" | awk -v d="${dropped}" '!index(d, "," $0 ",")' | paste -sd, -)"
  fi
  nikos_tools_order "${tsv}" "$(nikos_tools_filter "${tsv}" "${csv}")"
}

# nikos_tools_order <tsv> <csv> - catalog order, except that a tool's chosen
# needs come before it: the catalog lists pgvector ahead of postgresql, and
# distrodeck installs in the order given.
nikos_tools_order() {
  printf '%s\n' "$1" | awk -F'\t' -v list="$2" '
    function visit(t,   n, a, i) {
      if (t in seen) return
      seen[t] = 1
      n = split(needs[t], a, ",")
      for (i = 1; i <= n; i++) {
        if (a[i] == "docker" && !(a[i] in chosen) && ("podman" in chosen)) a[i] = "podman"
        if (a[i] in chosen) visit(a[i])
      }
      out = out (out == "" ? "" : ",") t
    }
    NF >= 7 { needs[$3] = ($7 == "-" ? "" : $7); next }
    NF >= 6 && $4 ~ /\(container\)/ { needs[$3] = "docker" }
    NF >= 6 && $3 ~ /^plugin-/ { needs[$3] = "claude-code" }
    END {
      k = split(list, order, ",")
      for (i = 1; i <= k; i++) chosen[order[i]] = 1
      for (i = 1; i <= k; i++) visit(order[i])
      print out
    }'
}

# nikos_tools_select_plain <tsv> <saved csv>
# One prompt per category. Enter keeps the preselection, "-" clears it, "*"
# takes the whole category, otherwise a space or comma separated list of names.
nikos_tools_select_plain() {
  local tsv="$1" default cat_ids cat label tools line answer name chosen="" pre ok
  # Answers are split on spaces below; "*" or "?" must not expand to file names.
  local -
  set -f
  default="$(nikos_tools_default "${tsv}" "$(nikos_tools_drop_owned "$2")")"
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
  default="$(nikos_tools_default "${tsv}" "$(nikos_tools_drop_owned "$2")")"
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
