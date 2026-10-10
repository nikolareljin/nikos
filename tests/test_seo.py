"""scripts/seo.py: every site page carries one current SEO block, and the check
catches each way that goes wrong. Each failure case breaks a copy of site/."""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import seo  # noqa: E402


@pytest.fixture
def site(tmp_path):
    copy = tmp_path / "site"
    shutil.copytree(ROOT / "site", copy)
    return copy


def test_the_published_site_passes():
    assert seo.problems() == []


def test_write_is_idempotent(site):
    before = {p.name: p.read_text() for p in site.glob("*.html")}
    seo.write(site)
    assert {p.name: p.read_text() for p in site.glob("*.html")} == before


def test_every_json_ld_block_parses():
    for name in seo.PAGES:
        text = (ROOT / "site" / name).read_text()
        ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', text).group(1)
        assert json.loads(ld)["@context"] == "https://schema.org"


def test_descriptions_fit_and_differ():
    descs = [p["description"] for p in seo.PAGES.values()]
    assert all(0 < len(d) <= seo.DESCRIPTION_MAX for d in descs)
    assert len(set(descs)) == len(descs)


def test_a_stale_block_is_caught(site):
    page = site / "install.html"
    page.write_text(page.read_text().replace("three install modes", "two install modes", 1))
    assert any("install.html: SEO block missing or stale" in p for p in seo.problems(site))


def test_a_changed_title_is_caught(site):
    page = site / "help.html"
    page.write_text(page.read_text().replace("<title>NikOS — Help</title>", "<title>Help</title>"))
    assert any("help.html: <title> does not match" in p for p in seo.problems(site))


def test_a_second_description_is_caught(site):
    page = site / "about.html"
    page.write_text(page.read_text().replace("</head>", '<meta name="description" content="x">\n</head>'))
    assert any('about.html: expected exactly one name="description"' in p for p in seo.problems(site))


def test_a_new_page_without_metadata_is_caught(site):
    (site / "faq.html").write_text("<html><head><title>FAQ</title></head></html>")
    assert any("faq.html is not in PAGES" in p for p in seo.problems(site))


def test_a_stale_sitemap_and_a_missing_image_are_caught(site):
    (site / "sitemap.xml").write_text("")
    (site / "assets/og-image.png").unlink()
    found = seo.problems(site)
    assert any("sitemap.xml is stale" in p for p in found)
    assert any("og-image.png is missing" in p for p in found)


def test_a_page_with_no_title_is_refused():
    with pytest.raises(SystemExit):
        seo.with_block("x.html", "<html><head></head></html>", "<!-- seo -->\n<!-- /seo -->\n")


def test_the_share_image_is_the_card_size():
    # Width and height from the PNG header, so the test needs no image library.
    head = (ROOT / "site/assets/og-image.png").read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    assert (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")) == seo.IMAGE_SIZE


def test_the_search_console_file_is_not_a_page(site):
    assert any(p.name.startswith("google") for p in site.glob("google*.html"))
    assert seo.problems(site) == []
    assert "google" not in seo.sitemap()
