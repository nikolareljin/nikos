#!/usr/bin/env python3
"""NikOS first-run Git host setup wizard (installed as nikos-git-setup).

Generates an SSH key, sets the git identity and adds the key to GitHub,
GitLab, Bitbucket or a custom Git server. Tokens are read with getpass, held
in a local variable for one request, and never printed, logged or stored.
"""

import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_FLAG = Path.home() / ".config" / "nikos" / "github-configured"
SSH_DIR = Path.home() / ".ssh"
SSH_KEY = SSH_DIR / "id_ed25519"
HTTP_TIMEOUT = 20
KEY_TITLE = "nikos"

PROVIDERS = ["GitHub", "GitLab", "Bitbucket", "Custom Git server", "Skip"]
SETTINGS_URLS = {
    "GitHub": "https://github.com/settings/keys",
    "Bitbucket": "https://bitbucket.org/account/settings/ssh-keys/",
}

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*(?::(\d{1,5}))?$"
)


class Abort(Exception):
    """User pressed Ctrl-C or closed stdin."""


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def ask(msg: str) -> str:
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        raise Abort() from None


def ask_secret(msg: str) -> str:
    try:
        return getpass.getpass(msg).strip()
    except (EOFError, KeyboardInterrupt):
        raise Abort() from None


def yes(msg: str) -> bool:
    return ask(msg).lower() in ("y", "yes")


def write_flag() -> None:
    CONFIG_FLAG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FLAG.touch()


def _ssh_config_path() -> Path:
    return SSH_DIR / "config"


# -- host validation -------------------------------------------------------

def parse_host(raw: str) -> tuple[str, int | None]:
    """Return (hostname, port) or raise ValueError.

    Accepts `host`, `host:port` and `https://host[:port]`. Refuses any other
    scheme (http:// sends a token in clear text), paths and spaces.
    """
    value = raw.strip()
    if "://" in value:
        scheme, _, rest = value.partition("://")
        if scheme.lower() != "https":
            raise ValueError(f"refusing {scheme}:// host, HTTPS only")
        value = rest.rstrip("/")
    match = _HOST_RE.match(value)
    if not match:
        raise ValueError(f"not a hostname: {raw!r}")
    port = int(match.group(1)) if match.group(1) else None
    if port is not None and not 0 < port < 65536:
        raise ValueError(f"bad port in {raw!r}")
    return value.split(":")[0], port


def _api_base(host: str, port: int | None) -> str:
    return f"https://{host}:{port}" if port else f"https://{host}"


# -- HTTP ------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies our headers onto a redirect, token included, even to
    http:// or another host. Treat any redirect as the response instead."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)

def http_json(url: str, payload: dict | None, headers: dict) -> tuple[int | None, str]:
    """POST JSON (GET when payload is None) over HTTPS. Returns (status, body);
    status None on network error."""
    if not url.startswith("https://"):
        raise ValueError("HTTPS only")
    if payload is None:
        req = urllib.request.Request(url, method="GET")
    else:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        return None, str(getattr(exc, "reason", exc))


def _classify(status: int | None, body: str, dup_words: tuple[str, ...]) -> str:
    if status in (200, 201):
        return "added"
    if status == 400 and any(w in body.lower() for w in dup_words):
        return "present"
    if status in (401, 403):
        return "badtoken"
    return "error"


def http_post_json(url: str, payload: dict, headers: dict) -> tuple[int | None, str]:
    return http_json(url, payload, headers)


def gitlab_add_key(host: str, port: int | None, token: str, pubkey: str) -> str:
    status, body = http_post_json(
        f"{_api_base(host, port)}/api/v4/user/keys",
        {"title": KEY_TITLE, "key": pubkey},
        {"PRIVATE-TOKEN": token},
    )
    return _classify(status, body, ("has already been taken",))


