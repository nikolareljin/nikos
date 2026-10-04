"""Per-release package names and the skip-with-message path for missing repos."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
MAIN = yaml.safe_load((REPO / "vars/main.yml").read_text(encoding="utf-8"))
RELEASES = MAIN["nikos_ubuntu_releases"]
CODENAMES = {"22.04": "jammy", "24.04": "noble", "26.04": "resolute"}


def test_installer_accepts_exactly_the_releases_the_vars_describe():
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    m = re.search(r'case "\$\{version_id\}" in\n\s*([0-9.|]+)\)', text)
    assert m, "release case statement not found in install.sh"
    assert sorted(m.group(1).split("|")) == sorted(RELEASES)


def test_every_release_names_every_package_key():
    keys = set(RELEASES["24.04"])
    for version, facts in RELEASES.items():
        assert set(facts) == keys, version


@pytest.mark.parametrize(
    "version,glib,xubuntu,postgres,education,netdata",
    [
        ("22.04", "libglib2.0-0", "xubuntu-core",
         ["postgresql", "postgresql-contrib"], ["libreoffice", "anki"], "netdata"),
        ("24.04", "libglib2.0-0t64", "xubuntu-desktop-minimal",
         ["postgresql", "postgresql-contrib", "postgresql-16-pgvector"], ["libreoffice", "anki"], "netdata"),
        ("26.04", "libglib2.0-0t64", "xubuntu-desktop-minimal",
         ["postgresql", "postgresql-18-pgvector"], ["libreoffice"], ""),
    ],
)
def test_package_names_follow_the_release(version, glib, xubuntu, postgres, education, netdata):
    jinja2 = pytest.importorskip("jinja2")
    env = jinja2.Environment()
    ctx = {"nikos_release": RELEASES[version]}

    def render(expr):
        return env.from_string("{{ (" + expr + ") | tojson }}").render(ctx)

    assert RELEASES[version]["glib_package"] == glib
    assert RELEASES[version]["xubuntu_minimal_package"] == xubuntu
    assert RELEASES[version]["netdata_package"] == netdata
    assert yaml.safe_load(render(
        "['postgresql', nikos_release.postgres_contrib_package, nikos_release.pgvector_package]"
        " | select | list")) == postgres
    assert yaml.safe_load(render("['libreoffice', nikos_release.anki_package] | select | list")) == education


def test_vars_use_the_release_names_not_a_fixed_one():
    assert "{{ nikos_release.glib_package }}" in MAIN["nikos_vision_apt_packages"]
    assert MAIN["nikos_desktop_packages"]["xubuntu-minimal"][0] == "{{ nikos_release.xubuntu_minimal_package }}"
    for rel in ("roles/optional/postgres/tasks/main.yml", "roles/optional/education/tasks/main.yml",
                "roles/optional/monitoring/tasks/main.yml"):
        text = (REPO / rel).read_text(encoding="utf-8")
        for name in ("postgresql-16-pgvector", "- anki", "name: netdata"):
            assert name not in text, (rel, name)


def _run_mongodb_role(tmp_path, version):
    playbook = tmp_path / "play.yml"
    playbook.write_text(
        "- hosts: localhost\n"
        "  gather_facts: false\n"
        "  vars_files:\n"
        f"    - {REPO}/vars/main.yml\n"
        f"    - {REPO}/vars/versions.yml\n"
        "  roles:\n"
        f"    - {REPO}/roles/optional/mongodb\n"
    )
    return subprocess.run(
        ["ansible-playbook", "-i", "localhost,", "-c", "local", "--check", str(playbook),
         "-e", json.dumps({"ansible_facts": {"distribution_version": version,
                                             "distribution_release": CODENAMES[version]}})],
        capture_output=True, text=True, cwd=REPO,
    )


def test_mongodb_repo_codenames_are_supported_releases():
    assert set(MAIN["mongodb_repo_codenames"]) <= set(CODENAMES.values())


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed")
def test_mongodb_is_skipped_with_a_message_where_the_vendor_has_no_repository(tmp_path):
    if "resolute" in MAIN["mongodb_repo_codenames"]:
        pytest.skip("MongoDB now publishes resolute")
    run = _run_mongodb_role(tmp_path, "26.04")
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "mongodb is not available on Ubuntu 26.04: MongoDB publishes no repository for resolute" in out
    assert "Download the MongoDB repository signing key" not in out


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed")
@pytest.mark.parametrize(
    "distribution,version,ok",
    [("Ubuntu", "22.04", True), ("Ubuntu", "26.04", True), ("Ubuntu", "20.04", False),
     ("Debian", "24.04", False)],
)
def test_the_play_refuses_an_unsupported_release(tmp_path, distribution, version, ok):
    site = yaml.safe_load((REPO / "site.yml").read_text(encoding="utf-8"))
    task = next(t for t in site[0]["pre_tasks"] if t["name"] == "Check this is a supported Ubuntu release")
    playbook = tmp_path / "play.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "gather_facts": False,
        "vars_files": [str(REPO / "vars/main.yml")], "tasks": [task],
    }]))
    run = subprocess.run(
        ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook),
         "-e", json.dumps({"ansible_facts": {"distribution": distribution, "distribution_version": version}})],
        capture_output=True, text=True, cwd=REPO,
    )
    assert (run.returncode == 0) == ok, run.stdout + run.stderr
    if not ok:
        assert f"this is {distribution} {version}" in run.stdout


def _release_note_func() -> str:
    import re as _re
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    funcs = []
    for name in ("_os_release_value", "_release_note"):
        m = _re.search(rf"^{name}\(\) \{{.*?^\}}", text, _re.M | _re.S)
        assert m, name
        funcs.append(m.group(0))
    return "\n".join(funcs)


def test_installer_menu_notes_match_the_release_table(tmp_path):
    # The menu must say which bundles a release lacks, and agree with
    # vars/main.yml: an empty package name (or no MongoDB repository) there
    # means a note here, and no note otherwise.
    import subprocess as _sp
    import yaml as _yaml
    vars_main = _yaml.safe_load((REPO / "vars/main.yml").read_text(encoding="utf-8"))
    releases = vars_main["nikos_ubuntu_releases"]
    codenames = {"22.04": "jammy", "24.04": "noble", "26.04": "resolute"}
    missing_by = {"postgres": "pgvector_package", "education": "anki_package", "monitoring": "netdata_package"}
    for version, rel in releases.items():
        osr = tmp_path / f"os-{version}"
        osr.write_text(f'ID=ubuntu\nVERSION_ID="{version}"\n')
        for bundle in ("postgres", "education", "monitoring", "mongodb"):
            out = _sp.run(["bash", "-c", _release_note_func() + f"\n_release_note {bundle}"],
                          capture_output=True, text=True,
                          env={"NIKOS_OS_RELEASE_FILE": str(osr), "PATH": "/usr/bin:/bin"}).stdout
            if bundle == "mongodb":
                expect = codenames[version] not in vars_main["mongodb_repo_codenames"]
            else:
                alt = {"education": "anki_release", "monitoring": "netdata_vendor_repo"}.get(bundle)
                expect = not rel[missing_by[bundle]] and not (alt and rel.get(alt))
            assert bool(out) == expect, (version, bundle, out)


def test_vendor_sources_only_where_the_archive_has_no_package():
    # 22.04 and 24.04 must install exactly as before: the Netdata repository
    # and the Anki tarball are used only where the archive lacks the package.
    import yaml as _yaml
    releases = _yaml.safe_load((REPO / "vars/main.yml").read_text(encoding="utf-8"))["nikos_ubuntu_releases"]
    for version, rel in releases.items():
        assert bool(rel.get("netdata_vendor_repo")) == (not rel["netdata_package"]), version
        assert bool(rel.get("anki_release")) == (not rel["anki_package"]), version
    assert releases["24.04"]["netdata_package"] == "netdata" and releases["24.04"]["anki_package"] == "anki"
