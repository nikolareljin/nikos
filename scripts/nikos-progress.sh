#!/usr/bin/env bash
# nikos-progress.sh — dialog progress rendering for NikOS Ansible runs.
#
# Ansible's own output is a colour-coded stream. Feeding it straight into
# `dialog --progressbox` renders the raw escape sequences as literal text
# (^[[0;33mchanged: [localhost]^[[0m), because progressbox does not interpret
# ANSI. This library replaces that with a `--mixedgauge` view: one row per
# role, an overall percentage taken from `ansible-playbook --list-tasks`, and
# the current task as the caption.
#
# Public functions:
#   nikos_progress_supported          — true when mixedgauge rendering can run
#   nikos_progress_plan <opts...>     — pre-count tasks and roles for a run
#   nikos_progress_run <title> <log> <cmd...> — run a command behind the gauge
#   nikos_progress_stream <log>       — ANSI-stripped fallback filter
#
# All rendering goes to /dev/tty because the command output occupies stdout.

# ── Internal state ───────────────────────────────────────────────────────────
NIKOS_PROGRESS_ROLES=()          # ordered role names
NIKOS_PROGRESS_TOTAL=0           # total task count from --list-tasks
declare -A NIKOS_PROGRESS_STATUS # role -> dialog mixedgauge status code

# dialog --mixedgauge status codes
readonly NIKOS_PROGRESS_SUCCEEDED=0
readonly NIKOS_PROGRESS_FAILED=1
readonly NIKOS_PROGRESS_RUNNING=7
# "-0" renders a 0% bar. Status 8 blanks the whole row, hiding the role name.
readonly NIKOS_PROGRESS_PENDING="-0"

# Tasks that run outside any role (pre_tasks/post_tasks) are grouped here.
readonly NIKOS_PROGRESS_PLAY_ROLE="playbook"

_nikos_progress_tty() {
  [[ -e /dev/tty ]] && { : >/dev/tty; } 2>/dev/null
}

# Returns 0 when the mixedgauge UI can be drawn.
nikos_progress_supported() {
  command -v dialog >/dev/null 2>&1 || return 1
  _nikos_progress_tty || return 1
  return 0
}

# Strip ANSI CSI/OSC sequences and carriage returns from stdin.
nikos_progress_strip_ansi() {
  # 1. OSC sequences (ESC ] ... BEL), 2. CSI sequences including the mouse
  # reports a pty emits (ESC [ <65;108;24M), 3. trailing carriage returns.
  # LC_ALL=C matters: under a UTF-8 locale the [@-~] and [ -/] ranges follow
  # collation order instead of byte order and stop matching escape sequences.
  LC_ALL=C sed -u \
    -e 's|\x1b\][^\x07]*\x07||g' \
    -e 's|\x1b\[[0-9;:<=>?]*[ -/]*[@-~]||g' \
    -e 's|\x1b[()][A-Za-z0-9]||g' \
    -e 's|\r$||'
}

# nikos_progress_plan <workdir> <ansible_cfg> <play_opts...>
# Populates NIKOS_PROGRESS_ROLES and NIKOS_PROGRESS_TOTAL. Returns non-zero
# when the task list could not be produced, in which case the caller should
# fall back to the streaming view.
nikos_progress_plan() {
  local workdir="$1" ansible_cfg="$2"
  shift 2

  NIKOS_PROGRESS_ROLES=()
  NIKOS_PROGRESS_TOTAL=0
  NIKOS_PROGRESS_STATUS=()

  local listing
  if ! listing=$(
    cd "${workdir}" 2>/dev/null &&
      ANSIBLE_CONFIG="${ansible_cfg}" ANSIBLE_NOCOLOR=1 ANSIBLE_FORCE_COLOR=0 \
      ansible-playbook --list-tasks "$@" 2>/dev/null
  ); then
    return 1
  fi

  local line entry role
  while IFS= read -r line; do
    # Task lines are indented six spaces; play and section headers are not.
    [[ "${line}" =~ ^\ {6}[^\ ] ]] || continue
    entry="${line#"${line%%[![:space:]]*}"}"   # trim leading whitespace
    entry="${entry%%$'\t'TAGS:*}"              # trim the trailing TAGS column
    [[ -n "${entry}" ]] || continue

    if [[ "${entry}" == *" : "* ]]; then
      role="${entry%% : *}"
    else
      role="${NIKOS_PROGRESS_PLAY_ROLE}"
    fi

    if [[ -z "${NIKOS_PROGRESS_STATUS[${role}]:-}" ]]; then
      NIKOS_PROGRESS_ROLES+=("${role}")
      NIKOS_PROGRESS_STATUS["${role}"]="${NIKOS_PROGRESS_PENDING}"
    fi
    NIKOS_PROGRESS_TOTAL=$((NIKOS_PROGRESS_TOTAL + 1))
  done <<<"${listing}"

  [[ "${NIKOS_PROGRESS_TOTAL}" -gt 0 ]]
}

