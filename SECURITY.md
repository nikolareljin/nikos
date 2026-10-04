# Security policy

NikOS runs as root on the machine it sets up, adds apt repositories and
installs software, so security reports are taken seriously.

## Supported versions

| Version | Supported |
|---|---|
| 1.x (latest release) | yes |
| 0.x | no; `nikos update` moves to the latest release |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability
reporting:
[Report a vulnerability](https://github.com/nikolareljin/nikos/security/advisories/new).

Include what you can of:

- the NikOS version and Ubuntu release
- the role, script or file involved
- how to reproduce it, and what an attacker gains

You will get an acknowledgement on the advisory, and the fix is released as a
patch with credit to you unless you prefer otherwise.

## What is in scope

- anything that installs or runs code that was not verified (a download not
  checked against its pinned sha256, an apt key not checked against its
  fingerprint, an unpinned package)
- privilege problems in the installer, `nikos` CLI or roles (for example files
  written to predictable paths, or secrets left readable)
- services NikOS configures that listen beyond 127.0.0.1 without saying so

Problems in the upstream software NikOS installs (Ollama, VS Code, and so on)
belong with those projects; a report here is still welcome when NikOS's
configuration of it makes things worse.
