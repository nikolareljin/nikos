# Third-party notices

NikOS is MIT licensed. One file is not, because it is derived from GPL-licensed
work. That file carries its own notice, and this page records the exception so
it is discoverable without reading the tree.

## roles/theming/files/plymouth/nikos.script

**GPL-3.0-or-later**, not MIT.

- Copyright (C) 2011 The Xubuntu Community
- Copyright (C) 2009 Canonical Ltd.
- Copyright (C) 2026 Nikola Reljin

Derived from `xubuntu-logo.script`, shipped in the `xubuntu-artwork` package
and installed at `/usr/share/plymouth/themes/xubuntu-logo/xubuntu-logo.script`.

The NikOS boot splash was written by working from that file, and kept parts of
its implementation:

| Retained from upstream | Relationship to the original |
|---|---|
| `strlen()` | Identical after whitespace normalisation |
| `atoi()` | Identical apart from renaming `int` to `value` |
| Colon-separated status parsing loop | Line-for-line identical apart from renaming `tmp_char` and `elem_count` |
| Message-line shifting | Same structure |
| Per-device fsck aggregation | Same structure |

The layout, logo scaling, spinner animation, progress-bar helpers, passphrase
bullet row, boot-progress handling and quit handling are original to NikOS.

GPL-3.0-or-later and MIT are not the same terms, and the GPL ones govern this
file. Anyone redistributing NikOS, or this theme on its own, has to carry the
GPL notice and offer the corresponding source for it.

A full copy of the licence is at [`LICENSES/GPL-3.0-or-later.txt`](LICENSES/GPL-3.0-or-later.txt).

## Everything else

MIT, as stated in [`LICENSE`](LICENSE).
