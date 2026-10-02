"""Tests for nikos-github-wizard.py."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Load wizard module from file (hyphenated filename requires importlib)
_wizard_path = Path(__file__).parent.parent / "roles/github-setup/files/nikos-github-wizard.py"
_spec = importlib.util.spec_from_file_location("nikos_github_wizard", _wizard_path)
wizard = importlib.util.module_from_spec(_spec)
sys.modules["nikos_github_wizard"] = wizard
_spec.loader.exec_module(wizard)


def test_is_gh_authenticated_returns_false_when_gh_fails():
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert wizard.is_gh_authenticated() is False


def test_is_gh_authenticated_returns_true_when_gh_succeeds():
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert wizard.is_gh_authenticated() is True


def test_is_git_identity_set_returns_false_when_empty():
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert wizard.is_git_identity_set() is False


def test_is_ssh_key_on_github_returns_true_when_key_present():
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="nikos  ssh-ed25519 AAAA...")
        assert wizard.is_ssh_key_on_github() is True


def test_is_ssh_key_on_github_returns_false_when_key_absent():
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="other-key  ssh-ed25519 BBBB...")
        assert wizard.is_ssh_key_on_github() is False


def test_is_ssh_key_on_github_assumes_present_when_scope_missing(capsys):
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="This API operation needs the \"admin:public_key\" scope.",
        )
        result = wizard.is_ssh_key_on_github()
    assert result is True
    captured = capsys.readouterr()
    assert "admin:public_key" in captured.out


def test_is_ssh_key_on_github_returns_false_on_other_error():
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="network error")
        assert wizard.is_ssh_key_on_github() is False


def test_main_exits_early_if_already_configured(tmp_path, monkeypatch):
    flag = tmp_path / "github-configured"
    flag.touch()
    monkeypatch.setattr(wizard, "CONFIG_FLAG", flag)
    mock_exit = MagicMock(side_effect=SystemExit(0))
    with patch("sys.exit", mock_exit):
        try:
            wizard.main()
        except SystemExit:
            pass
    mock_exit.assert_called_once_with(0)


# -- provider wizard ---------------------------------------------------------

import io
import base64
import json
import urllib.error

import pytest
import yaml


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Unit tests never reach a real Git host. A stale patch target once sent the
    test token to gitlab.com; any outbound connect now fails the test."""
    import socket
    real = socket.socket.connect

    def guard(sock, addr):
        if isinstance(addr, tuple) and addr[0] not in ("127.0.0.1", "::1"):
            raise AssertionError(f"network call to {addr}")
        return real(sock, addr)
    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture(autouse=True)
def _tools_present(monkeypatch):
    """gh and ssh count as installed unless a test says otherwise."""
    monkeypatch.setattr(wizard, "have", lambda cmd: True)

ROOT = Path(__file__).parent.parent
TOKEN = "glpat-SECRET-TOKEN-123"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(wizard, "CONFIG_FLAG", tmp_path / ".config/nikos/github-configured")
    monkeypatch.setattr(wizard, "SSH_DIR", tmp_path / ".ssh")
    monkeypatch.setattr(wizard, "SSH_KEY", tmp_path / ".ssh/id_ed25519")
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: True, raising=False)
    return tmp_path