# Choose the window of roles to display so the gauge fits the terminal.
_nikos_progress_window() {
  local current_index="$1" capacity="$2" total="${#NIKOS_PROGRESS_ROLES[@]}"
  local start=0

  if (( total > capacity )); then
    start=$(( current_index - capacity + 2 ))
    (( start < 0 )) && start=0
    (( start > total - capacity )) && start=$(( total - capacity ))
  fi
  printf '%s\n' "${start}"
}

# _nikos_progress_draw <title> <percent> <caption> <current_role>
_nikos_progress_draw() {
  local title="$1" percent="$2" caption="$3" current_role="$4"
  local height="${DIALOG_HEIGHT:-20}" width="${DIALOG_WIDTH:-72}"
  local total="${#NIKOS_PROGRESS_ROLES[@]}"

  # mixedgauge spends 8 lines on borders, the caption and the percentage box.
  # Overrunning that budget makes dialog drop the caption, which is the one
  # line telling the user which task is actually running.
  local capacity=$(( height - 8 ))
  (( capacity < 3 )) && capacity=3

  local current_index=0 i
  for (( i = 0; i < total; i++ )); do
    [[ "${NIKOS_PROGRESS_ROLES[i]}" == "${current_role}" ]] && current_index="${i}"
  done

  # A long "role: task name" caption would wrap and push the gauge off-screen.
  local max_caption=$(( width - 6 ))
  if (( max_caption > 8 && ${#caption} > max_caption )); then
    caption="${caption:0:max_caption-3}..."
  fi

  local start
  start=$(_nikos_progress_window "${current_index}" "${capacity}")

  local rows=() role
  for (( i = start; i < total && i < start + capacity; i++ )); do
    role="${NIKOS_PROGRESS_ROLES[i]}"
    rows+=("${role}" "${NIKOS_PROGRESS_STATUS[${role}]:-${NIKOS_PROGRESS_PENDING}}")
  done

  dialog --keep-window --title "${title}" \
    --mixedgauge "${caption}" "${height}" "${width}" "${percent}" \
    "${rows[@]}" >/dev/tty 2>/dev/null || true
}

# Mark every still-running role as finished once the play ends.
_nikos_progress_finalize() {
  local role
  for role in "${NIKOS_PROGRESS_ROLES[@]}"; do
    if [[ "${NIKOS_PROGRESS_STATUS[${role}]}" == "${NIKOS_PROGRESS_RUNNING}" ]]; then
      NIKOS_PROGRESS_STATUS["${role}"]="${NIKOS_PROGRESS_SUCCEEDED}"
    fi
  done
}

# nikos_progress_filter <title> <log>
# Reads plain (already ANSI-stripped) Ansible output on stdin, appends it to
# the log and redraws the gauge on every task boundary.
nikos_progress_filter() {
  local title="$1" log="$2"
  local line inner role task current_role="" caption="Starting..."
  local done_count=0 percent=0 recap_seen=0

  _nikos_progress_draw "${title}" 0 "Preparing..." ""

  while IFS= read -r line; do
    printf '%s\n' "${line}" >>"${log}"

    case "${line}" in
      "TASK ["*|"RUNNING HANDLER ["*)
        inner="${line#*[}"
        inner="${inner%%]*}"
        if [[ "${inner}" == *" : "* ]]; then
          role="${inner%% : *}"
          task="${inner#* : }"
        else
          role="${NIKOS_PROGRESS_PLAY_ROLE}"
          task="${inner}"
        fi

        # Handlers are not in --list-tasks, so only count real tasks.
        [[ "${line}" == "TASK ["* ]] && done_count=$((done_count + 1))

        if [[ -z "${NIKOS_PROGRESS_STATUS[${role}]:-}" ]]; then
          NIKOS_PROGRESS_ROLES+=("${role}")
        elif [[ -n "${current_role}" && "${role}" != "${current_role}" &&
                "${NIKOS_PROGRESS_STATUS[${current_role}]}" == "${NIKOS_PROGRESS_RUNNING}" ]]; then
          NIKOS_PROGRESS_STATUS["${current_role}"]="${NIKOS_PROGRESS_SUCCEEDED}"
        fi

        [[ "${NIKOS_PROGRESS_STATUS[${role}]:-}" == "${NIKOS_PROGRESS_FAILED}" ]] ||
          NIKOS_PROGRESS_STATUS["${role}"]="${NIKOS_PROGRESS_RUNNING}"
        current_role="${role}"

        if (( NIKOS_PROGRESS_TOTAL > 0 )); then
          percent=$(( done_count * 100 / NIKOS_PROGRESS_TOTAL ))
          (( percent > 99 )) && percent=99
        fi
        caption="${role}: ${task}"
        _nikos_progress_draw "${title}" "${percent}" "${caption}" "${current_role}"
        ;;
      "fatal: ["*|"failed: ["*)
        if [[ -n "${current_role}" ]]; then
          NIKOS_PROGRESS_STATUS["${current_role}"]="${NIKOS_PROGRESS_FAILED}"
          _nikos_progress_draw "${title}" "${percent}" "${caption}" "${current_role}"
        fi
        ;;
      "PLAY RECAP"*)
        recap_seen=1
        _nikos_progress_finalize
        _nikos_progress_draw "${title}" 100 "Finishing up..." "${current_role}"
        ;;
    esac
  done

  if (( recap_seen == 0 )); then
    _nikos_progress_draw "${title}" "${percent}" "${caption}" "${current_role}"
  fi
}

