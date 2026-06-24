#!/usr/bin/env python3
"""Deploy a blog post from a claude-blog draft folder to fabiomorus.com.

Usage:
    python scripts/deploy_post.py --draft content/<slug>/ --category <cat> [--dry-run]

--dry-run: runs steps 1-10 (including pnpm build) but skips step 11 (deploy.sh).

Exit codes: 0 = success, 1 = failure (JSON error on stderr).
Stdout on success:
    {"status": "ok", "pt_url": "...", ["en_url": "..."], "hero": "/blog/<slug>-hero.webp"}
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


_REMOVE_PT = frozenset({"ogImage", "canonical"})
_REMOVE_EN = frozenset({"ogImage", "canonical", "locale", "translatedFrom", "translatedDate", "slug"})


def _get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _fail(message: str, extra: Optional[dict] = None) -> None:
    payload = {"error": "deploy-failed", "message": message, **(extra or {})}
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(1)


def _load_config(root: Path) -> dict:
    cfg = root / ".deploy.json"
    if not cfg.exists():
        _fail(".deploy.json not found. Create it with `site` pointing to the fabiomorus repo.")
    try:
        return json.loads(cfg.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f".deploy.json is invalid JSON: {e}")


def _find_canonical_md(draft: Path) -> Path:
    candidates = [f for f in draft.glob("*.md") if f.name != "review.md"]
    if not candidates:
        _fail(f"No canonical .md found in {draft}.")
    slug = draft.name
    preferred = [f for f in candidates if f.stem == slug]
    return preferred[0] if preferred else candidates[0]


def _find_hero(draft: Path) -> Path:
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        p = draft / f"hero{ext}"
        if p.exists():
            return p
    _fail(f"No hero image in `{draft}`. Run Phase 6.5 Gate 1 first.")


def _to_webp(src: Path, dest: Path) -> None:
    try:
        from PIL import Image  # type: ignore
        with Image.open(src) as img:
            img.save(dest, "WEBP", quality=85)
        return
    except ImportError:
        pass
    except Exception as e:
        print(f"[deploy] webp conversion failed ({e}); copying as-is", file=sys.stderr)
    shutil.copy2(src, dest)


def _parse_frontmatter_full(text: str) -> tuple[str, str]:
    """Return (raw_fm_block, body). raw_fm_block excludes the --- delimiters."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    fm_raw = text[3:end + 1]
    body = text[end + 4:]
    return fm_raw, body


def _normalize_pt_frontmatter(
    fm_text: str, slug: str, en_slug: Optional[str],
    category: Optional[str], hero_rel: str
) -> str:
    lines = fm_text.splitlines()
    out: list[str] = []
    seen: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        if ": " not in line and not line.endswith(":"):
            out.append(line)
            continue
        key = line.split(":")[0].strip()
        if key in _REMOVE_PT:
            continue
        if key == "coverImage":
            out.append(f'image: "{hero_rel}"')
            seen.add("image")
            continue
        if key == "image":
            out.append(f'image: "{hero_rel}"')
            seen.add("image")
            continue
        if key == "coverImageAlt":
            val = line.partition(": ")[2]
            out.append(f"imageAlt: {val}")
            seen.add("imageAlt")
            continue
        if key == "lastUpdated":
            val = line.partition(": ")[2]
            out.append(f"lastmod: {val}")
            seen.add("lastmod")
            continue
        if key == "author":
            out.append('author: "Fabio Morus"')
            seen.add("author")
            continue
        out.append(line)
        seen.add(key)

    if "lang" not in seen:
        out.append('lang: "pt-BR"')
    if "draft" not in seen:
        out.append("draft: false")
    if category and "category" not in seen:
        out.append(f'category: "{category}"')
    if en_slug and "translationKey" not in seen:
        out.append(f'translationKey: "pair-{slug}-{en_slug}"')
    if "image" not in seen:
        out.append(f'image: "{hero_rel}"')

    return "\n".join(out)


