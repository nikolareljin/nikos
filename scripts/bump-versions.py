#!/usr/bin/env python3
"""bump-versions.py - check, bump and verify the pins in vars/versions.yml.

    scripts/bump-versions.py [--check]                 list each pin and the newest eligible upstream
    scripts/bump-versions.py --bump [NAME...]          move pins to the newest eligible upstream
    scripts/bump-versions.py --verify [NAME...]        re-download / re-query every pin and compare

NAME is a key of nikos_pin_sources in vars/versions.yml (all pins when none
is given). Eligible means: not a draft or pre-release, and published at least
--min-age-days ago (default 3).

--bump downloads each new artifact, hashes it, and cross-checks the hash with
the vendor's checksum file when there is one; a mismatch skips that pin. Pins
whose artifacts have no vendor checksum, and apt key fingerprints, are never
changed automatically: they are reported for a person to update by hand (and
then proven with --verify). Only the changed values are rewritten, comments
and layout are kept, and the file is replaced atomically. The changed pins
are then verified again from upstream and `python3 -m pytest tests -q` runs,
unless --no-tests.

Needs Python 3.8+ and PyYAML (already required by Ansible and the tests) to
read the file; everything else is the standard library. GITHUB_TOKEN, when
set, is sent to api.github.com only, to lift the 60 requests/hour limit.

Exit codes: 0 ok, 1 a verification failed or a checksum did not match,
2 usage or network error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships with Ansible
    sys.stderr.write("bump-versions: PyYAML is required (python3 -m pip install pyyaml)\n")
    sys.exit(2)

REPO = Path(__file__).resolve().parent.parent
VERSIONS = REPO / "vars" / "versions.yml"
UA = "nikos-bump-versions"


class NetError(Exception):
    """A network or upstream API failure: exit 2."""


class NotFound(NetError):
    """HTTP 404: the pinned thing does not exist upstream (a verify failure)."""


class ChecksumMismatch(Exception):
    """The download does not match the vendor's checksum or signature: exit 1."""


