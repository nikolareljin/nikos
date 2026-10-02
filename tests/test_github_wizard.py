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
import json
import urllib.error

import pytest
import yaml

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
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(201, seen=seen))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "ssh-ed25519 K") == "added"
    req = seen[0]
    assert req.full_url == "https://gitlab.com/api/v4/user/keys"
    assert req.get_header("Private-token") == TOKEN
    assert json.loads(req.data) == {"title": "nikos", "key": "ssh-ed25519 K"}


def test_gitlab_400_duplicate_is_present(monkeypatch):
    err = http_error(400, '{"message":{"fingerprint":["has already been taken"]}}')
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "present"


def test_gitlab_400_other_is_error(monkeypatch):
    err = http_error(400, '{"message":"key is invalid"}')
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "error"


def test_gitlab_401_bad_token(monkeypatch):
    err = http_error(401, '{"message":"401 Unauthorized"}')
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "badtoken"


def test_bitbucket_201_added(monkeypatch):
    seen = []
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(201, seen=seen))
    assert wizard.bitbucket_add_key("nik", TOKEN, "k") == "added"
    assert seen[0].full_url == "https://api.bitbucket.org/2.0/users/nik/ssh-keys"
    assert seen[0].get_header("Authorization").startswith("Basic ")


def test_bitbucket_401_bad_token(monkeypatch):
    monkeypatch.setattr(
        wizard.urllib.request, "urlopen", _urlopen_returning(error=http_error(401, ""))
    )
    assert wizard.bitbucket_add_key("nik", TOKEN, "k") == "badtoken"


def test_network_error_is_error(monkeypatch):
    err = urllib.error.URLError("no route")
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(error=err))
    assert wizard.gitlab_add_key("gitlab.com", None, TOKEN, "k") == "error"


def test_gitlab_flow_token_never_in_argv_or_output(home, monkeypatch, capsys):
    fake_key(home)
    rec = Recorder()
    monkeypatch.setattr(wizard.subprocess, "run", rec)
    monkeypatch.setattr(wizard, "is_git_identity_set", lambda: True)
    monkeypatch.setattr(
        wizard.urllib.request, "urlopen", _urlopen_returning(error=http_error(401, ""))
    )
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
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(201))
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
    monkeypatch.setattr(wizard.urllib.request, "urlopen", _urlopen_returning(201))
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