# nikos_progress_stream <title> <log>
# Fallback view: strip ANSI, log, and scroll the output in a programbox.
nikos_progress_stream() {
  local title="$1" log="$2"
  nikos_progress_strip_ansi \
    | tee -a "${log}" \
    | dialog --title "${title}" \
        --progressbox "Running Ansible playbook..." \
        "${DIALOG_HEIGHT:-20}" "${DIALOG_WIDTH:-72}"
}

# nikos_progress_run <title> <log> <workdir> <ansible_cfg> <play_opts...>
# Runs ansible-playbook behind the mixedgauge and returns the playbook's own
# exit status (not dialog's, and not tee's).
nikos_progress_run() {
  local title="$1" log="$2" workdir="$3" ansible_cfg="$4"
  shift 4

  local rc_file rc
  rc_file="$(mktemp "${TMPDIR:-/tmp}/nikos-play-rc.XXXXXX")"

  {
    if ! cd "${workdir}"; then
      printf '127\n' >"${rc_file}"
      exit 127
    fi
    ANSIBLE_CONFIG="${ansible_cfg}" ANSIBLE_NOCOLOR=1 ANSIBLE_FORCE_COLOR=0 \
      PYTHONUNBUFFERED=1 ansible-playbook "$@" 2>&1
    printf '%s\n' "$?" >"${rc_file}"
  } | nikos_progress_strip_ansi | nikos_progress_filter "${title}" "${log}"

  rc="$(cat "${rc_file}" 2>/dev/null || echo 1)"
  rm -f -- "${rc_file}"
  [[ "${rc}" =~ ^[0-9]+$ ]] || rc=1
  return "${rc}"
}
