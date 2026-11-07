"""`./test` driven end to end against stub VBoxManage, ssh and friends: what it
refuses, and what it leaves alone when it does."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Each stub appends its arguments to $STUB_LOG, prefixed with its own name.
LOG = 'printf "%s %s\\n" "${0##*/}" "$*" >> "${STUB_LOG}"\n'
STUBS = {
    "VBoxManage": LOG + """
if [ "$1" = showvminfo ]; then
  [ "${STUB_VM_EXISTS}" = 1 ] || exit 1
  printf 'VMState="%s"\\nForwarding(0)="ssh,tcp,127.0.0.1,2222,,22"\\n' "${STUB_VM_STATE}"
fi
""",
    "ssh": LOG + """
case "$*" in
  *os-release*) printf '%s' "${STUB_GUEST_RELEASE}" ;;
  *"command -v lantern"*) exit "${STUB_CHECK_RC}" ;;
esac
""",
    # Like the real curl: a 404 exits 22 under -f, and without -f the error page
    # lands in the output file with exit 0. STUB_CURL_RC is a transfer cut short.
    "curl": LOG + """
if [ -n "${STUB_CURL_MKDIR:-}" ]; then mkdir -p "${STUB_CURL_MKDIR}"; fi
if [ -n "${STUB_CURL_404:-}" ]; then
  case "$1" in -*f*) exit 22 ;; esac
  echo "<html>404</html>" > "$4"
  exit 0
fi
if [ -n "${STUB_CURL_BYTES:-}" ]; then
  truncate -s "${STUB_CURL_BYTES}" "$4"
else
  echo "default image" > "$4"