def feed(monkeypatch, answers, secret=TOKEN):
    it = iter(answers)

    def fake_input(_msg=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(wizard.getpass, "getpass", lambda _m="": secret)


def fake_key(home):
    (home / ".ssh").mkdir(exist_ok=True)
    (home / ".ssh/id_ed25519").write_text("PRIVATE")
    (home / ".ssh/id_ed25519.pub").write_text("ssh-ed25519 AAAAkey nikos")


class Recorder:
    """Stands in for subprocess.run; records argv, returns success."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, *a, **kw):
        self.calls.append(list(cmd))
        out = "Welcome to GitLab" if cmd[0] == "ssh" else "x"
        return MagicMock(returncode=1 if cmd[0] == "ssh" else 0, stdout=out, stderr="")


def run_main(argv=None):
    with pytest.raises(SystemExit) as exc:
        wizard.main(argv or [])
    return exc.value.code


def http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body.encode()))


def test_skip_writes_flag_and_never_runs_ssh_keygen(home, monkeypatch, capsys):
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    feed(monkeypatch, ["5", "y"])
    assert run_main() == 0
    assert wizard.CONFIG_FLAG.exists()
    assert not any(c[0] == "ssh-keygen" for c in rec.calls)
    out = capsys.readouterr().out
    assert "ssh-keygen -t ed25519" in out and "nikos-git-setup" in out


def test_skip_flag_cli_writes_flag_without_tty(home, monkeypatch):
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: False, raising=False)
    assert run_main(["--skip"]) == 0
    assert wizard.CONFIG_FLAG.exists()


def test_reset_removes_flag_and_runs(home, monkeypatch):
    wizard.write_flag()
    feed(monkeypatch, [])
    assert run_main(["--reset"]) == 130
    assert not wizard.CONFIG_FLAG.exists()


def test_non_tty_exits_zero_without_prompting(home, monkeypatch):
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: False, raising=False)
    prompted = MagicMock(side_effect=AssertionError("prompted"))
    monkeypatch.setattr("builtins.input", prompted)
    assert run_main() == 0
    prompted.assert_not_called()
    assert not wizard.CONFIG_FLAG.exists()


def test_eof_exits_130_without_flag(home, monkeypatch):
    feed(monkeypatch, [])
    assert run_main() == 130
    assert not wizard.CONFIG_FLAG.exists()


def test_existing_key_is_reused_not_overwritten(home, monkeypatch):
    fake_key(home)
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    assert wizard.step_ssh_key() == "ssh-ed25519 AAAAkey nikos"
    assert rec.calls == []
    assert (home / ".ssh/id_ed25519").read_text() == "PRIVATE"


@pytest.mark.parametrize("raw", ["http://gitlab.example.com", "ftp://gitlab.example.com"])
def test_non_https_host_refused(raw):
    with pytest.raises(ValueError):
        wizard.parse_host(raw)


@pytest.mark.parametrize("raw", ["gitlab.example.com/api", "git lab.com", "", "a.com:99999"])
def test_bad_hostname_refused(raw):
    with pytest.raises(ValueError):
        wizard.parse_host(raw)


def test_https_host_and_port_accepted():
    assert wizard.parse_host("https://git.example.com:8443/") == ("git.example.com", 8443)
    assert wizard.parse_host("gitlab.com") == ("gitlab.com", None)


def test_http_post_refuses_plain_http():
    with pytest.raises(ValueError):
        wizard.http_post_json("http://x", {}, {})


def _urlopen_returning(status=None, error=None, seen=None):
    def fake(req, timeout=None):
        assert timeout
        if seen is not None:
            seen.append(req)
        if error:
            raise error
        resp = MagicMock(status=status)
        resp.read.return_value = b"{}"
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: False
        return resp
    return fake


def test_gitlab_201_added(monkeypatch):
    seen = []
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(201, seen=seen))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "ssh-ed25519 K") == "added"
    req = seen[0]
    assert req.full_url == "https://gitlab.com/api/v4/user/keys"
    assert req.get_header("Private-token") == TOKEN
    assert json.loads(req.data) == {"title": "nikos", "key": "ssh-ed25519 K"}


def test_gitlab_400_duplicate_is_present(monkeypatch):
    err = http_error(400, '{"message":{"fingerprint":["has already been taken"]}}')
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "present"


def test_gitlab_400_other_is_error(monkeypatch):
    err = http_error(400, '{"message":"key is invalid"}')
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "error"


def test_gitlab_401_bad_token(monkeypatch):
    err = http_error(401, '{"message":"401 Unauthorized"}')
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "badtoken"


def _sequence(*responses, seen=None):
    """Fake opener answering each request with the next (status, body)."""
    queue = list(responses)

    def fake(req, timeout=None):
        assert timeout
        if seen is not None:
            seen.append(req)
        status, body = queue.pop(0)
        if status >= 400:
            raise http_error(status, body)
        resp = MagicMock(status=status)
        resp.read.return_value = body.encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: False
        return resp
    return fake


def test_bitbucket_201_added(monkeypatch):
    seen = []
    monkeypatch.setattr(wizard._OPENER, "open", _sequence(
        (200, '{"uuid": "{abc-123}"}'), (201, "{}"), seen=seen))
    assert wizard.bitbucket_add_key("me@example.com", TOKEN, "k") == "added"
    assert seen[0].full_url == "https://api.bitbucket.org/2.0/user"
    assert seen[0].get_method() == "GET"
    assert seen[1].full_url == "https://api.bitbucket.org/2.0/users/%7Babc-123%7D/ssh-keys"
    expected = "Basic " + base64.b64encode(f"me@example.com:{TOKEN}".encode()).decode()
    assert all(r.get_header("Authorization") == expected for r in seen)


def test_bitbucket_401_bad_token(monkeypatch):
    seen = []
    monkeypatch.setattr(wizard._OPENER, "open", _sequence((401, ""), seen=seen))
    assert wizard.bitbucket_add_key("me@example.com", TOKEN, "k") == "badtoken"
    assert len(seen) == 1


def test_bitbucket_duplicate_is_present(monkeypatch):
    monkeypatch.setattr(wizard._OPENER, "open", _sequence(
        (200, '{"uuid": "{abc}"}'), (400, '{"error":{"message":"Key already exists"}}')))
    assert wizard.bitbucket_add_key("me@example.com", TOKEN, "k") == "present"


def test_bitbucket_user_without_uuid_is_error(monkeypatch):
    monkeypatch.setattr(wizard._OPENER, "open", _sequence((200, "{}")))
    assert wizard.bitbucket_add_key("me@example.com", TOKEN, "k") == "error"


def test_github_key_match_is_by_key_not_title():
    out = "nikos\tssh-ed25519 OTHERMACHINE\t2026-01-01\n"
    with patch("nikos_github_wizard.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=out)
        assert wizard.is_ssh_key_on_github("ssh-ed25519 THISMACHINE nikos") is False
        assert wizard.is_ssh_key_on_github("ssh-ed25519 OTHERMACHINE nikos") is True


def test_missing_pub_is_derived_from_private_key(home, monkeypatch):
    (home / ".ssh").mkdir()
    monkeypatch.setattr(wizard, "SSH_DIR", home / ".ssh")
    monkeypatch.setattr(wizard, "SSH_KEY", home / ".ssh/id_ed25519")
    (home / ".ssh/id_ed25519").write_text("PRIVATE")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="ssh-ed25519 DERIVED\n")
    monkeypatch.setattr(wizard.subprocess, "run", fake_run)
    assert wizard.step_ssh_key() == "ssh-ed25519 DERIVED nikos"
    assert calls == [["ssh-keygen", "-y", "-f", str(home / ".ssh/id_ed25519")]]


def test_custom_sees_host_in_a_multi_host_line(home, monkeypatch):
    monkeypatch.setattr(wizard, "SSH_DIR", home / ".ssh")
    (home / ".ssh").mkdir()
    (home / ".ssh/config").write_text("Host other git.example.com\n    Port 2200\n")
    assert wizard.ensure_ssh_config("git.example.com", 2222, "git") is False
    assert wizard.ensure_ssh_config("example.com", 2222, "git") is True


def test_network_error_is_error(monkeypatch):
    err = urllib.error.URLError("no route")
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "error"


def test_gitlab_flow_token_never_in_argv_or_output(home, monkeypatch, capsys):
    fake_key(home)
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    monkeypatch.setattr(wizard, "is_git_identity_set", lambda: True)
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(error=http_error(401, "")))
    feed(monkeypatch, ["2", "gitlab.com", "n", ""])
    assert run_main() == 0
    assert wizard.CONFIG_FLAG.exists()
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert "/-/user_settings/ssh_keys" in out.out
    assert all(TOKEN not in " ".join(c) for c in rec.calls)
    assert not (home / ".ssh/config").exists()


def test_gitlab_flow_verifies_over_ssh(home, monkeypatch, capsys):
    fake_key(home)
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    monkeypatch.setattr(wizard, "is_git_identity_set", lambda: True)
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(201))
    feed(monkeypatch, ["2", "", "n", ""])
    assert run_main() == 0
    ssh = [c for c in rec.calls if c[0] == "ssh"]
    assert ssh and ssh[0][-1] == "git@gitlab.com" and "BatchMode=yes" in ssh[0]
    assert "[ok] SSH login to gitlab.com works" in capsys.readouterr().out


def test_http_host_reprompts_then_accepts(home, monkeypatch, capsys):
    feed(monkeypatch, ["http://gitlab.example.com", "gitlab.example.com"])
    assert wizard._ask_host("host: ", "gitlab.com") == ("gitlab.example.com", None)
    assert "HTTPS only" in capsys.readouterr().out


def test_custom_writes_config_block_once(home, monkeypatch):
    fake_key(home)
    monkeypatch.setattr(wizard.subprocess, "run", Recorder())
    for _ in range(2):
        feed(monkeypatch, ["git.example.com", "2222", "gitea", ""])
        assert wizard.setup_custom("ssh-ed25519 K") == ("git.example.com", 2222, "gitea")
    cfg = home / ".ssh/config"
    text = cfg.read_text()
    assert text.count("Host git.example.com") == 1
    assert "Port 2222" in text and "User gitea" in text
    assert cfg.stat().st_mode & 0o777 == 0o600
    assert (home / ".ssh").stat().st_mode & 0o777 == 0o700


def test_custom_default_port_and_user_write_no_config(home, monkeypatch):
    monkeypatch.setattr(wizard.subprocess, "run", Recorder())
    feed(monkeypatch, ["git.example.com", "", "", ""])
    assert wizard.setup_custom("k") == ("git.example.com", 22, "git")
    assert not (home / ".ssh/config").exists()


def test_add_another_host_loops(home, monkeypatch):
    fake_key(home)
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    monkeypatch.setattr(wizard, "is_git_identity_set", lambda: True)
    monkeypatch.setattr(wizard._OPENER, "open", _urlopen_returning(201))
    feed(monkeypatch, ["2", "", "y", "4", "git.example.com", "", "", "", "n", ""])
    assert run_main() == 0
    hosts = [c[-1] for c in rec.calls if c[0] == "ssh"]
    assert hosts == ["git@gitlab.com", "git@git.example.com"]


# -- role ----------------------------------------------------------------------

def _tasks():
    return yaml.safe_load((ROOT / "roles/github-setup/tasks/main.yml").read_text())


def test_role_has_no_lineinfile_wizard_hook():
    for task in _tasks():
        assert "ansible.builtin.lineinfile" not in task, task["name"]


def test_role_gates_hook_on_nikos_git_setup():
    hooks = [
        t for t in _tasks()
        if "nikos-github-wizard" in str(t.get("ansible.builtin.blockinfile", {}).get("block", ""))
    ]
    assert len(hooks) == 1
    assert "nikos_git_setup" in hooks[0]["ansible.builtin.blockinfile"]["state"]


def test_role_removes_old_hook_text():
    old = (
        '# NikOS first-run wizard (runs once on first login)\n'
        'if [[ ! -f "${HOME}/.config/nikos/github-configured" ]]; then\n'
        '  /usr/local/bin/nikos-github-wizard\n'
        'fi\n'
    )
    import re
    rep = [t for t in _tasks() if "ansible.builtin.replace" in t]
    assert rep
    pattern = rep[0]["ansible.builtin.replace"]["regexp"]
    assert re.sub(pattern, "", "a\n" + old + "b\n") == "a\nb\n"


def test_nikos_git_setup_default_is_ask():
    data = yaml.safe_load((ROOT / "vars/main.yml").read_text())
    assert data["nikos_git_setup"] == "ask"


def test_custom_does_not_shadow_existing_host_entry(home, monkeypatch):
    (home / ".ssh").mkdir()
    (home / ".ssh/config").write_text("Host git.example.com\n    Port 2200\n")
    monkeypatch.setattr(wizard.subprocess, "run", Recorder())
    feed(monkeypatch, ["git.example.com", "2222", "gitea", ""])
    wizard.setup_custom("k")
    assert (home / ".ssh/config").read_text().count("Host git.example.com") == 1


def test_dotfiles_refuses_option_like_input(home, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    feed(monkeypatch, ["--upload-pack=touch x@y"])
    wizard.step_dotfiles("GitLab", "gitlab.com", 22, "git")
    assert rec.calls == []


def test_dotfiles_shorthand_uses_provider_host(home, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    feed(monkeypatch, ["nik/dots"])
    wizard.step_dotfiles("Custom Git server", "git.example.com", 2222, "gitea")
    assert rec.calls[0][:3] == ["git", "clone", "ssh://gitea@git.example.com:2222/nik/dots.git"]


def test_flag_present_tells_user_how_to_rerun(home, monkeypatch, capsys):
    wizard.write_flag()
    assert run_main() == 0
    assert "--reset" in capsys.readouterr().out


def test_verify_ssh_does_not_read_the_terminal(monkeypatch):
    seen = {}

    def fake(cmd, **kw):
        seen.update(kw)
        return MagicMock(returncode=1, stdout="", stderr="Hi nik! You've successfully authenticated")

    monkeypatch.setattr(wizard.subprocess, "run", fake)
    assert wizard.verify_ssh("git", "github.com", 22) is True
    assert seen["stdin"] is wizard.subprocess.DEVNULL


def test_role_removes_every_duplicated_old_hook():
    # The old lineinfile never matched its own multi-line text, so each run
    # appended a copy; a real .bashrc had 25 of them.
    old = (
        '# NikOS first-run wizard (runs once on first login)\n'
        'if [[ ! -f "${HOME}/.config/nikos/github-configured" ]]; then\n'
        '  /usr/local/bin/nikos-github-wizard\n'
        'fi\n'
        '\n'
    )
    import re
    rep = [t for t in _tasks() if "ansible.builtin.replace" in t]
    pattern = rep[0]["ansible.builtin.replace"]["regexp"]
    assert re.sub(pattern, "", "a\n" + old * 25 + "b\n") == "a\nb\n"


def test_self_hosted_gitlab_uses_its_ssh_port(monkeypatch):
    answers = iter(["git.example.com", "2222"])
    monkeypatch.setattr(wizard, "ask", lambda _m: next(answers))
    monkeypatch.setattr(wizard, "ask_secret", lambda _m: TOKEN)
    monkeypatch.setattr(wizard, "gitlab_add_key", lambda *a: "added")
    seen = []
    monkeypatch.setattr(wizard, "verify_ssh", lambda u, h, p: seen.append((u, h, p)) or True)
    assert wizard.setup_gitlab("ssh-ed25519 K") == ("git.example.com", 2222, "git")
    assert seen == [("git", "git.example.com", 2222)]


def test_token_request_does_not_follow_redirects():
    # A followed redirect would resend PRIVATE-TOKEN / Authorization to the
    # new location, which may be http:// or another host.
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    hits = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append((self.path, self.headers.get("PRIVATE-TOKEN")))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{srv.server_port}/leak")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = wizard.urllib.request.Request(
            f"http://127.0.0.1:{srv.server_port}/api", data=b"{}", method="POST")
        req.add_header("PRIVATE-TOKEN", TOKEN)
        try:
            wizard._OPENER.open(req, timeout=5)
        except wizard.urllib.error.HTTPError as exc:
            assert exc.code == 302
    finally:
        srv.shutdown()
    assert [p for p, _ in hits] == ["/api"]


def test_missing_gh_shows_the_key_instead_of_crashing(monkeypatch, capsys):
    monkeypatch.setattr(wizard, "have", lambda cmd: cmd != "gh")
    monkeypatch.setattr(wizard.subprocess, "run", Recorder())
    assert wizard.setup_github("ssh-ed25519 K nikos") == ("github.com", 22, "git")
    out = capsys.readouterr().out
    assert "gh is not installed" in out and "ssh-ed25519 K nikos" in out


def test_missing_ssh_skips_the_login_check(monkeypatch, capsys):
    monkeypatch.setattr(wizard, "have", lambda cmd: cmd != "ssh")
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    assert wizard.verify_ssh("git", "example.com", 22) is False
    assert rec.calls == []


def test_custom_host_port_becomes_the_default(home, monkeypatch):
    monkeypatch.setattr(wizard, "SSH_DIR", home / ".ssh")
    monkeypatch.setattr(wizard.subprocess, "run", Recorder())
    answers = iter(["git.example.com:2222", "", "", ""])
    monkeypatch.setattr(wizard, "ask", lambda _m: next(answers))
    assert wizard.setup_custom("ssh-ed25519 K") == ("git.example.com", 2222, "git")