def bitbucket_add_key(email: str, token: str, pubkey: str) -> str:
    """Bitbucket API tokens authenticate as the Atlassian account email, and the
    ssh-keys endpoint takes the account UUID, not the username."""
    auth = {"Authorization": "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()}
    status, body = http_json("https://api.bitbucket.org/2.0/user", None, auth)
    if status != 200:
        return _classify(status, body, ())
    try:
        uuid = json.loads(body)["uuid"]
    except (ValueError, KeyError, TypeError):
        return "error"
    status, body = http_post_json(
        f"https://api.bitbucket.org/2.0/users/{urllib.parse.quote(uuid, safe='')}/ssh-keys",
        {"key": pubkey, "label": KEY_TITLE},
        auth,
    )
    return _classify(status, body, ("already exists", "already in use", "already been added"))


# -- common steps ----------------------------------------------------------

def is_gh_authenticated() -> bool:
    return run(["gh", "auth", "status"], check=False).returncode == 0


def is_ssh_key_on_github(pubkey: str = "") -> bool:
    result = run(["gh", "ssh-key", "list"], check=False)
    if result.returncode != 0:
        # Missing admin:public_key scope: cannot verify. Assume present and warn.
        if "admin:public_key" in result.stderr or "scope" in result.stderr.lower():
            print("  [!] Cannot verify SSH key: missing admin:public_key scope.")
            print("      To grant it later: gh auth refresh -h github.com -s admin:public_key")
            return True
        return False
    # Match the key itself: a key titled "nikos" from another machine is not this one.
    parts = pubkey.split()
    if len(parts) >= 2:
        return parts[1] in result.stdout
    return "nikos" in result.stdout


def is_git_identity_set() -> bool:
    name = run(["git", "config", "--global", "user.name"], check=False)
    email = run(["git", "config", "--global", "user.email"], check=False)
    return bool(name.stdout.strip()) and bool(email.stdout.strip())


def step_ssh_key() -> str:
    """Create ~/.ssh/id_ed25519 if missing; never overwrite. Return the public key."""
    if SSH_KEY.exists():
        print(f"  [ok] Reusing existing key {SSH_KEY}")
    else:
        print("  Generating SSH key (ed25519)...")
        SSH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-C", KEY_TITLE, "-f", str(SSH_KEY), "-N", ""],
            check=True,
        )
    pub = SSH_KEY.with_suffix(".pub")
    if not pub.exists():
        # Private key without its .pub (copied over by hand): derive it.
        derived = subprocess.run(
            ["ssh-keygen", "-y", "-f", str(SSH_KEY)], check=True, text=True, stdout=subprocess.PIPE,
        )
        pub.write_text(derived.stdout.strip() + f" {KEY_TITLE}\n")
    return pub.read_text().strip()


def step_git_identity() -> None:
    if is_git_identity_set():
        print("  [ok] Git identity already configured")
        return
    name = ask("  Your full name for git commits: ")
    email = ask("  Your email for git commits: ")
    if not name or not email:
        print("  [!] Name or email empty, git identity left unset.")
        return
    run(["git", "config", "--global", "user.name", name])
    run(["git", "config", "--global", "user.email", email])
    print("  [ok] Git identity configured")


def step_dotfiles(provider: str, host: str, port: int, user: str) -> None:
    answer = ask("  Dotfiles repo (user/repo or a git URL), Enter to skip: ")
    if not answer:
        return
    if answer.startswith("-"):
        print(f"  [!] Not a repo: {answer!r}")
        return
    dest = Path.home() / "dotfiles"
    if dest.exists():
        print(f"  [!] {dest} already exists, not cloning.")
        return
    if "://" in answer or "@" in answer:
        cmd = ["git", "clone", answer, str(dest)]
    elif re.fullmatch(r"[\w.-]+/[\w.-]+", answer):
        if provider == "GitHub":
            cmd = ["gh", "repo", "clone", answer, str(dest)]
        elif port != 22:
            cmd = ["git", "clone", f"ssh://{user}@{host}:{port}/{answer}.git", str(dest)]
        else:
            cmd = ["git", "clone", f"{user}@{host}:{answer}.git", str(dest)]
    else:
        print(f"  [!] Not a repo: {answer!r}")
        return
    if subprocess.run(cmd, check=False).returncode == 0:
        print(f"  [ok] Dotfiles cloned to {dest}")
    else:
        print("  [!] Clone failed, continuing.")


# -- verification and custom hosts -----------------------------------------