class Http:
    """The only thing that touches the network; tests replace it."""

    def _open(self, url: str, headers: dict | None = None, method: str = "GET"):
        hdrs = {"User-Agent": UA}
        host = urllib.parse.urlparse(url).hostname or ""
        token = os.environ.get("GITHUB_TOKEN", "")
        if token and host == "api.github.com":
            hdrs["Authorization"] = f"Bearer {token}"
        hdrs.update(headers or {})
        req = urllib.request.Request(url, headers=hdrs, method=method)
        try:
            return urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise NotFound(f"{url}: 404 Not Found") from exc
            raise NetError(f"{url}: {exc}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise NetError(f"{url}: {exc}") from exc

    def get(self, url: str, headers: dict | None = None) -> bytes:
        with self._open(url, headers) as resp:
            return resp.read()

    def json(self, url: str, headers: dict | None = None):
        return json.loads(self.get(url, headers))

    def head(self, url: str, headers: dict | None = None) -> dict:
        with self._open(url, headers, method="HEAD") as resp:
            return {k.lower(): v for k, v in resp.headers.items()}

    def sha256(self, url: str) -> str:
        digest = hashlib.sha256()
        with self._open(url) as resp:
            for chunk in iter(lambda: resp.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()


# -- small helpers -------------------------------------------------------------


def vkey(version: str) -> tuple:
    """Natural sort key: v1.10.0 > v1.9.3, b10444 > b9999."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def parse_time(value: str) -> dt.datetime:
    value = value.replace("Z", "+00:00")
    stamp = dt.datetime.fromisoformat(value)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def is_prerelease(version: str) -> bool:
    """Any letter or "-" after a leading "v" (1.0.0rc1, 4.7.0a2, 0.64.0-nightly.1).

    Sources whose releases carry letters on purpose (llama.cpp "b10444",
    Miniforge "26.3.2-3") set version_regex instead, which replaces this test.
    """
    core = (version[1:] if version.startswith("v") else version).split("+")[0]
    return bool(re.search(r"[A-Za-z-]", core))


def fill(template: str, **values: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


def checksum_from_file(text: str, name: str) -> str | None:
    """The sha256 for `name` in a sums file, or the only hash in a one-hash file."""
    hashes = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            continue
        hashes.append(parts[0].lower())
        if len(parts) > 1 and parts[-1].lstrip("*").split("/")[-1] == name:
            return parts[0].lower()
    return hashes[0] if len(hashes) == 1 else None


def gpg_fingerprints(key: bytes) -> list[str]:
    with tempfile.TemporaryDirectory() as home, tempfile.NamedTemporaryFile() as tmp:
        tmp.write(key)
        tmp.flush()
        out = subprocess.run(["gpg", "--batch", "--show-keys", "--with-colons", tmp.name],
                             env={**os.environ, "GNUPGHOME": home}, capture_output=True, text=True).stdout
    fprs, primary = [], False
    for line in out.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            primary = True
        elif fields[0] == "sub":
            primary = False
        elif fields[0] == "fpr" and primary:
            fprs.append(fields[9].upper())
            primary = False
    return sorted(set(fprs))


def gpg_signed_by(data: bytes, sig: bytes, key: bytes, fingerprints: list[str]) -> bool:
    """True when `sig` is a good signature over `data` by a key in `key`
    whose primary fingerprint is one of `fingerprints`."""
    if gpg_fingerprints(key) != sorted(f.upper() for f in fingerprints):
        return False
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "GNUPGHOME": home}
        paths = {}
        for name, blob in (("key", key), ("data", data), ("sig", sig)):
            paths[name] = os.path.join(home, name)
            with open(paths[name], "wb") as handle:
                handle.write(blob)
        subprocess.run(["gpg", "--batch", "--import", paths["key"]], env=env, capture_output=True)
        out = subprocess.run(["gpg", "--batch", "--status-fd", "1", "--verify", paths["sig"], paths["data"]],
                             env=env, capture_output=True, text=True)
    valid = [line.split()[-1].upper() for line in out.stdout.splitlines() if line.startswith("[GNUPG:] VALIDSIG")]
    return out.returncode == 0 and any(f in [x.upper() for x in fingerprints] for f in valid)


# -- reading and rewriting vars/versions.yml -----------------------------------


def load(path: Path = VERSIONS) -> tuple[str, dict]:
    text = path.read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def rewrite(text: str, changes: dict[str, str]) -> str:
    """Replace the quoted value of each `key: "value"` line, nothing else.

    A key "parent.child" is a line indented under the `parent:` mapping.
    """
    lines = text.splitlines(keepends=True)
    for key, value in changes.items():
        parent, _, child = key.rpartition(".")
        start, end = 0, len(lines)
        if parent:
            start = next(i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(parent)}:\s*$", ln)) + 1
            end = next((i for i in range(start, len(lines)) if re.match(r"^\S", lines[i])), len(lines))
            pattern = re.compile(rf'^(\s+{re.escape(child)}:\s*")[^"]*(".*)$', re.S)
        else:
            pattern = re.compile(rf'^({re.escape(child)}:\s*")[^"]*(".*)$', re.S)
        hits = [i for i in range(start, end) if pattern.match(lines[i])]
        if len(hits) != 1:
            raise ValueError(f"expected one `{key}: \"...\"` line, found {len(hits)}")
        lines[hits[0]] = pattern.sub(lambda m: m.group(1) + value + m.group(2), lines[hits[0]])
    return "".join(lines)


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".versions-", suffix=".yml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# -- upstream lookups per source type ------------------------------------------


class Result:
    """What a pin should become: values to write, and what could not be done."""

    def __init__(self, version: str | None, values: dict | None = None):
        self.version = version
        self.values = values or {}
        self.problem = ""   # a mismatch: the pin is skipped and the run fails
        self.manual = ""    # not automatic: a person has to look


class Pins:
    def __init__(self, versions: dict, http: Http, min_age_days: int, now: dt.datetime | None = None):
        self.v = versions
        self.http = http
        self.cutoff = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=min_age_days)
        self._releases: dict[str, list] = {}
        self._tags: dict[str, list] = {}

    # github ------------------------------------------------------------------
    def releases(self, repo: str) -> list:
        """Releases newest first, paged until one older than the cutoff is seen.

        llama.cpp publishes dozens a day, so one page can be all too new.
        """
        if repo not in self._releases:
            found: list = []
            for page in range(1, 11):
                batch = self.http.json(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}")
                found += batch
                old = [r for r in batch if parse_time(r.get("published_at") or r["created_at"]) <= self.cutoff]
                if len(batch) < 100 or old:
                    break
            self._releases[repo] = found
        return self._releases[repo]

    def release(self, repo: str, tag: str) -> dict:
        for rel in self.releases(repo):
            if rel.get("tag_name") == tag:
                return rel
        return self.http.json(f"https://api.github.com/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}")

    def newest_release(self, src: dict) -> str | None:
        prefix, regex = src.get("tag_prefix", ""), src.get("version_regex", "")
        best = None
        for rel in self.releases(src["repo"]):
            tag = rel.get("tag_name", "")
            if rel.get("draft") or not tag.startswith(prefix):
                continue
            if rel.get("prerelease") and not src.get("allow_prerelease"):
                continue
            version = tag[len(prefix):]
            if regex and not re.search(regex, version):
                continue
            if not regex and is_prerelease(version):
                continue
            if parse_time(rel.get("published_at") or rel["created_at"]) > self.cutoff:
                continue
            if best is None or vkey(version) > vkey(best):
                best = version
        return best

    def tags(self, repo: str) -> list:
        if repo not in self._tags:
            found: list = []
            for page in range(1, 11):
                batch = self.http.json(f"https://api.github.com/repos/{repo}/tags?per_page=100&page={page}")
                found += batch
                if len(batch) < 100:
                    break
            self._tags[repo] = found
        return self._tags[repo]

    def commit_time(self, repo: str, sha: str) -> dt.datetime:
        data = self.http.json(f"https://api.github.com/repos/{repo}/commits/{sha}")
        return parse_time(data["commit"]["committer"]["date"])

    def newest_tag(self, src: dict) -> tuple[str, str] | tuple[None, None]:
        regex = src.get("version_regex", "")
        tags = [t for t in self.tags(src["repo"]) if not regex or re.search(regex, t["name"])]
        for tag in sorted(tags, key=lambda t: vkey(t["name"]), reverse=True):
            if is_prerelease(tag["name"]) and not regex:
                continue
            if self.commit_time(src["repo"], tag["commit"]["sha"]) <= self.cutoff:
                return tag["name"], tag["commit"]["sha"]
        return None, None

    def tag_commit(self, repo: str, tag: str) -> str | None:
        for item in self.tags(repo):
            if item["name"] == tag:
                return item["commit"]["sha"]
        return None

    # artifacts ---------------------------------------------------------------
    def artifact_url(self, src: dict, art: dict, version: str) -> str:
        tag = src.get("tag_prefix", "") + version
        if "asset" in art:
            asset = fill(art["asset"], version=version, tag=tag)
            return f"https://github.com/{src['repo']}/releases/download/{tag}/{asset}"
        return fill(art["url"], version=version, tag=tag)

    def vendor_sha(self, src: dict, art: dict, version: str) -> str | None:
        """The vendor's published sha256 for an artifact, or None when it publishes none."""
        spec = art.get("checksums")
        if not spec:
            return None
        tag = src.get("tag_prefix", "") + version
        url = self.artifact_url(src, art, version)
        asset = url.rsplit("/", 1)[-1]
        if spec == "github-digest":
            rel = self.release(src["repo"], tag)
            digest = next((a.get("digest") or "" for a in rel.get("assets", []) if a["name"] == asset), "")
            return digest.split(":", 1)[1] if digest.startswith("sha256:") else None
        if spec == "claude-manifest":
            # The manifest's own signature is checked first, against the
            # release key pinned as claude_code_key_fingerprints.
            base = f"https://downloads.claude.ai/claude-code-releases/{version}"
            body, sig = self.http.get(f"{base}/manifest.json"), self.http.get(f"{base}/manifest.json.sig")
            key = self.http.get("https://downloads.claude.ai/keys/claude-code.asc")
            if not gpg_signed_by(body, sig, key, self.v["claude_code_key_fingerprints"]):
                raise ChecksumMismatch(f"{base}/manifest.json is not signed by the pinned Claude Code key")
            return json.loads(body)["platforms"]["linux-x64"]["checksum"].lower()
        target = fill(spec, version=version, tag=tag, asset=asset, url=url)
        if "://" not in target:
            target = f"https://github.com/{src['repo']}/releases/download/{tag}/{target}"
        return checksum_from_file(self.http.get(target).decode("utf-8", "replace"), asset)

    def hash_artifacts(self, src: dict, version: str, *, require_vendor: bool) -> Result:
        res = Result(version)
        for art in src.get("artifacts", []):
            url = self.artifact_url(src, art, version)
            vendor = self.vendor_sha(src, art, version)
            if vendor is None and require_vendor:
                res.manual = f"{url} has no vendor checksum: hash it by hand, then --verify"
                return res
            got = self.http.sha256(url)
            if vendor is not None and got != vendor:
                res.problem = f"{url}: downloaded sha256 {got} but the vendor lists {vendor}"
                return res
            res.values[art["sha256_var"]] = got
        return res

    # per type: newest eligible ------------------------------------------------
    def newest(self, name: str, src: dict) -> Result:
        kind = src["type"]
        if kind == "github-release":
            return Result(self.newest_release(src))
        if kind == "github-tag":
            tag, sha = self.newest_tag(src)
            res = Result(tag)
            if sha and "commit_var" in src:
                res.values[src["commit_var"]] = sha
            return res
        if kind == "github-commit":
            until = self.cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
            data = self.http.json(f"https://api.github.com/repos/{src['repo']}/commits"
                                  f"?sha={src.get('branch', 'main')}&until={until}&per_page=1")
            sha = data[0]["sha"] if data else None
            return Result(sha, {src["commit_var"]: sha} if sha else {})
        if kind == "npm":
            return Result(self.newest_npm(src))
        if kind == "pypi":
            return Result(self.newest_pypi(src["package"]))
        if kind == "go-module":
            return Result(self.newest_go(src["module"]))
        if kind == "nodejs":
            return Result(self.newest_node(src))
        if kind == "docker-image":
            version = self.newest_release(src)
            res = Result(version)
            if version:
                res.values[src["digest_var"]] = self.docker_digest(src["image"], version)
            return res
        raise ValueError(f"{name}: no newest-version lookup for type {kind}")

    def newest_npm(self, src: dict) -> str | None:
        meta = self.http.json(f"https://registry.npmjs.org/{urllib.parse.quote(src['package'], safe='@')}")
        times = meta.get("time", {})
        if src.get("dist_tag"):
            tagged = meta.get("dist-tags", {}).get(src["dist_tag"])
            if not tagged:
                return None
            if tagged in times and parse_time(times[tagged]) <= self.cutoff:
                return tagged
            # The channel's head is too new. Take the newest old-enough release
            # on the same line (same first two version parts, not above the
            # head): a daily-release channel would otherwise never be eligible.
            line = tagged.split(".")[:2]
            best = None
            for version in meta.get("versions", {}):
                if (is_prerelease(version) or version not in times
                        or version.split(".")[:2] != line
                        or vkey(version) > vkey(tagged)
                        or parse_time(times[version]) > self.cutoff):
                    continue
                if best is None or vkey(version) > vkey(best):
                    best = version
            return best
        best = None
        for version in meta.get("versions", {}):
            if is_prerelease(version) or version not in times or parse_time(times[version]) > self.cutoff:
                continue
            if best is None or vkey(version) > vkey(best):
                best = version
        return best

    def newest_pypi(self, package: str) -> str | None:
        meta = self.http.json(f"https://pypi.org/pypi/{package}/json")
        best = None
        for version, files in meta.get("releases", {}).items():
            if not files or is_prerelease(version) or all(f.get("yanked") for f in files):
                continue
            uploaded = min(parse_time(f["upload_time_iso_8601"]) for f in files)
            if uploaded > self.cutoff:
                continue
            if best is None or vkey(version) > vkey(best):
                best = version
        return best

    def go_escape(self, module: str) -> str:
        return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), module)

    def newest_go(self, module: str) -> str | None:
        base = f"https://proxy.golang.org/{self.go_escape(module)}/@v"
        listed = [v for v in self.http.get(f"{base}/list").decode().split() if not is_prerelease(v)]
        for version in sorted(listed, key=vkey, reverse=True):
            if parse_time(self.http.json(f"{base}/{version}.info")["Time"]) <= self.cutoff:
                return version
        return None

    def newest_node(self, src: dict) -> str | None:
        regex = src.get("version_regex", "")
        best = None
        for rel in self.http.json("https://nodejs.org/dist/index.json"):
            version = rel["version"].lstrip("v")
            if regex and not re.search(regex, version):
                continue
            if parse_time(rel["date"] + "T00:00:00Z") > self.cutoff:
                continue
            if best is None or vkey(version) > vkey(best):
                best = version
        return best

    def docker_digest(self, image: str, tag: str) -> str:
        token = self.http.json("https://auth.docker.io/token?service=registry.docker.io"
                               f"&scope=repository:{image}:pull")["token"]
        headers = self.http.head(
            f"https://registry-1.docker.io/v2/{image}/manifests/{tag}",
            {"Authorization": f"Bearer {token}",
             "Accept": "application/vnd.oci.image.index.v1+json, "
                       "application/vnd.docker.distribution.manifest.list.v2+json"})
        return headers["docker-content-digest"]

    # verify --------------------------------------------------------------------
    def verify(self, name: str, src: dict) -> list[str]:
        """Problems with the recorded pin; an empty list means it holds."""
        kind, v = src["type"], self.v
        problems: list[str] = []
        current = str(get_var(v, src.get("version_var", "")))
        if kind in ("github-release", "github-tag", "npm") and src.get("artifacts"):
            for art in src["artifacts"]:
                url = self.artifact_url(src, art, current)
                got = self.http.sha256(url)
                if got != v[art["sha256_var"]]:
                    problems.append(f"{url}: sha256 {got}, pinned {v[art['sha256_var']]}")
                vendor = self.vendor_sha(src, art, current)
                if vendor is not None and vendor != v[art["sha256_var"]]:
                    problems.append(f"{url}: vendor lists {vendor}, pinned {v[art['sha256_var']]}")
        if kind == "github-release" and not src.get("artifacts"):
            self.release(src["repo"], src.get("tag_prefix", "") + current)
        if kind == "github-tag":
            sha = self.tag_commit(src["repo"], current)
            if "commit_var" in src and sha != v[src["commit_var"]]:
                problems.append(f"tag {current} is {sha}, pinned {v[src['commit_var']]}")
            if sha is None:
                problems.append(f"tag {current} does not exist")
        if kind == "github-commit":
            sha = v[src["commit_var"]]
            data = self.http.json(f"https://api.github.com/repos/{src['repo']}/compare/"
                                  f"{src.get('branch', 'main')}...{sha}")
            if data.get("status") not in ("identical", "behind"):
                problems.append(f"{sha} is not on {src.get('branch', 'main')} ({data.get('status')})")
        if kind == "npm":
            meta = self.http.json(f"https://registry.npmjs.org/{urllib.parse.quote(src['package'], safe='@')}")
            if current not in meta.get("versions", {}):
                problems.append(f"{src['package']}@{current} is not in the npm registry")
        if kind == "pypi":
            problems += self.verify_pypi(src["package"], current)
        if kind == "pypi-map":
            for package, version in v[src["version_var"]].items():
                problems += self.verify_pypi(package, version)
        if kind == "go-module":
            base = f"https://proxy.golang.org/{self.go_escape(src['module'])}/@v"
            self.http.json(f"{base}/{current}.info")
            body = self.http.get(f"https://sum.golang.org/lookup/{src['module']}@{current}").decode()
            if f"{src['module']} {current} h1:" not in body:
                problems.append(f"sum.golang.org has no hash for {src['module']}@{current}")
        if kind == "nodejs":
            sums = self.http.get(f"https://nodejs.org/dist/v{current}/SHASUMS256.txt").decode()
            if f"node-v{current}-linux-x64.tar.xz" not in sums:
                problems.append(f"node v{current} has no linux-x64 tarball in SHASUMS256.txt")
        if kind == "docker-image":
            digest = self.docker_digest(src["image"], current)
            if digest != v[src["digest_var"]]:
                problems.append(f"{src['image']}:{current} is {digest}, pinned {v[src['digest_var']]}")
        if kind == "apt-key":
            have, want = self.key_fingerprints(src), sorted(f.upper() for f in v[src["fingerprints_var"]])
            if have != want:
                problems.append(f"key at {self.key_url(src)} is {have}, pinned {want}")
        return problems

    def verify_pypi(self, package: str, version: str) -> list[str]:
        files = self.http.json(f"https://pypi.org/pypi/{package}/json").get("releases", {}).get(version)
        if not files:
            return [f"{package}=={version} is not on PyPI"]
        if all(f.get("yanked") for f in files):
            return [f"{package}=={version} is yanked"]
        return []

    def key_url(self, src: dict) -> str:
        return fill(src["url"], **{k: str(val) for k, val in self.v.items() if isinstance(val, str)})

    def key_fingerprints(self, src: dict) -> list[str]:
        return gpg_fingerprints(self.http.get(self.key_url(src)))


