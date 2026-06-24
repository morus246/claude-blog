#!/usr/bin/env python3
"""blog_hygiene.py: Deterministic structural auto-fixes for blog posts.

Runs after blog_render.py and before Gate 3 of the Blog Delivery Contract
to auto-apply fixes that do not require editorial judgment:

  1. HTML: add loading="lazy" to <img> tags missing the attribute.
  2. HTML: warn on <img> tags missing alt text (cannot invent alt text).
  3. Markdown: insert a TOC block before the first body H2 on posts >2000
     words if no TOC is already present.

Output: JSON to stdout; {lazy_fixed, alt_warned, toc_inserted, warnings}
Exit code: 0 always (hygiene never blocks delivery).

Usage:
    python3 scripts/blog_hygiene.py --md <slug>.md [--html <slug>.html]
    python3 scripts/blog_hygiene.py --html <slug>.html          # HTML only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path


def _slugify(text: str) -> str:
    """Convert heading text to a URL-friendly anchor slug.

    Strips accents (NFKD decomposition), lowercases, removes punctuation
    except hyphens, replaces spaces with hyphens.
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def fix_html_lazy_loading(html: str) -> tuple[str, int]:
    """Add loading="lazy" to <img> tags that lack a loading attribute.

    Returns (modified_html, count_fixed). Writes to disk only if caller
    decides; this function is pure.
    """
    count = 0

    def _add_lazy(m: re.Match) -> str:
        nonlocal count
        tag = m.group(0)
        if re.search(r"\bloading=", tag, re.IGNORECASE):
            return tag
        count += 1
        return tag[:4] + ' loading="lazy"' + tag[4:]

    result = re.sub(r"<img\b[^>]*>", _add_lazy, html, flags=re.IGNORECASE | re.DOTALL)
    return result, count


def warn_missing_alt(html: str) -> list[str]:
    """Return list of img srcs missing alt attributes (cannot auto-fix)."""
    missing = []
    for m in re.finditer(r"<img\b([^>]*)>", html, re.IGNORECASE | re.DOTALL):
        attrs = m.group(1)
        if not re.search(r"\balt=", attrs, re.IGNORECASE):
            src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            src = src_m.group(1) if src_m else "(unknown)"
            missing.append(src)
    return missing


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter block and return body only."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def _count_words(text: str) -> int:
    """Count words in body text, stripping HTML and markdown syntax."""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"[*_`#\[\]()>~]", " ", clean)
    return len(clean.split())


def _extract_h2s(body: str) -> list[tuple[str, str]]:
    """Extract all H2 headings. Returns list of (heading_text, slug)."""
    h2s = []
    for m in re.finditer(r"^## (.+)$", body, re.MULTILINE):
        text = m.group(1).strip()
        slug = _slugify(text)
        if slug:
            h2s.append((text, slug))
    return h2s


def _toc_already_present(text: str) -> bool:
    """Return True if a TOC block is already in the document."""
    markers = (
        "**Neste artigo:**",
        "**In this article:**",
        "**Table of Contents**",
        "**Sumario:**",
        "**Indice:**",
    )
    return any(m in text for m in markers)


def _detect_lang(md: str) -> str:
    """Detect post language from frontmatter lang field."""
    m = re.search(r'^lang:\s*["\']?([^"\'\n]+)["\']?', md, re.MULTILINE)
    if m:
        lang_val = m.group(1).strip()
        if lang_val.startswith("en"):
            return "en"
    return "pt"


def _build_toc(h2s: list[tuple[str, str]], lang: str = "pt") -> str:
    """Build a TOC markdown block from a list of (heading_text, slug) pairs."""
    label = "**Neste artigo:**" if lang == "pt" else "**In this article:**"
    lines = [label]
    for text, slug in h2s:
        lines.append(f"- [{text}](#{slug})")
    return "\n".join(lines)


def insert_toc(md: str) -> tuple[str, bool]:
    """Insert TOC before the first body H2 when post >2000 words and no TOC exists.

    Returns (modified_md, toc_inserted).
    """
    body = _strip_frontmatter(md)
    if _count_words(body) <= 2000:
        return md, False
    if _toc_already_present(md):
        return md, False

    h2s = _extract_h2s(body)
    if not h2s:
        return md, False

    lang = _detect_lang(md)
    toc_block = _build_toc(h2s, lang)

    first_h2 = re.search(r"^## ", md, re.MULTILINE)
    if not first_h2:
        return md, False

    pos = first_h2.start()
    modified = md[:pos] + toc_block + "\n\n" + md[pos:]
    return modified, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blog structural hygiene auto-fixer")
    parser.add_argument("--md", type=Path, metavar="FILE", help="Markdown source file")
    parser.add_argument("--html", type=Path, metavar="FILE", help="Rendered HTML file")
    args = parser.parse_args(argv)

    result: dict = {
        "lazy_fixed": 0,
        "alt_warned": 0,
        "toc_inserted": False,
        "warnings": [],
    }

    if args.html:
        if not args.html.exists():
            result["warnings"].append(f"html file not found: {args.html}")
        else:
            html = args.html.read_text(encoding="utf-8")

            fixed_html, lazy_count = fix_html_lazy_loading(html)
            result["lazy_fixed"] = lazy_count
            if lazy_count > 0:
                args.html.write_text(fixed_html, encoding="utf-8")

            missing_alt = warn_missing_alt(fixed_html)
            result["alt_warned"] = len(missing_alt)
            for src in missing_alt:
                result["warnings"].append(f"img missing alt text: {src}")

    if args.md:
        if not args.md.exists():
            result["warnings"].append(f"md file not found: {args.md}")
        else:
            md = args.md.read_text(encoding="utf-8")
            modified_md, toc_inserted = insert_toc(md)
            result["toc_inserted"] = toc_inserted
            if toc_inserted:
                args.md.write_text(modified_md, encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
