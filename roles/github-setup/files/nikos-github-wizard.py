#!/usr/bin/env python3
"""NikOS first-run GitHub setup wizard."""

import subprocess
import sys
from pathlib import Path

CONFIG_FLAG = Path.home() / ".config" / "nikos" / "github-configured"
CONFIG_DIR = CONFIG_FLAG.parent


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def is_gh_authenticated() -> bool:
    result = run(["gh", "auth", "status"], check=False)
    return result.returncode == 0


def is_ssh_key_on_github() -> bool:
    result = run(["gh", "ssh-key", "list"], check=False)
    if result.returncode != 0:
        # Missing admin:public_key scope — cannot verify. Assume present and warn.
        if "admin:public_key" in result.stderr or "scope" in result.stderr.lower():
            print("  [!] Cannot verify SSH key: missing admin:public_key scope.")
            print("      To grant it later: gh auth refresh -h github.com -s admin:public_key")
            return True
        return False
    return "nikos" in result.stdout


def is_git_identity_set() -> bool:
    name = run(["git", "config", "--global", "user.name"], check=False)
    email = run(["git", "config", "--global", "user.email"], check=False)
    return bool(name.stdout.strip()) and bool(email.stdout.strip())


def step_gh_auth() -> None:
    if is_gh_authenticated():
        print("  [✓] Already authenticated with GitHub")
        return
    print("  Opening GitHub authentication flow...")
    subprocess.run(["gh", "auth", "login"], check=True)


def step_ssh_key() -> None:
    ssh_key_path = Path.home() / ".ssh" / "id_ed25519"
    if not ssh_key_path.exists():
        print("  Generating SSH key (ed25519)...")
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-C", "nikos", "-f", str(ssh_key_path), "-N", ""],
            check=True,
        )
    if is_ssh_key_on_github():
        print("  [✓] SSH key already on GitHub")
        return
    print("  Uploading SSH key to GitHub...")
    try:
        subprocess.run(
            ["gh", "ssh-key", "add", str(ssh_key_path.with_suffix(".pub")), "--title", "nikos"],
            check=True,
        )
    except subprocess.CalledProcessError:
        print("  [!] Could not upload SSH key.")
        print("      Grant scope and retry: gh auth refresh -h github.com -s admin:public_key")
        sys.exit(1)


def step_git_identity() -> None:
    if is_git_identity_set():
        print("  [✓] Git identity already configured")
        return
    name = input("  Your full name for git commits: ").strip()
    email = input("  Your email for git commits: ").strip()
    run(["git", "config", "--global", "user.name", name])
    run(["git", "config", "--global", "user.email", email])
    print("  [✓] Git identity configured")


def step_dotfiles() -> None:
    answer = input("  Pull dotfiles repo from GitHub? Enter repo (user/repo) or press Enter to skip: ").strip()
    if not answer:
        return
    dest = Path.home() / "dotfiles"
    subprocess.run(["gh", "repo", "clone", answer, str(dest)], check=True)
    print(f"  [✓] Dotfiles cloned to {dest}")


def main() -> None:
    if CONFIG_FLAG.exists():
        sys.exit(0)

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║  NikOS — Neural Innovation for Knowledge OS      ║")
    print("║  First Run GitHub Setup                          ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    steps = [
        ("Authenticate with GitHub", step_gh_auth),
        ("Set up SSH key", step_ssh_key),
        ("Configure git identity", step_git_identity),
        ("Pull dotfiles repo (optional)", step_dotfiles),
    ]

    for i, (label, fn) in enumerate(steps, start=1):
        print(f"\n[{i}/{len(steps)}] {label}")
        fn()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FLAG.touch()
    print("\n[✓] GitHub setup complete. Configuration saved.")


if __name__ == "__main__":
    main()