# -- commands --------------------------------------------------------------------


def get_var(versions: dict, name: str):
    """A variable by name; "parent.child" reaches into a mapping."""
    value = versions
    for part in name.split("."):
        value = value.get(part, "") if isinstance(value, dict) else ""
    return value


def current_of(versions: dict, src: dict) -> str:
    if src["type"] == "github-commit":
        return versions[src["commit_var"]]
    if src["type"] == "apt-key":
        return ",".join(versions[src["fingerprints_var"]])
    return str(get_var(versions, src.get("version_var", "")))


def select(sources: dict, names: list[str], versions: dict | None = None) -> dict:
    """The named pins. "nikos_pip_pins.<package>" picks one package of a pypi-map."""
    chosen, unknown = {}, []
    for name in names or list(sources):
        parent, _, child = name.partition(".")
        if name in sources:
            chosen[name] = sources[name]
        elif child and sources.get(parent, {}).get("type") == "pypi-map" and child in (
                (versions or {}).get(sources[parent]["version_var"]) or {}):
            chosen[name] = {"type": "pypi", "package": child, "version_var": f"{sources[parent]['version_var']}.{child}"}
        else:
            unknown.append(name)
    if unknown:
        raise SystemExit(f"bump-versions: unknown pin(s): {', '.join(unknown)} "
                         f"(known: {', '.join(sources)}, or nikos_pip_pins.<package>)")
    return chosen


