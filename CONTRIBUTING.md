# Contributing to NikOS

Contributions are welcome: bug reports, fixes, new optional bundles,
documentation, and testing on a wide range of machines and setups.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Report a problem

[Open an issue](https://github.com/nikolareljin/nikos/issues/new/choose) and
pick **Bug report**. The form asks for what helps most:

- NikOS version (`nikos status` or `cat ~/.local/share/nikos/VERSION`)
- Ubuntu or Xubuntu release (22.04, 24.04 or 26.04) and how you installed
- what you ran, what you expected, what happened
- the **log digest**: the block at the end of the install or update log, from
  `=== NikOS log digest ===` to `=== end of digest ===`. It lists every failed
  task with its message, so it is usually enough to find the cause:

  ```bash
  # after an install
  sed -n '/=== NikOS log digest/,/=== end of digest/p' ~/.config/nikos/logs/install-latest.log
  # after nikos update
  sed -n '/=== NikOS log digest/,/=== end of digest/p' ~/.config/nikos/logs/playbook-latest.log
  ```

Check the [debugging guide](docs/debugging.md) and the
[open issues](https://github.com/nikolareljin/nikos/issues) first; a comment
with your details on an existing issue helps as much as a new one.

Security problems go through the [security policy](SECURITY.md), not a public
issue.

## Suggest a change

Pick **Feature request** in the issue form: what you want, why, and what you do
today instead. Questions and ideas that are not yet a request fit
[Discussions](https://github.com/nikolareljin/nikos/discussions).

## Work on the code

1. Fork, then branch from `main` (or from an open `release/X.Y.Z` branch when
   the maintainer says a change belongs to it).
2. Read [docs/development.md](docs/development.md): layout, roles, tags, and how
   to run a role on its own.
3. Make the change, with a test under `tests/` that fails without it.
4. Run what CI runs:

   ```bash
   python3 -m pytest tests -q
   ansible-lint site.yml
   shellcheck install.sh scripts/nikos scripts/nikos-progress.sh scripts/nikos-tools.sh \
     scripts/distrodeck-version.sh scripts/repo-sync.sh scripts/install-collections.sh \
     scripts/verify-key-fingerprint.sh roles/theming/files/nikos-apply-wallpaper.sh
   ansible-playbook site.yml -i inventory/local --check --skip-tags network,music,education --ask-become-pass
   ```

   CI also runs the `--check` playbook on Ubuntu 22.04, 24.04 and 26.04.
5. Add a line under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md): what
   changed and why, in a sentence or two.
6. Open a pull request. The template asks what changed, why, and how you
   tested it.

### Rules every change follows

- **Verified sources only.** Nothing is installed from an unverified source: no
  `curl | sh`, no `@latest`, no `releases/latest`, no branch-head clones.
  Downloads are pinned to a version and checked against a sha256, apt keys
  against a fingerprint, npm/pip/go installs use exact versions. Every pin
  lives in [`vars/versions.yml`](vars/versions.yml) with its hash;
  `scripts/bump-versions.py --check` and `--bump` help keep them current.
  `tests/test_pinned_sources.py` enforces this.
- **Never downgrade.** On `nikos update` a pin is a minimum: a newer version the
  user installed is left alone (`roles/pin-gate`).
- **Safe to re-run.** `nikos update` re-runs the whole playbook on every
  machine, so a task must converge: running it again must not break or
  duplicate anything.
- **Works on 22.04, 24.04 and 26.04.** Package names that differ per release go
  in `nikos_ubuntu_releases` in `vars/main.yml`; a release that lacks something
  skips it with a clear message.
- **No fixed `/tmp` paths.** Use `nikos_root_download_dir`,
  `nikos_user_download_dir` or `nikos_key_staging_dir`.
- **Keep PRs focused.** One concern per PR is easiest to review.

## Releases

The maintainer cuts releases from `release/X.Y.Z` branches; merging one into
`main` tags it and publishes the GitHub release. Contributors do not need to
bump `VERSION`.
