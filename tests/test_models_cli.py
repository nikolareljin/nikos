"""`nikos models` and the removal offer an update makes (scripts/nikos).

A fake Ollama answers /api/tags and records /api/delete. The approved set is the
real ai-models.env, picked by the real script-helpers with the class named
(nikos_ai_model_tier: standard), so the machine running the tests does not
change the answer.
"""

import json
import os
import sys
import pty
import select
import subprocess
import threading
import time
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
    # NIKOS_USE_DIALOG=0: these tests answer the text questions. The checklist
    # has its own tests, which take the setting out.
    return {**os.environ, "NIKOS_HOME": str(nikos), "XDG_STATE_HOME": str(state), "HOME": str(tmp_path),
            "NO_COLOR": "1", "NIKOS_USE_DIALOG": "0"}


def nikos(env, *args):
    return subprocess.run(["bash", str(ROOT / "scripts/nikos"), *args], env=env, capture_output=True,
                          text=True, timeout=60, stdin=subprocess.DEVNULL)


def on_tty(env, answers, *args):
    """Runs nikos with a terminal as its controlling tty, typing the answers."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("bash", ["bash", str(ROOT / "scripts/nikos"), *args], env)
    out = b""
    deadline = time.time() + 60

    def read_some():
        """One chunk, or b"" at end of output. A question nobody answers must
        fail the test, not hang it."""
        while True:
            if time.time() > deadline:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                raise AssertionError("nikos is still waiting: " + out.decode(errors="replace")[-400:])
            if select.select([fd], [], [], 1)[0]:
                try:
                    return os.read(fd, 4096)
                except OSError:
                    return b""

    for a in answers:
        while b"[y/N]" not in out.split(b"\n")[-1]:
            chunk = read_some()
            if chunk == b"":
                break
            out += chunk
        os.write(fd, a.encode() + b"\n")
    while True:
        chunk = read_some()
        if chunk == b"":
            break
        out += chunk
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
    commands = {
        None: ["ansible-playbook", "-i", "localhost,", "play.yml"],
        "ollama-coding": ["ansible-playbook", "-i", "localhost,", "play.yml", "--tags", "ollama-coding"],
        "ollama-models": ["ansible-playbook", "-i", "localhost,", "play.yml", "--tags", "ollama-models"],
    }
    r = subprocess.run(commands[tags], cwd=tmp_path, capture_output=True, text=True, timeout=180,
                       env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, stdin=subprocess.DEVNULL)
    calls = (tmp_path / "calls").read_text().splitlines() if (tmp_path / "calls").exists() else []
    return r, calls


def test_a_plain_run_pulls_only_the_default_module(tmp_path):
    r, calls = run_play(tmp_path)
    assert r.returncode == 0, r.stdout[-2000:]
    assert len(calls) == 1 and calls[0].endswith("http://127.0.0.1:11434 OLLAMA_MODEL OLLAMA_CODE_MODEL")
    assert calls[0].startswith("|1|ensure ") and "/ai-models.env " in calls[0]


def test_a_selected_module_pulls_its_roles_with_the_class_named(tmp_path):
    r, calls = run_play(tmp_path, tags="ollama-coding", tier="large")
    assert r.returncode == 0, r.stdout[-2000:]
    assert calls == [c for c in calls if c.startswith("large|1|")] and len(calls) == 1
    assert calls[0].endswith(" OLLAMA_CODE_MODEL")


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("small", "granite4.1:3b"),
        ("standard", "qwen2.5-coder:7b"),
        ("medium", "qwen2.5-coder:7b"),
        ("large", "qwen3-coder:30b"),
        ("xlarge", "qwen3.6:27b-coding"),
    ],
)
def test_hosts_resolve_the_approved_code_model_for_their_tier(home, tier, expected):
    local = Path(home["NIKOS_HOME"]) / "vars/local.yml"
    local.write_text(
        local.read_text().replace('nikos_ai_model_tier: "standard"', f'nikos_ai_model_tier: "{tier}"')
    )
    result = nikos(home, "models")
    assert result.returncode == 0, result.stderr
    assert f"OLLAMA_CODE_MODEL={expected}" in result.stdout


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


def test_a_model_a_repository_remembers_is_not_offered(home, tmp_path, ollama):
    """A repository's .env choice keeps its model off the removal offer."""
    repo = tmp_path / "Projects" / "some-app"
    repo.mkdir(parents=True)
    (repo / ".env").write_text('OLLAMA_CODE_MODEL_CHOICE="qwen2.5:7b"\nOTHER=1\n')
    out = on_tty(home, ["y"], "models", "prune")
    assert "Remove gpt-oss:20b?" in out
    assert "qwen2.5:7b" not in out.split("outside")[-1]
    assert ollama[1] == ["gpt-oss:20b"]


