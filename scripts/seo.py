#!/usr/bin/env python3
"""Search and share metadata for every page under site/, from one place.

Each page carries one block between `<!-- seo -->` and `<!-- /seo -->`: meta
description, keywords, canonical URL, Open Graph and Twitter card tags, and JSON-LD
(`SoftwareApplication` on the home page, `WebPage` elsewhere). The pages are
described in PAGES below; `--write` rewrites each block in place and site/sitemap.xml.

    python3 scripts/seo.py --write   # rewrite the blocks and sitemap.xml
    python3 scripts/seo.py --check   # exit 1 if anything is missing, stale or duplicated

No robots.txt: this is a GitHub Pages project site, served under /nikos/, and
crawlers only read robots.txt at the host root. Submit
https://nikolareljin.github.io/nikos/sitemap.xml in Google Search Console instead.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
SITE = "https://nikolareljin.github.io/nikos/"
REPO = "https://github.com/nikolareljin/nikos"
# 1200x630: the size Open Graph and Twitter's large card display without cropping.
IMAGE = SITE + "assets/og-image.png"
IMAGE_SIZE = (1200, 630)
IMAGE_ALT = "The NikOS desktop: Xfce in Nord colours on Ubuntu LTS"
DESCRIPTION_MAX = 160
VERIFICATION = re.compile(r"google[0-9a-f]+\.html")
BLOCK = re.compile(r"[ \t]*<!-- seo -->.*?<!-- /seo -->\n?", re.S)

SITE_KEYWORDS = ["NikOS", "AI workstation", "Ubuntu", "Ansible", "Ollama", "local AI"]

PAGES = {
    "index.html": {
        "title": "NikOS — an AI workstation built on Ubuntu LTS",
        "description": "An Ansible playbook that turns Ubuntu 22.04, 24.04 or 26.04 into a "
                       "local-first AI workstation: Xfce, Ollama, a conda AI stack and tools.",
        "keywords": ["local LLM", "Xubuntu", "developer workstation", "conda", "open source"],
        "kind": "app",
    },
    "install.html": {
        "title": "Installing NikOS",
        "description": "Install NikOS on Ubuntu 22.04, 24.04 or 26.04: requirements, the three "
                       "install modes, first boot, updating, and recovery.",
        "keywords": ["install", "Ubuntu setup", "nikos update", "recovery"],
        "kind": "page",
    },
    "included.html": {
        "title": "What NikOS installs",
        "description": "The full NikOS inventory: core roles, optional bundles, the Python AI "
                       "stack, Ollama models per machine class, and the nikos CLI.",
        "keywords": ["Ollama models", "AI tools", "Python AI stack", "VS Code"],
        "kind": "page",
    },
    "help.html": {
        "title": "NikOS — Help",
        "description": "Where to find help for NikOS, and for the Xubuntu desktop it is built on.",
        "keywords": ["help", "troubleshooting", "Xubuntu"],
        "kind": "page",
    },
    "about.html": {
        "title": "About — Nik Reljin",
        "description": "Nik Reljin builds local-first AI tooling, developer infrastructure and "
                       "security tools. NikOS is one of them; here are the others.",
        "keywords": ["about", "Nik Reljin"],
        "kind": "page",
    },
}


def _url(name: str) -> str:
    return SITE if name == "index.html" else SITE + name


def _json_ld(name: str, page: dict) -> dict:
    app = {"@type": "SoftwareApplication", "name": "NikOS", "url": SITE,
           "applicationCategory": "DeveloperApplication", "operatingSystem": "Ubuntu",
           "author": {"@type": "Person", "name": "Nik Reljin"}}
    if page["kind"] == "app":
        return {"@context": "https://schema.org", **app, "description": page["description"],
                "license": "https://opensource.org/licenses/MIT",
                "downloadUrl": REPO + "/releases", "codeRepository": REPO, "image": IMAGE,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "keywords": ", ".join(SITE_KEYWORDS + page["keywords"])}
    return {"@context": "https://schema.org", "@type": "WebPage", "name": page["title"],
            "url": _url(name), "description": page["description"], "about": app}


def head_for(name: str) -> str:
    """The `<!-- seo -->` block for one page, as it sits in the page's <head>."""
    page = PAGES[name]
    esc = lambda s: html.escape(s, quote=True)  # noqa: E731
    keywords = ", ".join(dict.fromkeys(page["keywords"] + SITE_KEYWORDS))
    og_type = "website" if page["kind"] == "app" else "article"
    # "</" cannot appear inside a script element; JSON allows the escaped slash.
    ld = json.dumps(_json_ld(name, page), ensure_ascii=False, separators=(",", ":"))
    ld = ld.replace("</", "<\\/")
    lines = [
        "<!-- seo -->",
        f'<meta name="description" content="{esc(page["description"])}">',
        f'<meta name="keywords" content="{esc(keywords)}">',
        '<meta name="author" content="Nik Reljin">',
        f'<link rel="canonical" href="{esc(_url(name))}">',
        '<meta property="og:site_name" content="NikOS">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{esc(page["title"])}">',
        f'<meta property="og:description" content="{esc(page["description"])}">',
        f'<meta property="og:url" content="{esc(_url(name))}">',
        f'<meta property="og:image" content="{IMAGE}">',
        f'<meta property="og:image:width" content="{IMAGE_SIZE[0]}">',
        f'<meta property="og:image:height" content="{IMAGE_SIZE[1]}">',
        f'<meta property="og:image:alt" content="{esc(IMAGE_ALT)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{esc(page["title"])}">',
        f'<meta name="twitter:description" content="{esc(page["description"])}">',
        f'<meta name="twitter:image" content="{IMAGE}">',
        f'<meta name="twitter:image:alt" content="{esc(IMAGE_ALT)}">',
        f'<script type="application/ld+json">{ld}</script>',
        "<!-- /seo -->",
    ]
    return "\n".join(lines) + "\n"