def _normalize_en_frontmatter(
    fm_text: str, slug: str, en_slug: str,
    category: Optional[str], hero_rel: str
) -> str:
    lines = fm_text.splitlines()
    out: list[str] = []
    seen: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        if ": " not in line and not line.endswith(":"):
            out.append(line)
            continue
        key = line.split(":")[0].strip()
        if key in _REMOVE_EN:
            continue
        if key == "coverImage":
            out.append(f'image: "{hero_rel}"')
            seen.add("image")
            continue
        if key == "image":
            out.append(f'image: "{hero_rel}"')
            seen.add("image")
            continue
        if key == "coverImageAlt":
            val = line.partition(": ")[2]
            out.append(f"imageAlt: {val}")
            seen.add("imageAlt")
            continue
        if key == "lastUpdated":
            val = line.partition(": ")[2]
            out.append(f"lastmod: {val}")
            seen.add("lastmod")
            continue
        if key == "author":
            out.append('author: "Fabio Morus"')
            seen.add("author")
            continue
        if key == "lang":
            out.append('lang: "en"')
            seen.add("lang")
            continue
        out.append(line)
        seen.add(key)

    if "lang" not in seen:
        out.append('lang: "en"')
    if "draft" not in seen:
        out.append("draft: false")
    if category and "category" not in seen:
        out.append(f'category: "{category}"')
    if "translationKey" not in seen:
        out.append(f'translationKey: "pair-{slug}-{en_slug}"')
    if "image" not in seen:
        out.append(f'image: "{hero_rel}"')

    return "\n".join(out)


def _assemble_md(fm_normalized: str, body: str) -> str:
    return f"---\n{fm_normalized}\n---\n{body}"


def _rollback(written: list[Path]) -> None:
    for p in written:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--draft", required=True)
    parser.add_argument("--category", help="Astro content category")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = _get_repo_root()
    draft = Path(args.draft).resolve()
    if not draft.is_dir():
        _fail(f"Draft folder not found: {draft}")

    # Step 1
    config = _load_config(root)
    site = Path(config.get("site", ""))
    if not site or not (site / "src" / "content" / "blog").is_dir():
        _fail(f"Site path `{site}` missing src/content/blog/. Check .deploy.json.")

    # Step 2
    canonical_md = _find_canonical_md(draft)
    slug = draft.name

    # Step 3
    hero_src = _find_hero(draft)

    # Step 4
    (site / "public" / "blog").mkdir(parents=True, exist_ok=True)
    hero_dest = site / "public" / "blog" / f"{slug}-hero.webp"
    _to_webp(hero_src, hero_dest)
    written: list[Path] = [hero_dest]
    hero_rel = f"/blog/{slug}-hero.webp"

    # Step 5 + detect EN
    content = canonical_md.read_text(encoding="utf-8")
    fm_raw, body = _parse_frontmatter_full(content)

    en_dir = root / "translations" / "en"
    en_files = list(en_dir.glob("*.md")) if en_dir.is_dir() else []
    en_md = en_files[0] if en_files else None
    en_slug = en_md.stem if en_md else None

    fm_pt = _normalize_pt_frontmatter(fm_raw, slug, en_slug, args.category, hero_rel)

    # Step 6
    pt_dest = site / "src" / "content" / "blog" / f"{slug}.md"
    pt_dest.write_text(_assemble_md(fm_pt, body), encoding="utf-8")
    written.append(pt_dest)

    # Steps 7-9: EN (skip if absent)
    if en_md:
        en_content = en_md.read_text(encoding="utf-8")
        fm_en_raw, en_body = _parse_frontmatter_full(en_content)
        fm_en = _normalize_en_frontmatter(fm_en_raw, slug, en_slug, args.category, hero_rel)
        en_dest = site / "src" / "content" / "blog-en" / f"{en_slug}.md"
        en_dest.parent.mkdir(parents=True, exist_ok=True)
        en_dest.write_text(_assemble_md(fm_en, en_body), encoding="utf-8")
        written.append(en_dest)

    # Step 10: pnpm run build
    build = subprocess.run(["pnpm", "run", "build"], cwd=str(site), capture_output=True, text=True)
    if build.returncode != 0:
        _rollback(written)
        _fail("pnpm build failed — rolled back written files.", {"stderr": build.stderr[-2000:]})

    # Step 11: deploy.sh
    if not args.dry_run:
        deploy_sh = site / "deploy.sh"
        if not deploy_sh.exists():
            _fail(f"deploy.sh not found at {deploy_sh}")
        deploy = subprocess.run(["bash", "deploy.sh"], cwd=str(site), capture_output=True, text=True)
        if deploy.returncode != 0:
            _fail("deploy.sh failed. Files remain in fabiomorus repo — revert manually if needed.",
                  {"stderr": deploy.stderr[-2000:]})

    # Step 12: success
    result: dict = {
        "status": "ok",
        "pt_url": f"https://fabiomorus.com/blog/{slug}",
        "hero": hero_rel,
    }
    if en_slug:
        result["en_url"] = f"https://fabiomorus.com/blog/{en_slug}"

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