def verify_ssh(user: str, host: str, port: int) -> bool:
    cmd = [
        "ssh", "-T", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
        "-p", str(port), f"{user}@{host}",
    ]
    try:
        result = subprocess.run(
            cmd, check=False, text=True, capture_output=True, timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        print(f"  [!] ssh to {host} timed out.")
        return False
    out = (result.stdout + result.stderr).lower()
    ok = result.returncode == 0 or "successfully authenticated" in out or "welcome" in out
    if ok:
        print(f"  [ok] SSH login to {host} works")
    else:
        print(f"  [!] SSH check to {host} failed (exit {result.returncode}).")
    return ok


def ensure_ssh_config(host: str, port: int, user: str) -> bool:
    """Append a Host block once. Returns True if it wrote one."""
    SSH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(SSH_DIR, 0o700)
    path = _ssh_config_path()
    marker = f"# nikos-git-setup: {host}"
    existing = path.read_text() if path.exists() else ""
    if marker in existing or re.search(rf"(?im)^\s*Host\s+(?:\S+\s+)*{re.escape(host)}(?:\s+\S+)*\s*$", existing):
        os.chmod(path, 0o600)
        return False
    block = f"\n{marker}\nHost {host}\n    HostName {host}\n    Port {port}\n    User {user}\n"
    with path.open("a") as fh:
        fh.write(block)
    os.chmod(path, 0o600)
    return True


def show_manual(pubkey: str, url: str | None) -> None:
    print("  Add this public key by hand:")
    print(f"    {pubkey}")
    if url:
        print(f"  SSH key settings: {url}")


# -- providers --------------------------------------------------------------

def setup_github(pubkey: str) -> tuple[str, int, str]:
    if is_gh_authenticated():
        print("  [ok] Already authenticated with GitHub")
    else:
        print("  Opening GitHub authentication flow...")
        if subprocess.run(["gh", "auth", "login"], check=False).returncode != 0:
            print("  [!] gh auth login failed.")
            show_manual(pubkey, SETTINGS_URLS["GitHub"])
            return "github.com", 22, "git"
    if is_ssh_key_on_github(pubkey):
        print("  [ok] SSH key already on GitHub")
    else:
        print("  Uploading SSH key to GitHub...")
        add = subprocess.run(
            ["gh", "ssh-key", "add", str(SSH_KEY.with_suffix(".pub")), "--title", KEY_TITLE],
            check=False,
        )
        if add.returncode != 0:
            print("  [!] Could not upload SSH key.")
            print("      Grant scope and retry: gh auth refresh -h github.com -s admin:public_key")
            show_manual(pubkey, SETTINGS_URLS["GitHub"])
            return "github.com", 22, "git"
    verify_ssh("git", "github.com", 22)
    return "github.com", 22, "git"


def _ask_host(prompt: str, default: str) -> tuple[str, int | None]:
    while True:
        raw = ask(prompt) or default
        try:
            return parse_host(raw)
        except ValueError as exc:
            print(f"  [!] {exc}")


def _report(result: str, pubkey: str, url: str) -> bool:
    if result == "added":
        print("  [ok] SSH key added")
    elif result == "present":
        print("  [ok] SSH key already present")
    elif result == "badtoken":
        print("  [!] Token rejected (401/403). Check the token and its scope.")
    else:
        print("  [!] Upload failed.")
    if result in ("added", "present"):
        return True
    show_manual(pubkey, url)
    return False


def setup_gitlab(pubkey: str) -> tuple[str, int, str]:
    host, api_port = _ask_host("  GitLab host [gitlab.com]: ", "gitlab.com")
    token = ask_secret("  Personal access token with scope 'api' (input hidden): ")
    url = f"{_api_base(host, api_port)}/-/user_settings/ssh_keys"
    ok = _report(gitlab_add_key(host, api_port, token, pubkey) if token else "error", pubkey, url)
    del token
    ssh_port = 22
    if host != "gitlab.com":
        raw = ask("  SSH port of this GitLab [22]: ") or "22"
        if raw.isdigit() and 0 < int(raw) < 65536:
            ssh_port = int(raw)
        else:
            print(f"  [!] Not a port: {raw!r}; using 22.")
    if ok:
        verify_ssh("git", host, ssh_port)
    return host, ssh_port, "git"


def setup_bitbucket(pubkey: str) -> tuple[str, int, str]:
    email = ask("  Atlassian account email: ")
    if not re.fullmatch(r"[^@\s:]+@[^@\s:]+", email):
        print("  [!] Not an email address.")
        show_manual(pubkey, SETTINGS_URLS["Bitbucket"])
        return "bitbucket.org", 22, "git"
    token = ask_secret("  Bitbucket API token with SSH key read/write and account read (input hidden): ")
    result = bitbucket_add_key(email, token, pubkey) if token else "error"
    del token
    if _report(result, pubkey, SETTINGS_URLS["Bitbucket"]):
        verify_ssh("git", "bitbucket.org", 22)
    return "bitbucket.org", 22, "git"


def setup_custom(pubkey: str) -> tuple[str, int, str]:
    host, _ = _ask_host("  Git server host: ", "")
    port_raw = ask("  SSH port [22]: ") or "22"
    if port_raw.isdigit() and 0 < int(port_raw) < 65536:
        port = int(port_raw)
    else:
        print(f"  [!] Bad port {port_raw!r}, using 22.")
        port = 22
    user = ask("  SSH user [git]: ") or "git"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", user):
        print("  [!] Bad user name, using git.")
        user = "git"
    print("  Add this public key to your account on the server:")
    print(f"    {pubkey}")
    if port != 22 or user != "git":
        if ensure_ssh_config(host, port, user):
            print(f"  [ok] Added Host {host} to {_ssh_config_path()}")
    ask("  Press Enter once the key is added on the server...")
    verify_ssh(user, host, port)
    return host, port, user


HANDLERS = {
    "GitHub": setup_github,
    "GitLab": setup_gitlab,
    "Bitbucket": setup_bitbucket,
    "Custom Git server": setup_custom,
}


def choose_provider() -> str:
    for i, name in enumerate(PROVIDERS, start=1):
        label = "Skip (I will set up SSH keys myself)" if name == "Skip" else name
        print(f"  {i}) {label}")
    while True:
        answer = ask(f"  Choose 1-{len(PROVIDERS)}: ")
        if answer.isdigit() and 1 <= int(answer) <= len(PROVIDERS):
            return PROVIDERS[int(answer) - 1]
        print("  [!] Enter a number from the list.")


def banner() -> None:
    print()
    print("+--------------------------------------------------+")
    print("|  NikOS - Git host setup                          |")
    print("+--------------------------------------------------+")
    print()
    print("This wizard creates an SSH key (~/.ssh/id_ed25519, reused if present),")
    print("sets your git name and email if unset, and adds the key to your Git")
    print("host so you can clone and push over SSH. It runs once.")
    print()


def confirm_skip() -> bool:
    print()
    print("No SSH key will be generated or uploaded. You will need to create your")
    print("own key (ssh-keygen -t ed25519) and add it to GitHub or your Git host")
    print("yourself. Rerun any time with `nikos-git-setup --reset`.")
    return yes("Skip Git setup? [y/N]: ")


def interactive() -> int:
    banner()
    provider = choose_provider()
    while provider == "Skip":
        if confirm_skip():
            write_flag()
            return 0
        provider = choose_provider()

    print("\n[1] SSH key")
    pubkey = step_ssh_key()
    print("\n[2] Git identity")
    step_git_identity()

    first = None
    while True:
        print(f"\n[3] {provider}")
        target = HANDLERS[provider](pubkey)
        first = first or (provider, *target)
        if not yes("\nAdd another Git host? [y/N]: "):
            break
        provider = choose_provider()
        if provider == "Skip":
            break

    print("\n[4] Dotfiles (optional)")
    step_dotfiles(*first)
    write_flag()
    print("\n[ok] Git setup complete. Rerun any time with `nikos-git-setup --reset`.")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nikos-git-setup", description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="forget the done flag and run again")
    parser.add_argument("--skip", action="store_true", help="mark setup done without asking")
    args = parser.parse_args([] if argv is None else argv)

    if args.skip:
        write_flag()
        sys.exit(0)
    if not sys.stdin.isatty():
        sys.exit(0)
    if args.reset:
        CONFIG_FLAG.unlink(missing_ok=True)
    elif CONFIG_FLAG.exists():
        print("Git setup already done. Run `nikos-git-setup --reset` to run it again.")
        sys.exit(0)
    try:
        sys.exit(interactive())
    except (Abort, KeyboardInterrupt):
        print("\nAborted. Setup not marked done; the wizard runs again next terminal.")
        sys.exit(130)


if __name__ == "__main__":
    main(sys.argv[1:])