@pytest.mark.parametrize(
    "env_text",
    [
        "AI_MODEL_CODE_CHOICE=qwen2.5:7b\n",            # what `select` stores with no NAME
        "CODE_LLM_CHOICE=qwen2.5:7b\n",                 # `select` with a NAME of the repository's own
        "ollama_model=qwen2.5:7b\n",
        "\ufeffOLLAMA_MODEL=qwen2.5:7b\n",              # a byte order mark on the first line
        "export OLLAMA_MODEL='qwen2.5:7b'  # note\r\n",
    ],
)
def test_every_spelling_of_a_remembered_model_is_kept(home, tmp_path, env_text):
    repo = tmp_path / "Projects" / "some-app"
    repo.mkdir(parents=True)
    (repo / ".env").write_text(env_text, encoding="utf-8", newline="")
    r = nikos(home, "models")
    assert r.returncode == 0, r.stderr
    outside = r.stdout.split("outside the set")[1].split()
    assert "gpt-oss:20b" in outside and "qwen2.5:7b" not in outside


def test_a_remembered_model_with_an_underscore_in_its_tag_is_kept(home, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "INSTALLED", [*INSTALLED, "llama3.1:8b-instruct-q4_K_M"])
    r = nikos(home, "models")
    assert "llama3.1:8b-instruct-q4_K_M" in r.stdout.split("outside the set")[1].split()
    repo = tmp_path / "Projects" / "some-app"
    repo.mkdir(parents=True)
    (repo / ".env").write_text("OLLAMA_MODEL=llama3.1:8b-instruct-q4_K_M\n")
    r = nikos(home, "models")
    assert r.returncode == 0, r.stderr
    assert "llama3.1:8b-instruct-q4_K_M" not in r.stdout.split("outside the set")[1].split()


def with_tiers_line(home, line):
    """A copy of the script-helpers tree whose tiers file has one more line."""
    nikos_home = Path(home["NIKOS_HOME"])
    (nikos_home / "scripts").unlink()
    (nikos_home / "scripts").mkdir()
    for child in (ROOT / "scripts").iterdir():
        if child.name != "script-helpers":
            (nikos_home / "scripts" / child.name).symlink_to(child)
    helpers = nikos_home / "scripts" / "script-helpers"
    helpers.mkdir()
    for child in (ROOT / "scripts/script-helpers").iterdir():
        if child.name != "config":
            (helpers / child.name).symlink_to(child)
    (helpers / "config").mkdir()
    tiers = (ROOT / "scripts/script-helpers/config/ollama_model_tiers.txt").read_text()
    (helpers / "config/ollama_model_tiers.txt").write_text(tiers + line + "\n")


def outside_the_set(home):
    r = nikos(home, "models")
    assert r.returncode == 0, r.stderr
    return r.stdout.split("outside the set")[1].split()


def test_a_tier_pick_for_any_type_is_not_offered(home, ollama):
    """qwen2.5:7b stays installed when it is a tier pick, not only a role pick."""
    with_tiers_line(home, "type extra-test qwen2.5:7b qwen2.5:7b qwen2.5:7b qwen2.5:7b")
    outside = outside_the_set(home)
    assert "gpt-oss:20b" in outside and "qwen2.5:7b" not in outside


