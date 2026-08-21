"""Guards on the shipped SVG artwork.

The Whisker Menu button, the LightDM greeter and xfdesktop all reach these
files through gdk-pixbuf, which is far pickier than a browser or Inkscape. A
file that opens fine in an editor can still be undrawable on the panel, so the
checks here run on the repository copies rather than on an installed system.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"

SVG_ASSETS = sorted(ASSETS.glob("*.svg"))

# gdk-pixbuf picks a loader by matching the head of the file against each
# loader's signature, and the SVG signature is the literal "<svg". Anything
# ahead of the root element - most easily an XML comment - pushes it past the
# window gdk-pixbuf looks at, and loading fails with "Unrecognized image file
# format". 128 bytes is comfortably inside that window and leaves room for the
# XML declaration.
SNIFF_WINDOW_BYTES = 128

WALLPAPERS = [ASSETS / "wallpaper.svg", ASSETS / "wallpaper-vertical.svg"]

# The flat backdrop colour NikOS also writes into the xfdesktop rgba1 property.
BACKDROP_COLOUR = "#2e3440"


def test_svg_assets_exist() -> None:
    assert SVG_ASSETS, "no SVG assets found to check"


@pytest.mark.parametrize("svg", SVG_ASSETS, ids=lambda p: p.name)
def test_root_element_is_within_the_gdk_pixbuf_sniff_window(svg: Path) -> None:
    head = svg.read_bytes()[:SNIFF_WINDOW_BYTES]
    assert b"<svg" in head, (
        f"{svg.name}: '<svg' must appear in the first {SNIFF_WINDOW_BYTES} bytes. "
        "Move any comment inside the root element, otherwise gdk-pixbuf cannot "
        "identify the file and consumers draw a missing-image placeholder."
    )


@pytest.mark.parametrize("svg", WALLPAPERS, ids=lambda p: p.name)
def test_wallpaper_backdrop_is_flat(svg: Path) -> None:
    """The wallpaper is drawn Scaled, so the desktop colour fills the rest.

    A gradient or a glow makes the image edge visible as a frame around the
    artwork on any screen that is not 16:9, so the backdrop has to stay a
    single flat colour that matches what xfconf paints behind it.
    """
    text = svg.read_text(encoding="utf-8")
    assert "linearGradient" not in text and "radialGradient" not in text, (
        f"{svg.name}: the backdrop must be flat, not a gradient."
    )
    assert BACKDROP_COLOUR in text, (
        f"{svg.name}: the backdrop must use {BACKDROP_COLOUR}, "
        "the colour NikOS writes into the xfdesktop rgba1 property."
    )


@pytest.mark.parametrize("svg", WALLPAPERS, ids=lambda p: p.name)
def test_wallpaper_keeps_its_wordmark_and_taglines(svg: Path) -> None:
    text = svg.read_text(encoding="utf-8")
    for phrase in ("NikOS", "Neural Innovation for Knowledge OS",
                   "LIGHT SYSTEM. HEAVY THINKING."):
        assert phrase in text, f"{svg.name}: lost the '{phrase}' text"


def test_wallpaper_backdrop_matches_the_xfconf_backdrop_colour() -> None:
    """#2e3440 as GdkRGBA doubles, as stored in xfce4-desktop.xml."""
    xml = (REPO_ROOT / "roles/theming/files/xfce4-desktop.xml").read_text(encoding="utf-8")
    values = [float(v) for v in re.findall(r'<value type="double" value="([0-9.]+)"/>', xml)]
    assert len(values) == 4, "expected four rgba1 components"
    expected = [int(BACKDROP_COLOUR[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1.0]
    for got, want in zip(values, expected):
        assert abs(got - want) < 0.001, f"rgba1 {values} does not match {BACKDROP_COLOUR}"
