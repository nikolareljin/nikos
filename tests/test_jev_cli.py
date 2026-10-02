"""Tests for roles/optional/jev: the jev command and its hash-pinned lock."""
import importlib.util
import stat
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "roles/optional/jev"
_spec = importlib.util.spec_from_file_location("jev_cli", ROLE / "files/jev.py")
jev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jev)

KEY = "ts-test-key-123"


@pytest.fixture(autouse=True)
def key_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    path = tmp_path / "typesafe" / "api_key"
    monkeypatch.setattr(jev, "KEY_FILE", path)
    return path


def test_login_stores_the_key_mode_600(key_file, monkeypatch, capsys):
    monkeypatch.setattr(jev.getpass, "getpass", lambda _p: f"  {KEY}  ")
    assert jev.main(["login"]) == 0
    assert key_file.read_text() == KEY + "\n"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert KEY not in capsys.readouterr().out


def test_login_with_nothing_entered_saves_nothing(key_file, monkeypatch):
    monkeypatch.setattr(jev.getpass, "getpass", lambda _p: "")
    assert jev.main(["login"]) == 1
    assert not key_file.exists()


def test_environment_key_wins(key_file, monkeypatch):
    jev.write_key("from-file")
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-env")
    assert jev.read_key() == "from-env"


def test_a_key_file_others_can_read_is_refused(key_file):
    jev.write_key(KEY)
    key_file.chmod(0o644)
    with pytest.raises(SystemExit) as exc:
        jev.read_key()
    assert "chmod 600" in str(exc.value)


def test_no_key_says_how_to_add_one(capsys):
    with pytest.raises(SystemExit) as exc:
        jev.main(["choose", "text", "a", "b"])
    assert "jev login" in str(exc.value)


def _fake_sdk(monkeypatch, response=None, error=None):
    """A stand-in typesafe_sdk, so no test reaches the network."""
    seen = {}

    class AuthError(Exception):
        pass

    class Client:
        def __init__(self, api_key):
            seen["api_key"] = api_key

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def system_one(self, state, questions):
            seen["state"], seen["questions"] = state, questions
            if error:
                raise error(AuthError)
            return response

    mod = types.ModuleType("typesafe_sdk")
    mod.TypeSafeClient = Client
    mod.TypeSafeAuthenticationError = AuthError
    mod.TypeSafeError = Exception
    mod.Choice = lambda **kw: ("choice", kw)
    mod.Score = lambda **kw: ("score", kw)
    monkeypatch.setitem(sys.modules, "typesafe_sdk", mod)
    return seen


def test_choose_prints_the_label_and_confidence(monkeypatch, capsys):
    jev.write_key(KEY)
    answer = SimpleNamespace(choice="billing", confidence=0.91,
                             probabilities={"billing": 0.91, "technical": 0.06, "other": 0.03})
    seen = _fake_sdk(monkeypatch, SimpleNamespace(choices={"answer": answer}))
    assert jev.main(["choose", "charged twice", "billing", "technical", "other"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "billing"
    assert "confidence 0.91" in out
    assert seen["api_key"] == KEY and seen["state"] == "charged twice"
    kind, kw = seen["questions"]["answer"]
    assert kind == "choice" and list(kw["criteria"]) == ["billing", "technical", "other"]
    assert KEY not in out


def test_choose_needs_two_labels(monkeypatch):
    jev.write_key(KEY)
    _fake_sdk(monkeypatch)
    with pytest.raises(SystemExit):
        jev.main(["choose", "text", "only-one"])


def test_score_sends_levels_in_order(monkeypatch, capsys):
    jev.write_key(KEY)
    answer = SimpleNamespace(score=1.7, confidence=0.6, probabilities={0: 0.1, 1: 0.1, 2: 0.8})
    seen = _fake_sdk(monkeypatch, SimpleNamespace(scores={"answer": answer}))
    monkeypatch.setattr(jev.sys, "stdin", __import__("io").StringIO("from stdin"))
    assert jev.main(["score", "-", "angry", "neutral", "happy"]) == 0
    assert seen["state"] == "from stdin"
    assert capsys.readouterr().out.splitlines()[0] == "1.70"
    kind, kw = seen["questions"]["answer"]
    assert kind == "score" and kw["criteria"] == ["angry", "neutral", "happy"]


def test_a_rejected_key_says_to_log_in_again(monkeypatch):
    jev.write_key(KEY)
    _fake_sdk(monkeypatch, error=lambda auth: auth("401"))
    with pytest.raises(SystemExit) as exc:
        jev.main(["choose", "t", "a", "b"])
    assert "jev login" in str(exc.value) and KEY not in str(exc.value)


def test_lock_pins_every_package_by_hash():
    lines = (ROLE / "files/requirements.lock").read_text().splitlines()
    pins = [l for l in lines if l and not l[0].isspace() and not l.startswith("#")]
    assert pins, "empty lock"
    for pin in pins:
        assert "==" in pin and pin.rstrip().endswith("\\"), pin
    assert any(p.startswith("typesafe-sdk==") for p in pins)
    assert sum("--hash=sha256:" in l for l in lines) >= len(pins)


def test_role_installs_with_require_hashes():
    import yaml

    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    pip = [t for t in tasks if "pip" in str(t.get("ansible.builtin.command", {}).get("argv", ""))]
    assert len(pip) == 1
    argv = pip[0]["ansible.builtin.command"]["argv"]
    assert "--require-hashes" in argv and "--only-binary=:all:" in argv


def test_an_existing_world_readable_key_file_is_tightened_before_writing(key_file, monkeypatch):
    key_file.parent.mkdir(parents=True)
    key_file.write_text("old\n")
    key_file.chmod(0o644)
    modes = []
    real_fdopen = jev.os.fdopen

    def spy(fd, *a, **kw):
        modes.append(stat.S_IMODE(jev.os.fstat(fd).st_mode))
        return real_fdopen(fd, *a, **kw)
    monkeypatch.setattr(jev.os, "fdopen", spy)
    jev.write_key(KEY)
    assert modes == [0o600]
    assert key_file.read_text() == KEY + "\n"


def test_choose_refuses_duplicate_labels(monkeypatch):
    jev.write_key(KEY)
    _fake_sdk(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        jev.main(["choose", "t", "yes", "yes"])
    assert "different" in str(exc.value)