def test_a_lower_tier_pick_is_kept_and_a_higher_one_is_not(home, ollama):
    """`select` falls back to a lower tier's model under a size floor, so the
    lower columns are kept. This machine is `standard` (the second column)."""
    with_tiers_line(home, "type extra-test qwen2.5:7b other:1b gpt-oss:20b gpt-oss:20b")
    outside = outside_the_set(home)
    assert "qwen2.5:7b" not in outside   # the small column
    assert "gpt-oss:20b" in outside      # only the large and xlarge columns


def with_stub_dialog(home, tmp_path, checklist_script):
    """The environment with dialog switched on and a stub dialog first on PATH."""
    bindir = tmp_path / "dialogbin"
    bindir.mkdir()
    log = tmp_path / "dialog.log"
    (bindir / "dialog").write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'case " $* " in\n'
        f"  *' --checklist '*) {checklist_script} ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    (bindir / "dialog").chmod(0o755)
    env = {k: v for k, v in home.items() if k != "NIKOS_USE_DIALOG"}
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["TERM"] = "xterm"
    return env, log


def test_with_dialog_the_offer_is_one_checklist_and_checked_models_are_removed(home, tmp_path, ollama):
    env, log = with_stub_dialog(home, tmp_path, 'printf "gpt-oss:20b\\n"; exit 0')
    out = on_tty(env, [], "models", "prune")
    calls = log.read_text().splitlines()
    checklists = [c for c in calls if "--checklist" in c]
    assert len(checklists) == 1, calls
    assert "gpt-oss:20b  off" in checklists[0] and "qwen2.5:7b  off" in checklists[0]   # nothing checked
    assert "qwen3.5:4b" not in checklists[0]                                           # a pick is not offered
    assert "[y/N]" not in out
    assert ollama[1] == ["gpt-oss:20b"]
    assert "Removed 1 model(s)." in out


@pytest.mark.parametrize("code", [1, 255])
def test_cancel_or_esc_in_the_checklist_removes_nothing(home, tmp_path, ollama, code):
    # Prints a name first, so a result read despite the exit code would remove it.
    env, log = with_stub_dialog(home, tmp_path, f"echo gpt-oss:20b; exit {code}")
    out = on_tty(env, [], "models", "prune")
    assert any("--checklist" in c for c in log.read_text().splitlines())
    assert ollama[1] == []
    assert "Removed" not in out


def test_the_checklist_does_not_erase_the_terminal(home, tmp_path, ollama):
    env, _ = with_stub_dialog(home, tmp_path, "exit 1")
    env["TERM"] = "xterm"
    assert "\x1b[2J" not in on_tty(env, [], "models", "prune")


def test_a_checklist_that_cannot_draw_falls_back_to_the_text_questions(home, tmp_path, ollama):
    env, log = with_stub_dialog(home, tmp_path, 'exit "${DIALOG_ERROR:-255}"')
    out = on_tty(env, ["y", "n"], "models", "prune")
    assert any("--checklist" in c for c in log.read_text().splitlines())
    assert "Remove gpt-oss:20b? [y/N]" in out
    assert ollama[1] == ["gpt-oss:20b"]


def test_the_question_boxes_keep_the_normal_screen():
    # A stub dialog cannot show this: the real one draws over the normal screen
    # without --keep-tite, and a clear after the box erases the sync output.
    text = (Path(__file__).resolve().parent.parent / "scripts" / "nikos").read_text()
    for call in ("--passwordbox", "--checklist"):
        start = text.index(call)
        line = text.rfind("dialog ", 0, start)
        assert "--keep-tite" in text[line:start], call
        after = text[start:]
        assert after.index("_leave_box") < after.find("_leave_tui") or "_leave_tui" not in after


def test_leaving_a_box_does_not_restore_the_screen_twice():
    text = (Path(__file__).resolve().parent.parent / "scripts" / "nikos").read_text()
    body = text[text.index("_leave_box() {"):]
    body = body[: body.index("\n}\n")]
    assert "rmcup" not in body and "clear" not in body