fi
exit "${STUB_CURL_RC:-0}"
""",
    # wait_for_ssh_port probes the port through `bash -c`; the harness itself
    # runs under /bin/bash by absolute path.
    **{name: LOG for name in ("scp", "ssh-copy-id", "ssh-keygen", "sshpass", "tar", "git", "sleep", "bash")},
}


@pytest.fixture
def run(tmp_path):
    """A copy of the harness in a tree of its own, returning (result, log)."""
    tree = tmp_path / "tree"
    (tree / "scripts/script-helpers").mkdir(parents=True)
    (tree / "scripts/script-helpers/helpers.sh").touch()
    (tree / "install.sh").touch()
    shutil.copy(REPO / "test", tree / "test")

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in STUBS.items():
        path = stubs / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    log = tmp_path / "stub.log"
    log.touch()

    def _run(*args: str, **env: str) -> tuple[subprocess.CompletedProcess, str]:
        full = {k: v for k, v in os.environ.items() if not k.startswith("NIKOS_TEST_")}
        full.update(HOME=str(home), PATH=f"{stubs}:/usr/bin:/bin", STUB_LOG=str(log),
                    STUB_VM_EXISTS="1", STUB_VM_STATE="running", STUB_GUEST_RELEASE="24.04",
                    STUB_CHECK_RC="0")
        full.update(env)
        r = subprocess.run(["/bin/bash", str(tree / "test"), *args], capture_output=True, text=True,
                           env=full, timeout=60)
        return r, log.read_text()

    _run.home = home
    return _run


def _downloaded(log: str) -> bool:
    # At line start: the checklist also sends "curl" to the guest through ssh.
    return any(line.startswith("curl ") for line in log.splitlines())


def _installer_ran(log: str) -> bool:
    return "nikos-install.sh" in log


# A VM that powers off by itself: the state -b needs to get through its wait.
BUILD_ENV = {"STUB_VM_STATE": "poweroff"}


def test_a_matching_guest_gets_the_installer_and_a_clean_run_exits_0(run):
    r, log = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert _installer_ran(log)
    assert "0 failed" in r.stdout


def test_a_guest_on_another_release_never_gets_the_installer(run):
    r, log = run(NIKOS_TEST_RELEASE="26.04", STUB_GUEST_RELEASE="24.04")
    assert r.returncode == 1
    assert "runs Ubuntu 24.04, but NIKOS_TEST_RELEASE is 26.04" in r.stderr
    assert not _installer_ran(log)


def test_a_guest_whose_release_cannot_be_read_never_gets_the_installer(run):
    r, log = run(STUB_GUEST_RELEASE="")
    assert r.returncode == 1
    assert not _installer_ran(log)


@pytest.mark.parametrize("variable", ["NIKOS_TEST_VM_RAM", "NIKOS_TEST_VM_CPUS", "NIKOS_TEST_VM_DISK"])
@pytest.mark.parametrize("args", [(), ("--show-config",)])
def test_a_resource_setting_without_build_is_refused(run, variable, args):
    r, log = run(*args, **{variable: "8192"})
    assert r.returncode == 1
    assert "apply only with -b" in r.stderr
    assert log == ""


@pytest.mark.parametrize("variable", ["NIKOS_TEST_VM_RAM", "NIKOS_TEST_VM_CPUS", "NIKOS_TEST_VM_DISK"])
@pytest.mark.parametrize("value", ["lots", "8G", "-1", "0", "1 2"])
@pytest.mark.parametrize("args", [("-b",), ("-b", "--show-config")])
def test_a_bad_resource_value_is_refused_before_the_vm_is_touched(run, variable, value, args):
    r, log = run(*args, **{variable: value}, **BUILD_ENV)
    assert r.returncode == 1
    assert f"{variable} must be a positive whole number" in r.stderr
    assert log == ""


def test_a_given_iso_that_is_missing_stops_before_the_download_and_the_wipe(run, tmp_path):
    r, log = run("-b", NIKOS_TEST_ISO=str(tmp_path / "gone.iso"), **BUILD_ENV)
    assert r.returncode == 1
    assert "NIKOS_TEST_ISO not found" in r.stderr
    assert not _downloaded(log)
    assert "unregistervm" not in log


def test_a_given_iso_below_the_floor_is_used_and_not_overwritten(run, tmp_path):
    iso = tmp_path / "custom.iso"
    iso.write_text("my image")
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), **BUILD_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert iso.read_text() == "my image"
    assert not _downloaded(log)
    assert f"--iso={iso}" in log


def _default_iso(run) -> Path:
    return run.home / "Downloads" / "xubuntu-24.04.4-desktop-amd64.iso"


def _no_wipe_and_no_leftovers(run, log: str) -> None:
    assert "unregistervm" not in log
    assert "createvm" not in log
    assert [p.name for p in run.home.glob("Downloads/*.part*")] == []


@pytest.mark.parametrize("env,message", [
    ({"STUB_CURL_404": "1"}, "Download failed"),
    ({"STUB_CURL_RC": "18"}, "Download failed"),
    ({}, "expected at least 1000000000"),
    ({"NIKOS_TEST_ISO_URL": "https://mirror.example/x.iso"}, "expected at least 1000000000"),
])
def test_a_bad_download_of_the_default_image_keeps_the_vm(run, env, message):
    r, log = run("-b", **env, **BUILD_ENV)
    assert r.returncode == 1
    assert message in r.stderr
    assert not _default_iso(run).exists()
    _no_wipe_and_no_leftovers(run, log)


@pytest.mark.parametrize("env", [{"STUB_CURL_404": "1"}, {}])
def test_a_bad_download_leaves_a_short_iso_as_it_was(run, env):
    iso = _default_iso(run)
    iso.write_text("short")
    r, log = run("-b", **env, **BUILD_ENV)
    assert r.returncode == 1
    assert iso.read_text() == "short"
    _no_wipe_and_no_leftovers(run, log)


def test_a_given_iso_and_url_that_404_keep_the_vm(run, tmp_path):
    iso = tmp_path / "custom.iso"
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), NIKOS_TEST_ISO_URL="https://mirror.example/c.iso",
                 STUB_CURL_404="1", **BUILD_ENV)
    assert r.returncode == 1
    assert not iso.exists()
    _no_wipe_and_no_leftovers(run, log)


def test_a_given_iso_and_url_refuse_an_empty_download(run, tmp_path):
    iso = tmp_path / "custom.iso"
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), NIKOS_TEST_ISO_URL="https://mirror.example/c.iso",
                 STUB_CURL_BYTES="0", **BUILD_ENV)
    assert r.returncode == 1
    assert "expected at least 1" in r.stderr
    assert not iso.exists()
    assert "unregistervm" not in log


def test_a_given_iso_with_a_url_is_not_fetched_again_once_present(run, tmp_path):
    iso = tmp_path / "custom.iso"
    iso.write_text("my image")
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), NIKOS_TEST_ISO_URL="https://mirror.example/c.iso",
                 **BUILD_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert iso.read_text() == "my image"
    assert not _downloaded(log)


def test_a_good_download_replaces_the_short_iso_before_the_wipe(run):
    iso = _default_iso(run)
    iso.write_text("short")
    r, log = run("-b", STUB_CURL_BYTES="1000000000", **BUILD_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert iso.stat().st_size == 1000000000
    assert log.index("curl ") < log.index("unregistervm")
    assert [p.name for p in run.home.glob("Downloads/*.part*")] == []


@pytest.mark.parametrize("variable", ["NIKOS_TEST_ISO", "NIKOS_TEST_ISO_URL"])
@pytest.mark.parametrize("args", [(), ("--show-config",)])
def test_an_iso_setting_without_build_is_refused(run, variable, args):
    r, log = run(*args, **{variable: "/isos/custom.iso"})
    assert r.returncode == 1
    assert "apply only with -b" in r.stderr
    assert log == ""


def test_a_given_iso_and_url_still_download(run, tmp_path):
    iso = tmp_path / "custom.iso"
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), NIKOS_TEST_ISO_URL="https://mirror.example/c.iso",
                 **BUILD_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "curl -fL https://mirror.example/c.iso" in log
    assert iso.read_text() == "default image\n"


def test_show_config_names_no_download_source_for_a_given_iso(run):
    r, _ = run("-b", "--show-config", NIKOS_TEST_ISO="/isos/custom.iso")
    assert r.returncode == 0
    assert "OS_ISO_URL=\n" in r.stdout


def test_the_missing_vm_hint_names_the_release_profile_and_vm(run):
    r, _ = run("--profile=server", "--vm-name=my vm", NIKOS_TEST_RELEASE="26.04",
               STUB_VM_EXISTS="0")
    assert r.returncode == 1
    assert "NIKOS_TEST_RELEASE=26.04 ./test -b --profile=server --vm-name=my\\ vm" in r.stderr


@pytest.mark.parametrize("args,env", [
    (("--vm-name=",), {}),
    (("--vm-name=.",), {}),
    (("--vm-name=..",), {}),
    (("--vm-name=a/b",), {}),
    (("--vm-name=../keep",), {}),
    ((), {"NIKOS_TEST_VM": ""}),
    ((), {"NIKOS_TEST_VM": "."}),
    ((), {"NIKOS_TEST_VM": ".."}),
    ((), {"NIKOS_TEST_VM": "../keep"}),
    (("--profile=server",), {"NIKOS_TEST_VM": ""}),
])
@pytest.mark.parametrize("mode", [("-b",), ("-b", "--show-config"), ()])
def test_a_vm_name_that_is_not_one_path_component_is_refused(run, tmp_path, mode, args, env):
    # HOME is the fixture's scratch directory, so a missed refusal cannot reach a real VM.
    disk = run.home / "VirtualBox VMs" / "other" / "other.vdi"
    disk.parent.mkdir(parents=True)
    disk.touch()
    keep = run.home / "VirtualBox VMs" / "a" / "b" / "b.vdi"
    keep.parent.mkdir(parents=True)
    keep.touch()
    iso = tmp_path / "custom.iso"
    iso.write_text("my image")
    build_env = {"NIKOS_TEST_ISO": str(iso), **BUILD_ENV} if mode and "--show-config" not in mode else {}
    r, log = run(*mode, *args, **env, **build_env)
    assert r.returncode == 1
    assert "VM name must not be empty" in r.stderr
    assert log == ""
    assert disk.exists() and keep.exists()


def test_a_good_flag_overrides_a_bad_vm_name_from_the_environment(run):
    r, _ = run("--show-config", "--vm-name=mine", NIKOS_TEST_VM="../keep")
    assert r.returncode == 0, r.stderr
    assert "VM_NAME=mine\n" in r.stdout


def test_an_empty_given_iso_with_no_url_stops_before_the_wipe(run, tmp_path):
    iso = tmp_path / "empty.iso"
    iso.touch()
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), **BUILD_ENV)
    assert r.returncode == 1
    assert "not found or empty" in r.stderr
    assert not _downloaded(log)
    assert "unregistervm" not in log


@pytest.mark.parametrize("url", [{}, {"NIKOS_TEST_ISO_URL": "https://mirror.example/c.iso"}])
def test_an_iso_path_that_is_not_a_file_stops_before_the_download_and_the_wipe(run, tmp_path, url):
    iso = tmp_path / "isodir"
    iso.mkdir()
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), **url, **BUILD_ENV)
    assert r.returncode == 1
    assert "not a regular file" in r.stderr
    assert list(iso.iterdir()) == []
    assert not _downloaded(log)
    assert "unregistervm" not in log


def test_a_directory_appearing_at_the_iso_path_during_the_download_keeps_the_vm(run, tmp_path):
    iso = tmp_path / "custom.iso"
    r, log = run("-b", NIKOS_TEST_ISO=str(iso), NIKOS_TEST_ISO_URL="https://mirror.example/c.iso",
                 STUB_CURL_MKDIR=str(iso), **BUILD_ENV)
    assert r.returncode == 1
    assert list(iso.iterdir()) == []
    assert [p.name for p in tmp_path.glob("custom.iso.part*")] == []
    assert "unregistervm" not in log


def test_a_failed_checklist_item_exits_1(run):
    r, _ = run(STUB_CHECK_RC="1")
    assert r.returncode == 1
    assert "1 failed" in r.stdout


@pytest.mark.parametrize("release,args,iso,real_size", [
    ("26.04", (), "xubuntu-26.04.1-desktop-amd64.iso", 5186390016),
    ("26.04", ("--profile=server",), "ubuntu-26.04.1-live-server-amd64.iso", 2927861760),
])
def test_the_26_04_floors_fit_the_real_isos(run, release, args, iso, real_size):
    path = run.home / "Downloads" / iso
    # Sparse files: a whole image passes, one 10 percent short is fetched again.
    path.touch()
    os.truncate(path, real_size)
    r, log = run("-b", *args, NIKOS_TEST_RELEASE=release, STUB_GUEST_RELEASE=release, **BUILD_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not _downloaded(log)

    os.truncate(path, real_size * 9 // 10)
    r, log = run("-b", *args, NIKOS_TEST_RELEASE=release, STUB_GUEST_RELEASE=release,
                 STUB_CURL_BYTES=str(real_size), **BUILD_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _downloaded(log)
    assert path.stat().st_size == real_size