def cmd_check(pins: Pins, sources: dict) -> int:
    rows = []
    for name, src in sources.items():
        if src["type"] == "apt-key":
            have = pins.key_fingerprints(src)
            want = sorted(f.upper() for f in pins.v[src["fingerprints_var"]])
            rows.append((name, "fingerprint", "-", "matches" if have == want else "CHANGED - needs a person"))
            continue
        if src["type"] == "pypi-map":
            for package, version in pins.v[src["version_var"]].items():
                newest = pins.newest_pypi(package)
                rows.append((f"{name}.{package}", version, newest or "-", status(version, newest)))
            continue
        current = current_of(pins.v, src)
        newest = pins.newest(name, src).version
        rows.append((name, current, newest or "-", status(current, newest, commit=src["type"] == "github-commit")))
    width = [max(len(r[i]) for r in rows + [("pin", "current", "newest eligible", "status")]) for i in range(4)]
    for row in [("pin", "current", "newest eligible", "status")] + rows:
        print("  ".join(cell.ljust(width[i]) for i, cell in enumerate(row)).rstrip())
    return 0


def status(current: str, newest: str | None, commit: bool = False) -> str:
    if not newest:
        return "no eligible release"
    if newest == current:
        return "current"
    if commit:
        return "newer commit"
    return "update available" if vkey(newest) > vkey(current) else "pin is newer than eligible"