def sitemap() -> str:
    names = sorted(PAGES, key=lambda n: (n != "index.html", n))
    urls = "".join(f"  <url><loc>{_url(n)}</loc></url>\n" for n in names)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}</urlset>\n")


def with_block(name: str, text: str, block: str) -> str:
    """Replace the page's block, or insert it after <title> (dropping the old description)."""
    if BLOCK.search(text):
        return BLOCK.sub(lambda _m: block, text, count=1)
    text = re.sub(r'[ \t]*<meta name="description"[^>]*>\n?', "", text, count=1)
    text, count = re.subn(r"(</title>[ \t]*)\n?", lambda m: m.group(1) + "\n" + block, text, count=1)
    if count == 0:
        raise SystemExit(f"site/{name}: no </title> to put the SEO block after")
    return text


def problems(site_dir: Path = SITE_DIR) -> list[str]:
    found = []
    seen: dict[str, str] = {}
    for name, page in PAGES.items():
        desc = page["description"]
        if not desc:
            found.append(f"{name}: no description")
        elif len(desc) > DESCRIPTION_MAX:
            found.append(f"{name}: description is {len(desc)} chars, max {DESCRIPTION_MAX}")
        if desc in seen:
            found.append(f"{name}: same description as {seen[desc]}")
        seen.setdefault(desc, name)
        path = site_dir / name
        if not path.is_file():
            found.append(f"site/{name} is missing")
            continue
        text = path.read_text(encoding="utf-8")
        if head_for(name) not in text:
            found.append(f"site/{name}: SEO block missing or stale - run: python3 scripts/seo.py --write")
        title = re.search(r"<title>(.*?)</title>", text, re.S)
        if not title or html.unescape(title.group(1)) != page["title"]:
            found.append(f"site/{name}: <title> does not match the og:title in scripts/seo.py")
        for tag in ('name="description"', 'rel="canonical"', 'property="og:title"'):
            if text.count(tag) != 1:
                found.append(f"site/{name}: expected exactly one {tag} tag")
    # A page on the site that is not described here gets no metadata and no sitemap entry.
    for path in sorted(site_dir.glob("*.html")):
        # Search Console's ownership file is not a page: no metadata, no sitemap entry.
        if path.name not in PAGES and not VERIFICATION.fullmatch(path.name):
            found.append(f"site/{path.name} is not in PAGES (scripts/seo.py)")
    sm = site_dir / "sitemap.xml"
    if not sm.is_file() or sm.read_text(encoding="utf-8") != sitemap():
        found.append("site/sitemap.xml is stale - run: python3 scripts/seo.py --write")
    if not (site_dir / IMAGE.removeprefix(SITE)).is_file():
        found.append(f"site/{IMAGE.removeprefix(SITE)} is missing (the share image)")
    return found


def write(site_dir: Path = SITE_DIR) -> None:
    for name in PAGES:
        path = site_dir / name
        text = path.read_text(encoding="utf-8")
        path.write_text(with_block(name, text, head_for(name)), encoding="utf-8")
    (site_dir / "sitemap.xml").write_text(sitemap(), encoding="utf-8")


def main(argv: list[str]) -> int:
    if argv == ["--write"]:
        write()
        return 0
    if argv == ["--check"]:
        found = problems()
        for p in found:
            print(f"  - {p}")
        return 1 if found else 0
    print("usage: scripts/seo.py --write | --check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
