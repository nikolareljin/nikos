"""scripts/bump-versions.py against a fake upstream: no network."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bump_versions", REPO / "scripts" / "bump-versions.py")
bump = importlib.util.module_from_spec(_spec)
sys.modules["bump_versions"] = bump
_spec.loader.exec_module(bump)

NOW = dt.datetime.now(dt.timezone.utc)


def ago(days: float) -> str:
    return (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeHttp(bump.Http):
    def __init__(self, routes: dict):
        self.routes = routes
        self.fetched: list[str] = []

    def get(self, url, headers=None):
        self.fetched.append(url)
        for prefix, body in self.routes.items():
            if url == prefix or (prefix.endswith("*") and url.startswith(prefix[:-1])):
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise bump.NotFound(f"{url}: 404 Not Found")

    def json(self, url, headers=None):
        return json.loads(self.get(url, headers))

    def sha256(self, url):
        return sha(self.get(url))


OLD = b"tool 1.0.0 bytes"
NEW = b"tool 1.2.0 bytes"

VERSIONS = f"""---
# A comment that must survive.
tool_version: "v1.0.0"   # trailing comment stays
tool_sha256: "{sha(OLD)}"
other_version: "v1.0.0"
pip_pins:
  requests: "2.0.0"
  # inner comment
  idna: "3.0"
repo_key_fingerprints:
  - "AAAA"
nikos_pin_sources:
  tool:
    type: github-release
    repo: acme/tool
    version_var: tool_version
    artifacts:
      - {{asset: tool-linux.tar.gz, sha256_var: tool_sha256, checksums: SHA256SUMS}}
  pip_pins:
    type: pypi-map
    version_var: pip_pins
    python: ["3.11", "3.12"]
  repo_key:
    type: apt-key
    url: https://example.invalid/key.asc
    fingerprints_var: repo_key_fingerprints
