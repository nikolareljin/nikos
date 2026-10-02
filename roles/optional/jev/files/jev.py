"""jev - ask TypeSafe Jev (System One) typed questions from the terminal.

Uses the official SDK, typesafe-sdk, installed by NikOS from a hash-pinned lock.
The API key comes from TYPESAFE_API_KEY or ~/.config/typesafe/api_key (mode
600, written by `jev login`). It is never printed or passed on a command line.

  jev login
  jev choose "I was charged twice" billing technical other
  jev score "Thanks, fixed in minutes" "angry" "neutral" "happy"
"""

from __future__ import annotations

import argparse
import getpass
import os
import stat
import sys
from pathlib import Path

KEY_ENV = "TYPESAFE_API_KEY"
KEY_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "typesafe" / "api_key"
CONSOLE_URL = "https://typesafe.ai"


def read_key() -> str | None:
    """The key from the environment, else from KEY_FILE. Refuses a key file
    other users can read, as ssh does for a private key."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    if not KEY_FILE.exists():
        return None
    mode = stat.S_IMODE(KEY_FILE.stat().st_mode)
    if mode & 0o077:
        raise SystemExit(f"jev: {KEY_FILE} is readable by others (mode {mode:o}); run: chmod 600 {KEY_FILE}")
    return KEY_FILE.read_text().strip() or None


def write_key(key: str) -> None:
    KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Create at 600 before writing: a umask-default file would hold the key
    # readable by others for a moment.
    # O_CREAT's mode applies only to a new file: tighten an existing one on
    # the open descriptor before anything is written to it.
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key + "\n")


def cmd_login(_args: argparse.Namespace) -> int:
    print(f"Get a key from the TypeSafe console ({CONSOLE_URL}).")
    try:
        key = getpass.getpass("TypeSafe API key (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 130
    if not key:
        print("jev: no key entered, nothing saved.", file=sys.stderr)
        return 1
    write_key(key)
    print(f"Saved to {KEY_FILE} (mode 600).")
    return 0


def _state(args: argparse.Namespace) -> str:
    if args.text == "-":
        return sys.stdin.read()
    return args.text


def _client(key: str):
    from typesafe_sdk import TypeSafeClient

    return TypeSafeClient(api_key=key)


def require_key() -> str:
    key = read_key()
    if not key:
        raise SystemExit(f"jev: no API key. Run `jev login` or set {KEY_ENV}.")
    return key


def _ask(questions: dict, args: argparse.Namespace):
    key = require_key()
    from typesafe_sdk import TypeSafeAuthenticationError, TypeSafeError

    try:
        with _client(key) as client:
            return client.system_one(state=_state(args), questions=questions)
    except TypeSafeAuthenticationError:
        raise SystemExit("jev: the API key was rejected. Run `jev login` with a new key.") from None
    except TypeSafeError as exc:
        raise SystemExit(f"jev: {type(exc).__name__}: {exc}") from None


def _probabilities(probs: dict) -> str:
    return "  ".join(f"{k}={v:.2f}" for k, v in sorted(probs.items(), key=lambda kv: -kv[1]))


def cmd_choose(args: argparse.Namespace) -> int:
    from typesafe_sdk import Choice

    if len(args.labels) < 2:
        raise SystemExit("jev: choose needs at least two labels.")
    if len(set(args.labels)) != len(args.labels):
        raise SystemExit("jev: each label must be different.")
    answer = _ask(
        {"answer": Choice(instructions=args.question, criteria={label: None for label in args.labels})}, args
    ).choices["answer"]
    print(answer.choice)
    print(f"confidence {answer.confidence:.2f}   {_probabilities(answer.probabilities)}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from typesafe_sdk import Score

    answer = _ask({"answer": Score(instructions=args.question, criteria=list(args.levels))}, args).scores["answer"]
    print(f"{answer.score:.2f}")
    print(f"confidence {answer.confidence:.2f}   {_probabilities(answer.probabilities)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jev", description="Ask TypeSafe Jev typed questions.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help=f"store your API key in {KEY_FILE}").set_defaults(func=cmd_login)

    choose = sub.add_parser("choose", help="pick one label for a text")
    choose.add_argument("text", help="the text to judge, or - for stdin")
    choose.add_argument("labels", nargs="+", help="two or more labels")
    choose.add_argument("-q", "--question", help="what to ask about the text")
    choose.set_defaults(func=cmd_choose)

    score = sub.add_parser("score", help="grade a text against ordered levels, lowest first")
    score.add_argument("text", help="the text to judge, or - for stdin")
    score.add_argument("levels", nargs="+", help="level descriptions, lowest first")
    score.add_argument("-q", "--question", help="what to ask about the text")
    score.set_defaults(func=cmd_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "login":
        require_key()  # before the SDK import, so a missing key reads as that
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
