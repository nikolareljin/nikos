"""Guards on the Plymouth boot splash.

The splash cannot be exercised locally: plymouthd draws on a framebuffer it
takes exclusive control of, and Ubuntu ships no X11 renderer to preview it
against. A mistake here surfaces at the next reboot, on a screen with no way
to report an error, so the cheap structural checks are worth having.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
THEME_DIR = REPO_ROOT / "roles/theming/files/plymouth"
SCRIPT = THEME_DIR / "nikos.script"
ASSET_DIR = REPO_ROOT / "assets/plymouth"

SPINNER_FRAMES = 36

# Callbacks the splash has to register. A theme missing the password handler
# looks fine until it meets an encrypted disk, and then it waits on a
# passphrase with nothing on screen to say so.
REQUIRED_HANDLERS = [
    "Plymouth.SetRefreshFunction",
    "Plymouth.SetBootProgressFunction",
    "Plymouth.SetDisplayPasswordFunction",
    "Plymouth.SetDisplayNormalFunction",
    "Plymouth.SetMessageFunction",
    "Plymouth.SetUpdateStatusFunction",
    "Plymouth.SetQuitFunction",
]


@pytest.fixture(scope="module")
def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_theme_descriptor_points_at_the_script() -> None:
    descriptor = (THEME_DIR / "nikos.plymouth").read_text(encoding="utf-8")
    assert "ModuleName=script" in descriptor
    assert "nikos.script" in descriptor


@pytest.mark.parametrize("handler", REQUIRED_HANDLERS)
def test_script_registers_handler(script_text: str, handler: str) -> None:
    assert f"{handler}(" in script_text, f"nikos.script never registers {handler}"


def test_every_image_the_script_loads_is_committed(script_text: str) -> None:
    """Image() takes a bare filename resolved against ImageDir at boot.

    A name with no matching file yields a null image, and the splash dies on
    the first method call against it.
    """
    literal = set(re.findall(r'Image\("([^"]+)"\)', script_text))
    for name in sorted(literal):
        assert (ASSET_DIR / name).is_file(), f"nikos.script loads missing asset {name}"


def test_spinner_frames_are_complete() -> None:
    """The frame names are built by string concatenation, not globbed.

    A gap in the sequence is only visible as a stutter at boot, so the count
    and the padding are checked here instead.
    """
    frames = sorted(ASSET_DIR.glob("spinner-*.png"))
    assert len(frames) == SPINNER_FRAMES, f"expected {SPINNER_FRAMES} spinner frames"
    for index in range(1, SPINNER_FRAMES + 1):
        assert (ASSET_DIR / f"spinner-{index:04d}.png").is_file(), (
            f"spinner frame {index} is missing"
        )


def test_script_frame_count_matches_the_rendered_frames(script_text: str) -> None:
    match = re.search(r"SPINNER_FRAMES\s*=\s*(\d+)", script_text)
    assert match, "nikos.script no longer declares SPINNER_FRAMES"
    assert int(match.group(1)) == SPINNER_FRAMES


def test_generator_and_script_agree_on_frame_count() -> None:
    generator = (REPO_ROOT / "scripts/render-plymouth-assets.py").read_text(encoding="utf-8")
    match = re.search(r"SPINNER_FRAMES\s*=\s*(\d+)", generator)
    assert match, "the generator no longer declares SPINNER_FRAMES"
    assert int(match.group(1)) == SPINNER_FRAMES


def test_spinner_name_building_covers_every_frame(script_text: str) -> None:
    """The script pads frame numbers by hand, in two branches.

    Both branches have to exist, otherwise every frame past nine resolves to a
    name that is not on disk.
    """
    assert '"spinner-000" + n' in script_text
    assert '"spinner-00" + n' in script_text


def test_braces_and_parentheses_balance(script_text: str) -> None:
    stripped = re.sub(r"#.*", "", script_text)
    stripped = re.sub(r'"[^"\n]*"', '""', stripped)
    for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
        assert stripped.count(opener) == stripped.count(closer), (
            f"nikos.script has unbalanced {opener}{closer}"
        )


def test_assets_are_transparent_and_desaturated() -> None:
    """Boot chrome sits on a near-black background.

    An opaque background would show as a rectangle around each element, so
    every asset has to be RGBA. Saturation is measured on the composite over
    the background colour nikos.script sets, not on the raw pixels: librsvg
    stores premultiplied alpha, and unpremultiplying a nearly transparent
    antialiased edge amplifies rounding into channel spreads that never reach
    the screen.

    The colours are the Nord cool greys rather than pure neutrals, so the
    bound is a saturation ceiling. The widest of them, #4c566a, spans 30; the
    mark's blue spans 210, which is what the bound is here to catch being
    carried into the boot set.
    """
    image_module = pytest.importorskip("PIL.Image", reason="Pillow is not installed")

    # Window.SetBackgroundTopColor in nikos.script, as 8-bit channels.
    background = (13, 13, 20)
    max_channel_spread = 32

    for path in sorted(ASSET_DIR.glob("*.png")):
        image = image_module.open(path)
        assert image.mode == "RGBA", f"{path.name} is {image.mode}, not RGBA"

        rgba = image.convert("RGBA")
        composite = image_module.new("RGB", rgba.size, background)
        composite.paste(rgba, mask=rgba.getchannel("A"))

        pixels = composite.tobytes()
        for offset in range(0, len(pixels), 3):
            red, green, blue = pixels[offset:offset + 3]
            spread = max(red, green, blue) - min(red, green, blue)
            assert spread <= max_channel_spread, (
                f"{path.name} carries a colour cast at rgb({red}, {green}, {blue})"
            )