"""

DL = "https://github.com/acme/tool/releases/download"


def releases(*items):
    return [{"tag_name": t, "draft": d, "prerelease": p, "published_at": when}
            for t, d, p, when in items]


def routes(new_sums: bytes | None = None, new_bytes: bytes = NEW) -> dict:
    return {
        "https://api.github.com/repos/acme/tool/releases*": releases(
            ("v1.3.0", False, True, ago(10)),         # marked pre-release: skipped
            ("v1.2.5-rc1", False, False, ago(10)),    # pre-release by name: skipped
            ("v1.4.0", False, False, ago(1)),         # too new: skipped
            ("v1.9.0", True, False, ago(20)),         # draft: skipped
            ("v1.2.0", False, False, ago(5)),         # the newest eligible
            ("v1.0.0", False, False, ago(30)),
        ),
        f"{DL}/v1.2.0/tool-linux.tar.gz": new_bytes,
        f"{DL}/v1.2.0/SHA256SUMS": new_sums if new_sums is not None
        else f"{sha(NEW)}  tool-linux.tar.gz\n{'0' * 64}  tool-other.tar.gz\n".encode(),
        f"{DL}/v1.0.0/tool-linux.tar.gz": OLD,
        f"{DL}/v1.0.0/SHA256SUMS": f"{sha(OLD)}  ./tool-linux.tar.gz\n".encode(),
    }


@pytest.fixture
def vfile(tmp_path: Path) -> Path:
    path = tmp_path / "versions.yml"
    path.write_text(VERSIONS, encoding="utf-8")
    return path


def pins(path: Path, http) -> "bump.Pins":
    _, versions = bump.load(path)
    return bump.Pins(versions, http, 3)


def test_newest_eligible_skips_prerelease_draft_and_too_new(vfile: Path) -> None:
    p = pins(vfile, FakeHttp(routes()))
    assert p.newest("tool", p.v["nikos_pin_sources"]["tool"]).version == "v1.2.0"
    # With no age limit the two-day-old release is eligible; the draft and
    # the pre-release still are not.
    _, versions = bump.load(vfile)
    assert bump.Pins(versions, FakeHttp(routes()), 0).newest_release(versions["nikos_pin_sources"]["tool"]) == "v1.4.0"


@pytest.mark.parametrize("version,pre", [("1.0.0rc1", True), ("4.7.0a2", True), ("0.64.0-nightly.1", True),
                                         ("v1.2.3", False), ("2026.8.33", False), ("2.14.1+cpu", False)])
def test_prerelease_detection(version: str, pre: bool) -> None:
    assert bump.is_prerelease(version) is pre


def test_bump_rewrites_only_the_target_lines(vfile: Path) -> None:
    before = vfile.read_text(encoding="utf-8")
    rc = bump.main(["--bump", "tool", "--no-tests"], http=FakeHttp(routes()), path=vfile)
    assert rc == 0
    after = vfile.read_text(encoding="utf-8")
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert changed == [
        ('tool_version: "v1.0.0"   # trailing comment stays', 'tool_version: "v1.2.0"   # trailing comment stays'),
        (f'tool_sha256: "{sha(OLD)}"', f'tool_sha256: "{sha(NEW)}"'),
    ]
    assert len(before.splitlines()) == len(after.splitlines())


def test_rewrite_reaches_into_a_mapping_and_keeps_comments() -> None:
    out = bump.rewrite(VERSIONS, {"pip_pins.idna": "3.10"})
    assert '  idna: "3.10"\n' in out and "  # inner comment\n" in out
    assert out.replace('  idna: "3.10"', '  idna: "3.0"') == VERSIONS
    with pytest.raises(ValueError):
        bump.rewrite(VERSIONS, {"missing_version": "1"})


def test_a_checksum_mismatch_skips_the_pin_and_fails(vfile: Path, capsys) -> None:
    before = vfile.read_text(encoding="utf-8")
    bad = f"{'f' * 64}  tool-linux.tar.gz\n".encode()
    rc = bump.main(["--bump", "tool", "--no-tests"], http=FakeHttp(routes(new_sums=bad)), path=vfile)
    assert rc == 1
    assert vfile.read_text(encoding="utf-8") == before
    assert "checksum mismatch" in capsys.readouterr().out


def test_a_changed_apt_key_is_reported_not_written(vfile: Path, monkeypatch, capsys) -> None:
    before = vfile.read_text(encoding="utf-8")
    monkeypatch.setattr(bump.Pins, "key_fingerprints", lambda self, src: ["BBBB"])
    rc = bump.main(["--bump", "repo_key", "--no-tests"], http=FakeHttp({}), path=vfile)
    assert rc == 0
    assert vfile.read_text(encoding="utf-8") == before
    assert "CHANGED - needs a person" in capsys.readouterr().out
    assert bump.main(["--verify", "repo_key"], http=FakeHttp({}), path=vfile) == 1


def test_a_pypi_group_is_reported_not_bumped_without_uv(vfile: Path, capsys, monkeypatch) -> None:
    def no_uv(requirements, python, extra_index):
        raise FileNotFoundError("uv")
    monkeypatch.setattr(bump, "uv_resolve", no_uv)
    http = FakeHttp({
        "https://pypi.org/pypi/requests/json": {"releases": {
            "2.0.0": [{"upload_time_iso_8601": ago(400)}],
            "2.5.0": [{"upload_time_iso_8601": ago(10)}],
            "3.0.0b1": [{"upload_time_iso_8601": ago(10)}],
        }},
        "https://pypi.org/pypi/idna/json": {"releases": {"3.0": [{"upload_time_iso_8601": ago(400)}]}},
    })
    before = vfile.read_text(encoding="utf-8")
    assert bump.main(["--bump", "pip_pins", "--no-tests"], http=http, path=vfile) == 0
    assert vfile.read_text(encoding="utf-8") == before
    assert "requests 2.0.0 -> 2.5.0" in capsys.readouterr().out
    assert bump.main(["--bump", "pip_pins.requests", "--no-tests"], http=http, path=vfile) == 0
    assert '  requests: "2.5.0"\n' in vfile.read_text(encoding="utf-8")


def _pip_http() -> FakeHttp:
    return FakeHttp({
        "https://pypi.org/pypi/requests/json": {"releases": {
            "2.0.0": [{"upload_time_iso_8601": ago(400)}], "2.5.0": [{"upload_time_iso_8601": ago(10)}]}},
        "https://pypi.org/pypi/idna/json": {"releases": {
            "3.0": [{"upload_time_iso_8601": ago(400)}], "4.0": [{"upload_time_iso_8601": ago(10)}]}},
    })


def test_a_pypi_group_moves_together_when_it_resolves(vfile: Path, capsys, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(bump, "uv_resolve", lambda reqs, python, index: calls.append((reqs, python, index)))
    assert bump.main(["--bump", "pip_pins", "--no-tests"], http=_pip_http(), path=vfile) == 0
    text = vfile.read_text(encoding="utf-8")
    assert '  requests: "2.5.0"\n' in text and '  idna: "4.0"\n' in text and "# inner comment" in text
    assert calls == [(["requests==2.5.0", "idna==4.0"], "3.11", None),
                     (["requests==2.5.0", "idna==4.0"], "3.12", None)]


def test_a_pypi_package_that_breaks_the_set_is_held_back(vfile: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(bump, "uv_resolve",
                        lambda reqs, python, index: "no solution" if "idna==4.0" in reqs else None)
    assert bump.main(["--bump", "pip_pins", "--no-tests"], http=_pip_http(), path=vfile) == 0
    text = vfile.read_text(encoding="utf-8")
    assert '  requests: "2.5.0"\n' in text and '  idna: "3.0"\n' in text
    assert "held back, does not resolve with the rest: idna 4.0" in capsys.readouterr().out


def test_a_resolve_alone_package_is_resolved_by_itself(vfile: Path, monkeypatch) -> None:
    vfile.write_text(vfile.read_text(encoding="utf-8").replace(
        '    python: ["3.11", "3.12"]\n', '    python: ["3.12"]\n    resolve_alone: [idna]\n    extra_index: https://example.invalid/whl\n'),
        encoding="utf-8")
    calls = []
    monkeypatch.setattr(bump, "uv_resolve", lambda reqs, python, index: calls.append((reqs, python, index)))
    assert bump.main(["--bump", "pip_pins", "--no-tests"], http=_pip_http(), path=vfile) == 0
    assert calls == [(["idna==4.0"], "3.12", "https://example.invalid/whl"),
                     (["requests==2.5.0"], "3.12", "https://example.invalid/whl")]


@pytest.mark.parametrize(
    "spec,minor,ok",
    [
        (">=3.12", "3.11", False), (">=3.12", "3.12", True), (">=3.11", "3.11", True),
        ("<3.13,>=3.10", "3.12", True), ("<3.13,>=3.10", "3.13", False), ("<4", "3.13", True),
        (">=3.9.1", "3.9", True), ("!=3.11.*,>=3.8", "3.11", False), ("~=3.9", "3.12", True),
        ("~=3.9", "4.0", False), ("=3.12", "3.12", True), ("=3.12", "3.11", False),
        ("==3.12.*", "3.12", True), (">3.11", "3.11", False), ("<=3.12", "3.12", True), ("", "3.11", True),
    ],
)
def test_python_allows(spec: str, minor: str, ok: bool) -> None:
    assert bump.python_allows(spec, minor) is ok


def test_python_allows_refuses_a_spec_it_cannot_read() -> None:
    with pytest.raises(ValueError):
        bump.python_allows("3.12", "3.12")


def test_a_pip_pin_must_install_on_every_python_of_the_env(vfile: Path, capsys) -> None:
    def http(requests_200: str) -> FakeHttp:
        return FakeHttp({
            "https://pypi.org/pypi/requests/json": {"releases": {
                "2.0.0": [{"upload_time_iso_8601": ago(400), "requires_python": requests_200}],
                "2.4.0": [{"upload_time_iso_8601": ago(20), "requires_python": "<3.13,>=3.10"}],
                "2.5.0": [{"upload_time_iso_8601": ago(10), "requires_python": ">=3.12"}],
                "2.6.0": [{"upload_time_iso_8601": ago(10), "requires_python": ">=3.6.0rc1"}],  # unreadable: skipped
            }},
            "https://pypi.org/pypi/idna/json": {"releases": {"3.0": [{"upload_time_iso_8601": ago(400)}]}},
        })
    assert bump.main(["--verify", "pip_pins"], http=http(">=3.8"), path=vfile) == 0
    capsys.readouterr()
    assert bump.main(["--verify", "pip_pins"], http=http(">=3.12"), path=vfile) == 1
    assert "requests==2.0.0 does not install on Python 3.11 (Requires-Python >=3.12)" in capsys.readouterr().out
    assert bump.main(["--verify", "pip_pins.requests"], http=http(">=3.12"), path=vfile) == 1
    assert bump.main(["--verify", "pip_pins"], http=http("3.8+"), path=vfile) == 1
    # 2.5.0 is the newest, but needs 3.12: the bump stops at 2.4.0.
    assert bump.main(["--bump", "pip_pins.requests", "--no-tests"], http=http(">=3.8"), path=vfile) == 0
    assert '  requests: "2.4.0"\n' in vfile.read_text(encoding="utf-8")


def test_verify_passes_on_the_recorded_pin_and_catches_a_wrong_hash(vfile: Path, capsys) -> None:
    assert bump.main(["--verify", "tool"], http=FakeHttp(routes()), path=vfile) == 0
    wrong = routes()
    wrong[f"{DL}/v1.0.0/tool-linux.tar.gz"] = b"swapped upstream"
    assert bump.main(["--verify", "tool"], http=FakeHttp(wrong), path=vfile) == 1
    assert "FAIL" in capsys.readouterr().out


def test_bump_restores_the_file_when_the_new_pin_fails_verification(vfile: Path) -> None:
    # The vendor's sums file and the first download agree, but the artifact
    # served on the verification pass differs: the old file comes back.
    before = vfile.read_text(encoding="utf-8")

    class Flaky(FakeHttp):
        calls = 0

        def sha256(self, url):
            if url.endswith("v1.2.0/tool-linux.tar.gz"):
                Flaky.calls += 1
                if Flaky.calls > 1:
                    return "0" * 64
            return super().sha256(url)

    assert bump.main(["--bump", "tool", "--no-tests"], http=Flaky(routes()), path=vfile) == 1
    assert vfile.read_text(encoding="utf-8") == before


def test_usage_and_network_errors_exit_2(vfile: Path) -> None:
    assert bump.main(["--check", "nope"], http=FakeHttp({}), path=vfile) == 2

    class Down(FakeHttp):
        def get(self, url, headers=None):
            raise bump.NetError(f"{url}: connection refused")

    assert bump.main(["--check", "tool"], http=Down({}), path=vfile) == 2


def test_every_real_source_entry_is_understood() -> None:
    _, versions = bump.load()
    for name, src in versions["nikos_pin_sources"].items():
        if src["type"] in ("apt-key", "pypi-map"):
            continue
        assert bump.current_of(versions, src), name
        for art in src.get("artifacts", []):
            url = bump.Pins(versions, FakeHttp({}), 3).artifact_url(src, art, bump.current_of(versions, src))
            assert url.startswith("https://") and "{" not in url, (name, url)


def _gpg_key(tmp_path: Path, name: str):
    import os
    import subprocess
    home = tmp_path / f"gnupg-{name}"
    home.mkdir(mode=0o700)
    env = {**os.environ, "GNUPGHOME": str(home)}
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", f"{name} <{name}@example.invalid>",
                    "ed25519", "sign", "never"], env=env, check=True, capture_output=True)
    listing = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], env=env, check=True,
                             capture_output=True, text=True).stdout
    fpr = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr"))
    key = subprocess.run(["gpg", "--batch", "--armor", "--export", fpr], env=env, check=True,
                         capture_output=True).stdout

    def sign(data: bytes) -> bytes:
        return subprocess.run(["gpg", "--batch", "--detach-sign", "-u", fpr, "-o", "-"], input=data, env=env,
                              check=True, capture_output=True).stdout

    return key, fpr, sign


@pytest.mark.skipif(not __import__("shutil").which("gpg"), reason="gpg is required")
@pytest.mark.parametrize("case", ["good", "wrong-key", "tampered"])
def test_a_claude_manifest_is_trusted_only_when_signed_by_the_pinned_key(tmp_path: Path, case: str) -> None:
    key, fpr, sign = _gpg_key(tmp_path, "release")
    other_key, other_fpr, other_sign = _gpg_key(tmp_path, "other")
    binary = b"claude binary"
    manifest = json.dumps({"platforms": {"linux-x64": {"checksum": sha(binary)}}}).encode()
    sig = (other_sign if case == "wrong-key" else sign)(manifest)
    served = manifest.replace(b"}}}", b"}}, \"x\": 1}") if case == "tampered" else manifest
    base = "https://downloads.claude.ai/claude-code-releases/9.9.9"
    http = FakeHttp({f"{base}/manifest.json": served, f"{base}/manifest.json.sig": sig,
                     "https://downloads.claude.ai/keys/claude-code.asc": key, f"{base}/linux-x64/claude": binary})
    versions = {"claude_code_key_fingerprints": [fpr]}
    src = {"type": "npm", "package": "x", "artifacts": [
        {"url": base.replace("9.9.9", "{version}") + "/linux-x64/claude", "sha256_var": "s", "checksums": "claude-manifest"}]}
    p = bump.Pins(versions, http, 3)
    if case == "good":
        assert p.hash_artifacts(src, "9.9.9", require_vendor=True).values == {"s": sha(binary)}
    else:
        with pytest.raises(bump.ChecksumMismatch):
            p.hash_artifacts(src, "9.9.9", require_vendor=True)


def test_a_dist_tag_head_too_new_falls_back_on_its_own_line(vfile: Path) -> None:
    # openclaw's extended-stable channel publishes almost daily; returning
    # nothing when the head is younger than the minimum age meant --bump never
    # moved it. The fallback stays on the channel's line (2026.8.x), never
    # crossing to the newer 2026.9 line or going above the head.
    meta = {
        "dist-tags": {"extended-stable": "2026.8.35", "latest": "2026.9.8"},
        "time": {"2026.8.33": ago(6), "2026.8.34": ago(4), "2026.8.35": ago(1),
                 "2026.9.7": ago(5), "2026.9.8": ago(1)},
        "versions": {v: {} for v in ["2026.8.33", "2026.8.34", "2026.8.35", "2026.9.7", "2026.9.8"]},
    }
    http = FakeHttp({"https://registry.npmjs.org/openclaw": meta})
    _, versions = bump.load(vfile)
    p = bump.Pins(versions, http, 3)
    assert p.newest_npm({"package": "openclaw", "dist_tag": "extended-stable"}) == "2026.8.34"
    meta["time"]["2026.8.35"] = ago(10)
    assert p.newest_npm({"package": "openclaw", "dist_tag": "extended-stable"}) == "2026.8.35"