def cmd_verify(pins: Pins, sources: dict) -> int:
    failed = 0
    for name, src in sources.items():
        try:
            problems = pins.verify(name, src)
        except (NotFound, ChecksumMismatch) as exc:
            problems = [str(exc)]
        shown = src["type"] if src["type"] == "pypi-map" else current_of(pins.v, src)
        print(f"{name}: {'ok' if not problems else 'FAIL'} ({shown})")
        for problem in problems:
            print(f"  {problem}")
        failed += bool(problems)
    print(f"verify: {len(sources) - failed} ok, {failed} failed")
    return 1 if failed else 0


def plan_bump(pins: Pins, name: str, src: dict) -> tuple[dict, str]:
    """(values to write, message). Raises nothing for a skipped pin; the message says why."""
    kind, v = src["type"], pins.v
    if kind == "apt-key":
        have = pins.key_fingerprints(src)
        want = sorted(f.upper() for f in v[src["fingerprints_var"]])
        return {}, "fingerprint matches" if have == want else f"CHANGED - needs a person (now {have})"
    if kind == "pypi-map":
        # These share one environment and have to resolve together, which a
        # per-package bump cannot check. Report; bump one at a time by name.
        newer = []
        for package, version in v[src["version_var"]].items():
            newest = pins.newest_pypi(package)
            if newest and vkey(newest) > vkey(version):
                newer.append(f"{package} {version} -> {newest}")
        if not newer:
            return {}, "all current"
        return {}, ("needs a person: resolve these together (uv pip compile), then "
                    f"--bump {src['version_var']}.<package>: " + "; ".join(newer))
    current = current_of(v, src)
    newest = pins.newest(name, src)
    if not newest.version or newest.version == current:
        return {}, "current" if newest.version else "no eligible release"
    if kind != "github-commit" and vkey(newest.version) <= vkey(current):
        return {}, f"pin {current} is newer than the newest eligible {newest.version}"
    values = dict(newest.values)
    if "version_var" in src:
        values[src["version_var"]] = newest.version
    if src.get("artifacts"):
        hashed = pins.hash_artifacts(src, newest.version, require_vendor=True)
        if hashed.problem:
            raise ChecksumMismatch(hashed.problem)
        if hashed.manual:
            return {}, f"{newest.version} available; {hashed.manual}"
        values.update(hashed.values)
    return values, f"{current} -> {newest.version}"


