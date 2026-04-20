# Plymouth Boot Logo

## Files

| File | Purpose |
|---|---|
| `plymouth-logo-source.svg` | Inkscape-editable source — open this to make design changes |
| `plymouth-logo.svg` | Optimized production SVG — minimal, no Inkscape metadata |
| `plymouth-logo.png` | Pre-exported PNG committed to the repo — used directly by Ansible |

The Ansible playbook copies `plymouth-logo.png` into the Plymouth theme directory at deploy time.
No runtime tools (Inkscape, rsvg, etc.) are required on the target machine.

## Updating the logo

### 1. Edit the design

Open `plymouth-logo-source.svg` in Inkscape and make your changes.

### 2. Sync the optimized SVG

Export a clean version without Inkscape metadata using Inkscape's command-line:

```
inkscape plymouth-logo-source.svg --export-plain-svg=plymouth-logo.svg
```

Or use [svgo](https://github.com/svg/svgo) for a more aggressive optimization:

```
svgo plymouth-logo-source.svg -o plymouth-logo.svg
```

### 3. Re-export the PNG

```
inkscape plymouth-logo.svg \
  --export-filename=plymouth-logo.png \
  --export-width=512 --export-height=466
```

Commit all three files (`plymouth-logo-source.svg`, `plymouth-logo.svg`, `plymouth-logo.png`).
