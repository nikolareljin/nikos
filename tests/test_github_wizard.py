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