def cmd_bump(pins: Pins, sources: dict, run_tests: bool, path: Path = VERSIONS) -> int:
    text, _ = load(path)
    changes: dict[str, str] = {}
    changed_pins, failed = [], 0
    for name, src in sources.items():
        try:
            values, message = plan_bump(pins, name, src)
        except ChecksumMismatch as exc:
            print(f"{name}: SKIPPED, checksum mismatch: {exc}")
            failed += 1
            continue
        print(f"{name}: {message}")
        if values:
            changes.update(values)
            changed_pins.append(name)
    if not changes:
        return 1 if failed else 0
    new_text = rewrite(text, changes)
    write_atomic(path, new_text)
    print(f"wrote {path}: {', '.join(changes)}")
    pins.v = yaml.safe_load(new_text)
    if cmd_verify(pins, {n: sources[n] for n in changed_pins}) != 0:
        write_atomic(path, text)
        print("verification of the new pins failed; restored the previous file")
        return 1
    if run_tests:
        tests = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=REPO)
        if tests.returncode != 0:
            print("tests failed with the new pins; the file is left changed for you to inspect")
            return 1
    return 1 if failed else 0


def main(argv: list[str] | None = None, http: Http | None = None, path: Path = VERSIONS) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="list pins and the newest eligible upstream (default)")
    mode.add_argument("--bump", action="store_true", help="move the named pins (default: all) forward")
    mode.add_argument("--verify", action="store_true", help="prove every recorded pin against upstream")
    parser.add_argument("names", nargs="*", help="pins (keys of nikos_pin_sources)")
    parser.add_argument("--min-age-days", type=int, default=3)
    parser.add_argument("--no-tests", action="store_true", help="with --bump: skip the pytest run")
    args = parser.parse_args(argv)
    if args.min_age_days < 0:
        parser.error("--min-age-days must be >= 0")
    try:
        _, versions = load(path)
        sources = select(versions["nikos_pin_sources"], args.names, versions)
        pins = Pins(versions, http or Http(), args.min_age_days)
        if args.verify:
            return cmd_verify(pins, sources)
        if args.bump:
            return cmd_bump(pins, sources, not args.no_tests, path)
        return cmd_check(pins, sources)
    except NetError as exc:
        print(f"bump-versions: network error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
