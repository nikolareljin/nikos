"""Tests for installer version selection and repo synchronisation.

The functions under test live in ``scripts/repo-sync.sh``. Each test sources
that file in a fresh bash process, so the shell functions are exercised
directly rather than through a reimplementation.
"""

import os
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_SYNC = REPO_ROOT / "scripts" / "repo-sync.sh"


def run_sourced(snippet, stdin=None, cwd=None, env=None):
    """Run a bash snippet with scripts/repo-sync.sh sourced."""
    merged_env = dict(os.environ)
    # Keep committer identity off the ambient config so fixtures are reproducible.
    merged_env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", "-c", f"set -uo pipefail\nsource {REPO_SYNC}\n{snippet}"],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=merged_env,
    )


def git(*args, cwd):
    """Run a git command in cwd, raising on failure."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    ).stdout.strip()


def commit(repo, message, path="file.txt", content=None):
    (repo / path).write_text(content if content is not None else message)
    git("add", path, cwd=repo)
    git("commit", "-m", message, cwd=repo)


def pick_latest(lines):
    """Feed newline-separated tag names through _pick_latest_semver."""
    result = run_sourced("_pick_latest_semver", stdin="\n".join(lines) + "\n")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestPickLatestSemver:
    def test_picks_highest_of_a_simple_list(self):
        assert pick_latest(["0.1.0", "0.4.2", "0.2.0"]) == "0.4.2"

    def test_orders_by_version_not_lexically(self):
        # Lexical sort puts 0.9.0 above 0.10.0. Version sort must not.
        assert pick_latest(["0.9.0", "0.10.0"]) == "0.10.0"

    def test_compares_major_versions_numerically(self):
        assert pick_latest(["9.0.0", "10.0.0"]) == "10.0.0"

    def test_excludes_prerelease_tags(self):
        assert pick_latest(["0.4.2", "0.5.0-rc1"]) == "0.4.2"

    def test_ignores_non_semver_tags(self):
        assert pick_latest(["production", "v0.4.2", "0.3.0", "release"]) == "0.3.0"

    def test_returns_empty_when_no_tag_qualifies(self):
        assert pick_latest(["production", "nightly"]) == ""

    def test_returns_empty_on_empty_input(self):
        result = run_sourced("_pick_latest_semver", stdin="")
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_tolerates_duplicate_tags(self):
        assert pick_latest(["0.4.2", "0.4.2", "0.4.1"]) == "0.4.2"


@pytest.fixture
def origin(tmp_path):
    """A publishable repo with tags 0.1.0, 0.2.0, 0.10.0 and a feature branch."""
    work = tmp_path / "origin-work"
    work.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=work)
    commit(work, "first")
    # A file no later commit touches, so an edit to it survives a ref switch.
    commit(work, "add stable file", path="stable.txt", content="stable")
    git("tag", "0.1.0", cwd=work)
    commit(work, "second")
    git("tag", "0.2.0", cwd=work)
    commit(work, "third")
    git("tag", "0.10.0", cwd=work)
    git("tag", "0.11.0-rc1", cwd=work)
    git("switch", "-q", "-c", "release/0.12.0", cwd=work)
    commit(work, "branch work")
    # A floating tag on a commit no release tag points at.
    git("tag", "production", cwd=work)
    git("switch", "-q", "main", cwd=work)

    bare = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(work), str(bare), cwd=tmp_path)
    # Let the work tree publish later commits and tags to the bare repo.
    git("remote", "add", "origin", str(bare), cwd=work)
    return {"work": work, "bare": bare}


@pytest.fixture
def clone(tmp_path, origin):
    """A consumer checkout of origin, standing in for NIKOS_HOME."""
    target = tmp_path / "nikos-home"
    git("clone", "-q", str(origin["bare"]), str(target), cwd=tmp_path)
    return target


def sync_env(nikos_home):
    return {
        "NIKOS_HOME": str(nikos_home),
        "MAIN_VARS_REL": "vars/main.yml",
        "LOCAL_VARS_REL": "vars/local.yml",
    }


def head_ref(repo):
    """Current branch name, or 'detached:<tag>' when not on a branch."""
    branch = git("branch", "--show-current", cwd=repo)
    if branch:
        return branch
    return "detached:" + git("describe", "--tags", "--exact-match", cwd=repo)


class TestLatestSemverTag:
    def test_reads_the_newest_release_tag_from_a_remote(self, origin):
        result = run_sourced(f'_latest_semver_tag "{origin["bare"]}"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0.10.0"

    def test_ignores_prerelease_and_floating_tags_on_the_remote(self, origin):
        result = run_sourced(f'_latest_semver_tag "{origin["bare"]}"')
        assert result.stdout.strip() not in ("0.11.0-rc1", "production")

    def test_is_empty_when_the_remote_is_unreachable(self, tmp_path):
        result = run_sourced(f'_latest_semver_tag "{tmp_path}/does-not-exist.git"')
        assert result.stdout.strip() == ""

    def test_reads_the_newest_release_tag_from_a_local_checkout(self, clone):
        result = run_sourced(f'_latest_local_semver_tag "{clone}"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0.10.0"


class TestSyncRepoToRef:
    def test_recovers_a_detached_head_onto_a_branch(self, clone):
        """Regression: install.sh exited 2 here instead of switching."""
        git("switch", "-q", "--detach", "0.1.0", cwd=clone)
        assert head_ref(clone) == "detached:0.1.0"

        result = run_sourced(
            '_sync_repo_to_ref "release/0.12.0" "test-autostash"',
            env=sync_env(clone),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert head_ref(clone) == "release/0.12.0"

    def test_moves_a_detached_head_to_a_newer_tag(self, clone):
        git("switch", "-q", "--detach", "0.1.0", cwd=clone)

        result = run_sourced(
            '_sync_repo_to_ref "0.10.0" "test-autostash"', env=sync_env(clone)
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert head_ref(clone) == "detached:0.10.0"

    def test_fast_forwards_a_branch_that_gained_commits(self, clone, origin):
        commit(origin["work"], "upstream commit")
        git("push", "-q", "origin", "main", cwd=origin["work"])

        result = run_sourced('_sync_repo_to_ref "main" "test-autostash"', env=sync_env(clone))

        assert result.returncode == 0, result.stdout + result.stderr
        assert head_ref(clone) == "main"
        assert git("log", "-1", "--format=%s", cwd=clone) == "upstream commit"

    def test_sees_tags_published_after_the_clone(self, clone, origin):
        git("tag", "0.20.0", cwd=origin["work"])
        git("push", "-q", "origin", "0.20.0", cwd=origin["work"])

        run_sourced('_sync_repo_to_ref "" "test-autostash"', env=sync_env(clone))

        result = run_sourced(f'_latest_local_semver_tag "{clone}"')
        assert result.stdout.strip() == "0.20.0"

    def test_preserves_uncommitted_changes_across_the_switch(self, clone):
        git("switch", "-q", "--detach", "0.1.0", cwd=clone)
        (clone / "stable.txt").write_text("local edit")
        (clone / "untracked.txt").write_text("keep me")

        result = run_sourced(
            '_sync_repo_to_ref "release/0.12.0" "test-autostash"',
            env=sync_env(clone),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert head_ref(clone) == "release/0.12.0"
        assert (clone / "stable.txt").read_text() == "local edit"
        assert (clone / "untracked.txt").read_text() == "keep me"

    def test_reports_local_changes_that_cannot_be_reapplied(self, clone):
        """file.txt differs between refs, so the stash cannot pop cleanly."""
        git("switch", "-q", "--detach", "0.1.0", cwd=clone)
        (clone / "file.txt").write_text("conflicting edit")

        result = run_sourced(
            '_sync_repo_to_ref "0.10.0" "test-autostash"', env=sync_env(clone)
        )

        assert result.returncode == 1
        # The work must still be recoverable, and the caller must be told how.
        assert "stash" in (result.stdout + result.stderr).lower()
        assert git("stash", "list", cwd=clone) != ""

    def test_reports_failure_for_an_unknown_ref(self, clone):
        result = run_sourced(
            '_sync_repo_to_ref "no/such/ref" "test-autostash"', env=sync_env(clone)
        )

        assert result.returncode != 0
        assert "no/such/ref" in (result.stdout + result.stderr)

    def test_leaves_the_checkout_usable_after_an_unknown_ref(self, clone):
        before = head_ref(clone)
        run_sourced('_sync_repo_to_ref "no/such/ref" "test-autostash"', env=sync_env(clone))
        assert head_ref(clone) == before
        assert git("status", "--porcelain", cwd=clone) == ""


class TestResolveReleaseRef:
    def test_prefers_the_newest_tag_published_by_the_remote(self, origin, clone):
        result = run_sourced(f'_resolve_release_ref "{origin["bare"]}" "{clone}"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0.10.0"

    def test_falls_back_to_local_tags_when_the_remote_is_unreachable(self, tmp_path, clone):
        result = run_sourced(f'_resolve_release_ref "{tmp_path}/gone.git" "{clone}"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0.10.0"

    def test_is_empty_when_neither_source_has_a_release_tag(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        git("init", "-q", "-b", "main", ".", cwd=empty)
        result = run_sourced(f'_resolve_release_ref "{tmp_path}/gone.git" "{empty}"')
        assert result.stdout.strip() == ""


INSTALLER = REPO_ROOT / "install.sh"


def run_installer(args, cwd=None, home=None, script=None):
    """Invoke install.sh with an isolated HOME so no real config is touched.

    Every case here must be rejected during argument handling, long before any
    network or package work. The timeout turns a regression in that ordering
    into a fast failure instead of a real install.
    """
    env = dict(os.environ)
    if home:
        env["HOME"] = str(home)
    try:
        return subprocess.run(
            ["bash", str(script or INSTALLER), *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"install.sh {' '.join(args)} did not exit during argument handling; "
            "it started doing real work."
        )


@pytest.fixture
def isolated_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


class TestInstallerCli:
    def test_help_documents_dev_mode(self, isolated_home):
        result = run_installer(["--help"], home=isolated_home)
        assert result.returncode == 0, result.stderr
        assert "--dev" in result.stdout
        assert "--ref" in result.stdout

    def test_rejects_an_unknown_option(self, isolated_home):
        result = run_installer(["--nope"], home=isolated_home)
        assert result.returncode != 0
        assert "--nope" in result.stdout + result.stderr

    def test_rejects_dev_and_ref_together(self, isolated_home):
        result = run_installer(["--dev", "--ref", "0.4.2"], home=isolated_home)
        assert result.returncode != 0
        assert "--dev" in result.stdout + result.stderr

    def test_dev_mode_requires_a_nikos_checkout(self, tmp_path, isolated_home):
        """--dev runs the tree it was launched from, so that tree must be one."""
        stray = tmp_path / "not-nikos"
        stray.mkdir()
        (stray / "install.sh").write_text(INSTALLER.read_text())

        result = run_installer(
            ["--dev"], home=isolated_home, script=stray / "install.sh"
        )

        assert result.returncode != 0
        assert "site.yml" in result.stdout + result.stderr


class TestResolveUpdateRef:
    """`nikos update` must upgrade a tag install without downgrading a branch one."""

    def test_moves_a_tag_install_to_a_newer_release(self, clone, origin):
        git("switch", "-q", "--detach", "0.2.0", cwd=clone)
        result = run_sourced(f'_resolve_update_ref "{origin["bare"]}" "{clone}"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0.10.0"

    def test_stays_put_when_already_on_the_newest_release(self, clone, origin):
        git("switch", "-q", "--detach", "0.10.0", cwd=clone)
        result = run_sourced(f'_resolve_update_ref "{origin["bare"]}" "{clone}"')
        assert result.stdout.strip() == ""

    def test_keeps_a_branch_install_on_its_branch(self, clone, origin):
        """A branch install must never be yanked back to an older tag."""
        git("switch", "-q", "--track", "origin/release/0.12.0", cwd=clone)
        result = run_sourced(f'_resolve_update_ref "{origin["bare"]}" "{clone}"')
        assert result.stdout.strip() == "release/0.12.0"

    def test_leaves_a_floating_tag_for_the_newest_release(self, clone, origin):
        git("switch", "-q", "--detach", "production", cwd=clone)
        result = run_sourced(f'_resolve_update_ref "{origin["bare"]}" "{clone}"')
        assert result.stdout.strip() == "0.10.0"

    def test_stays_put_when_no_release_tag_exists(self, tmp_path):
        repo = tmp_path / "untagged"
        repo.mkdir()
        git("init", "-q", "-b", "main", ".", cwd=repo)
        commit(repo, "only commit")
        git("checkout", "-q", "--detach", "HEAD", cwd=repo)
        result = run_sourced(f'_resolve_update_ref "{tmp_path}/gone.git" "{repo}"')
        assert result.stdout.strip() == ""


class TestStaleHelperRecovery:
    """Upgrading from a release whose repo-sync.sh predates _sync_repo_to_ref.

    install.sh sources the helper from NIKOS_HOME, which belongs to the
    *installed* version. On every 0.4.2 install that copy has no
    _sync_repo_to_ref, and the installer would die on `command not found`.
    """

    @staticmethod
    def _drive_sourcing(nikos_home, script_dir, repo_ref=""):
        """Run install.sh's _source_repo_sync_helpers in isolation."""
        func = subprocess.run(
            ["sed", "-n", "/^_source_repo_sync_helpers() {/,/^}/p", str(INSTALLER)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        snippet = f"""
set -euo pipefail
NIKOS_HOME='{nikos_home}'
SCRIPT_DIR='{script_dir}'
REPO_REF='{repo_ref}'
REPO_SYNC_HELPERS_REL='scripts/repo-sync.sh'
{func}
if _source_repo_sync_helpers && declare -F _sync_repo_to_ref >/dev/null; then
  echo HELPERS_OK
else
  echo HELPERS_MISSING
fi
"""
        return subprocess.run(
            ["bash", "-c", snippet], capture_output=True, text=True
        )

    @pytest.fixture
    def upgrade_scenario(self, tmp_path):
        """An origin carrying the current helper, and a clone stuck on an old one."""
        work = tmp_path / "origin-work"
        (work / "scripts").mkdir(parents=True)
        git("init", "-q", "-b", "main", ".", cwd=work)

        # The old release: a helper without _sync_repo_to_ref.
        (work / "scripts" / "repo-sync.sh").write_text(
            "_pull_repo_updates() { :; }\n"
        )
        git("add", "-A", cwd=work)
        git("commit", "-q", "-m", "old release", cwd=work)
        git("tag", "0.4.2", cwd=work)

        bare = tmp_path / "origin.git"
        git("clone", "-q", "--bare", str(work), str(bare), cwd=tmp_path)
        git("remote", "add", "origin", str(bare), cwd=work)

        # A machine installed at that old release.
        installed = tmp_path / "installed"
        git("clone", "-q", str(bare), str(installed), cwd=tmp_path)
        git("switch", "-q", "--detach", "0.4.2", cwd=installed)

        # The new release lands on the remote afterwards.
        (work / "scripts" / "repo-sync.sh").write_text(
            REPO_SYNC.read_text()
        )
        git("add", "-A", cwd=work)
        git("commit", "-q", "-m", "new release", cwd=work)
        git("tag", "0.5.0", cwd=work)
        git("push", "-q", "origin", "main", cwd=work)
        git("push", "-q", "origin", "0.5.0", cwd=work)

        return {"installed": installed, "empty": tmp_path / "no-checkout"}

    def test_the_installed_helper_really_is_too_old(self, upgrade_scenario):
        stale = upgrade_scenario["installed"] / "scripts" / "repo-sync.sh"
        assert "_sync_repo_to_ref" not in stale.read_text()

    def test_refreshes_a_stale_helper_from_the_remote(self, upgrade_scenario):
        result = self._drive_sourcing(
            upgrade_scenario["installed"], upgrade_scenario["empty"]
        )
        assert result.stdout.strip().splitlines()[-1] == "HELPERS_OK", (
            result.stdout + result.stderr
        )

    def test_prefers_a_local_checkout_that_is_current(self, tmp_path, upgrade_scenario):
        """A checkout beside install.sh is used without any network access."""
        result = self._drive_sourcing(tmp_path / "gone", REPO_ROOT)
        assert result.stdout.strip().splitlines()[-1] == "HELPERS_OK", (
            result.stdout + result.stderr
        )

    def test_reports_failure_when_no_source_can_supply_it(self, tmp_path):
        result = self._drive_sourcing(tmp_path / "gone", tmp_path / "also-gone")
        assert result.stdout.strip().splitlines()[-1] == "HELPERS_MISSING"
