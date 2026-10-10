"""`nikos models` and the removal offer an update makes (scripts/nikos).

A fake Ollama answers /api/tags and records /api/delete. The approved set is the
real ai-models.env, picked by the real script-helpers with the class named
(nikos_ai_model_tier: standard), so the machine running the tests does not
change the answer.
"""

import json
import os
import pty
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALLED = ["qwen3.5:4b", "nomic-embed-text:latest", "gpt-oss:20b", "qwen2.5:7b", "Kept:1b"]


@pytest.fixture
def ollama():
    deleted = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body):
            data = json.dumps(body, separators=(",", ":")).encode()  # as Ollama sends it
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/version":
                self._send({"version": "0.12.0"})
            else:
                self._send({"models": [{"name": m} for m in INSTALLED]})

        def do_DELETE(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            deleted.append(body["model"])
            self._send({})

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], deleted
    srv.shutdown()


@pytest.fixture
def home(tmp_path, ollama):
    port, _ = ollama
    nikos = tmp_path / "nikos"
    (nikos / "vars").mkdir(parents=True)
    (nikos / "scripts").symlink_to(ROOT / "scripts")
    (nikos / "ai-models.env").symlink_to(ROOT / "ai-models.env")
    (nikos / "vars/main.yml").write_text((ROOT / "vars/main.yml").read_text())
    (nikos / "vars/local.yml").write_text(f'nikos_ollama_host: "127.0.0.1:{port}"\nnikos_ai_model_tier: "standard"\n')
    state = tmp_path / "state"
    (state / "nikos").mkdir(parents=True)
    (state / "nikos/models-extra").write_text("Kept:1b\n")
    return {**os.environ, "NIKOS_HOME": str(nikos), "XDG_STATE_HOME": str(state), "HOME": str(tmp_path), "NO_COLOR": "1"}


def nikos(env, *args):
    return subprocess.run(["bash", str(ROOT / "scripts/nikos"), *args], env=env, capture_output=True,
                          text=True, timeout=60, stdin=subprocess.DEVNULL)


def on_tty(env, answers, *args):
    """Runs nikos with a terminal as its controlling tty, typing the answers."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("bash", ["bash", str(ROOT / "scripts/nikos"), *args], env)
    out = b""
    for a in answers:
        while b"[y/N]" not in out.split(b"\n")[-1]:
            out += os.read(fd, 4096)
        os.write(fd, a.encode() + b"\n")
        out += os.read(fd, 4096)
    try:
        while chunk := os.read(fd, 4096):
            out += chunk
    except OSError:
        pass
    os.waitpid(pid, 0)
    return out.decode(errors="replace")


def test_show_names_the_models_outside_the_set(home):
    r = nikos(home, "models")
    assert r.returncode == 0, r.stderr
    outside = r.stdout.split("outside the set")[1].split()
    assert "gpt-oss:20b" in outside and "qwen2.5:7b" in outside
    # The picks, with or without :latest, and the kept extra are not outside.
    assert "qwen3.5:4b" not in outside and "nomic-embed-text:latest" not in outside and "Kept:1b" not in outside


def test_without_a_terminal_nothing_is_removed(home, ollama):
    r = nikos(home, "models", "prune")
    assert r.returncode == 0, r.stderr
    assert "not removed, no terminal" in r.stdout + r.stderr
    assert ollama[1] == []


def test_on_a_terminal_each_model_is_asked_about(home, ollama):
    out = on_tty(home, ["y", ""], "models", "prune")
    assert "Remove gpt-oss:20b?" in out and "Remove qwen2.5:7b?" in out
    assert ollama[1] == ["gpt-oss:20b"]


def test_add_model_rejects_a_bad_name(home):
    r = nikos(home, "add", "model", "x;rm -rf /")
    assert r.returncode == 2


def test_update_offers_removal_before_the_playbook():
    cli = (ROOT / "scripts/nikos").read_text()
    body = cli.split("cmd_update() {")[1].split("\n}\n")[0]
    assert body.index("_models_offer_removal") < body.index("_playbook -e nikos_update_mode=true")




import yaml  # noqa: E402

TASKS = yaml.safe_load((ROOT / "roles/ai-stack/tasks/main.yml").read_text())
VARS = yaml.safe_load((ROOT / "vars/main.yml").read_text())
MODULES = ("default", "text", "reasoning", "coding", "vision", "embedding", "models")



def run_play(tmp_path, tags=None, tier=""):
    """The model tasks, with ollama_models.sh as a stub that logs its arguments."""
    stub = tmp_path / "scripts/script-helpers/scripts/ollama_models.sh"
    stub.parent.mkdir(parents=True)
    stub.write_text(f'#!/bin/sh\necho "$AI_MODEL_TIER|$OLLAMA_PULL_MISSING|$*" >> {tmp_path}/calls\n')
    stub.chmod(0o755)
    tasks = [{k: v for k, v in t.items() if k != "become"} for t in TASKS
             if "ai_stack_models_" in str(t.get("register", "")) + str(t.get("when", ""))]
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ai_stack_model_modules": VARS["ai_stack_model_modules"], "nikos_ollama_mode": "local",
                      "nikos_ollama_host": "127.0.0.1:11434", "nikos_ai_model_tier": tier},
             "tasks": tasks}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    cmd = ["ansible-playbook", "-i", "localhost,", "play.yml"] + (["--tags", tags] if tags else [])
    r = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, timeout=180,
                       env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, stdin=subprocess.DEVNULL)
    calls = (tmp_path / "calls").read_text().splitlines() if (tmp_path / "calls").exists() else []
    return r, calls


def test_a_plain_run_pulls_only_the_default_module(tmp_path):
    r, calls = run_play(tmp_path)
    assert r.returncode == 0, r.stdout[-2000:]
    assert len(calls) == 1 and calls[0].endswith("http://127.0.0.1:11434 OLLAMA_MODEL")
    assert calls[0].startswith("|1|ensure ") and "/ai-models.env " in calls[0]


def test_a_selected_module_pulls_its_roles_with_the_class_named(tmp_path):
    r, calls = run_play(tmp_path, tags="ollama-coding", tier="large")
    assert r.returncode == 0, r.stdout[-2000:]
    assert calls == [c for c in calls if c.startswith("large|1|")] and len(calls) == 1
    assert calls[0].endswith(" OLLAMA_CODE_MODEL")


def test_ollama_models_pulls_every_role(tmp_path):
    r, calls = run_play(tmp_path, tags="ollama-models")
    assert r.returncode == 0, r.stdout[-2000:]
    # Every module runs; "models" passes no names, so every role in the file.
    assert any(c.endswith("http://127.0.0.1:11434") for c in calls)


@pytest.mark.parametrize("module", MODULES)
def test_every_module_names_roles_the_models_file_has(module):
    names = {line.split("=")[0] for line in (ROOT / "ai-models.env").read_text().splitlines()
             if line and not line.startswith("#")}
    assert set(VARS["ai_stack_model_modules"][module]) <= names
