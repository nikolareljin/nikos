# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# Derived from ansible-core's sudo become plugin (lib/ansible/plugins/become/sudo.py).
from __future__ import annotations

DOCUMENTATION = """
    name: nikos_sudo
    short_description: sudo that also understands the sudo-rs password prompt
    description:
        - "The builtin sudo plugin passes its own prompt with -p and waits for a
          line that starts with it. sudo-rs, the default sudo on Ubuntu 26.04,
          prints '[sudo: <prompt>] Password:' instead, so the password is never
          sent and the task times out. This plugin accepts both forms.
          ansible-core carries the same fix upstream in 2.20.11 and 2.21.6, not
          in 2.21.5; Ubuntu 26.04 ships 2.20.1."
        - Same options as the builtin sudo plugin.
    author: NikOS
    options:
        become_user:
            description: User you 'become' to execute the task
            default: root
            ini:
              - section: privilege_escalation
                key: become_user
              - section: sudo_become_plugin
                key: user
            vars:
              - name: ansible_become_user
              - name: ansible_sudo_user
            env:
              - name: ANSIBLE_BECOME_USER
              - name: ANSIBLE_SUDO_USER
            keyword:
              - name: become_user
        become_exe:
            description: Sudo executable
            default: sudo
            ini:
              - section: privilege_escalation
                key: become_exe
              - section: sudo_become_plugin
                key: executable
            vars:
              - name: ansible_become_exe
              - name: ansible_sudo_exe
            env:
              - name: ANSIBLE_BECOME_EXE
              - name: ANSIBLE_SUDO_EXE
            keyword:
              - name: become_exe
        become_flags:
            description: Options to pass to sudo
            default: -H -S -n
            ini:
              - section: privilege_escalation
                key: become_flags
              - section: sudo_become_plugin
                key: flags
            vars:
              - name: ansible_become_flags
              - name: ansible_sudo_flags
            env:
              - name: ANSIBLE_BECOME_FLAGS
              - name: ANSIBLE_SUDO_FLAGS
            keyword:
              - name: become_flags
        become_pass:
            description: Password to pass to sudo
            required: False
            vars:
              - name: ansible_become_password
              - name: ansible_become_pass
              - name: ansible_sudo_pass
            env:
              - name: ANSIBLE_BECOME_PASS
              - name: ANSIBLE_SUDO_PASS
            ini:
              - section: sudo_become_plugin
                key: password
        sudo_chdir:
            description: Directory to change to before invoking sudo; can avoid permission errors when dropping privileges.
            type: string
            required: False
            vars:
              - name: ansible_sudo_chdir
            env:
              - name: ANSIBLE_SUDO_CHDIR
            ini:
              - section: sudo_become_plugin
                key: chdir
"""

import re

from ansible.plugins.become.sudo import BecomeModule as SudoBecomeModule


class BecomeModule(SudoBecomeModule):

    # The plugin loader keys on this; it must match the file name.
    name = 'nikos_sudo'

    def check_password_prompt(self, b_output: bytes) -> bool:
        if super().check_password_prompt(b_output):
            return True
        if not self.prompt:
            return False
        sudo_rs = re.compile(self._sudo_rs_prompt() + rb'\s+\S')
        return any(sudo_rs.match(line.strip()) for line in b_output.splitlines())

    def strip_become_prompt(self, data: bytes) -> bytes:
        # The builtin stops at the -p text, which leaves '] Password: ****' in
        # the task's stderr, and the stars show the password's length.
        if self.prompt and self.expect_prompt():
            data, found = re.subn(rb'^.*?' + self._sudo_rs_prompt() + rb'[^\n]*\n?', b'', data, count=1, flags=re.DOTALL)
            if found:
                return data
        return super().strip_become_prompt(data)

    def _sudo_rs_prompt(self) -> bytes:
        # sudo-rs wraps the -p text and appends its own localized word:
        # '[sudo: [sudo via ansible, key=...] password:] Password:'
        return rb'\[sudo:\s+' + re.escape(self.prompt.encode()) + rb'\]'
