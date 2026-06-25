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
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


_REMOVE_PT = frozenset({"ogImage", "canonical"})
_REMOVE_EN = frozenset({"ogImage", "canonical", "locale", "translatedFrom", "translatedDate", "slug"})

# Hard ceilings so a hung build or deploy cannot block forever (closes P1-4).
_BUILD_TIMEOUT_S = 600   # 10 min for pnpm run build
_DEPLOY_TIMEOUT_S = 1800  # 30 min for deploy.sh (rsync + remote install)

# URL-safe slug: lowercase alphanumerics with single hyphens between words
# (closes P1-12). Rejects accents, spaces, underscores, leading/trailing hyphens.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Config-driven defaults (closes P0-2, P0-3). Override via .deploy.json.
_DEFAULT_AUTHOR = "Fabio Morus"
_DEFAULT_SITE_URL = "https://fabiomorus.com"
_SITE_ENV = "CLAUDE_BLOG_SITE"

# Live-site verification after deploy (closes P1-7: 'deploy ok, site broken').
_HEALTH_ATTEMPTS = 3
_HEALTH_DELAY_S = 5.0
_HEALTH_TIMEOUT_S = 10.0


def _get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        _fail(
            f"Invalid slug '{slug}'. Use lowercase letters, digits, and single "
            "hyphens between words (e.g. 'meu-post'). No accents, spaces, "
            "underscores, or leading/trailing hyphens."
        )


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


def _config_author(config: dict) -> str:
    """Author written into deployed frontmatter (closes P0-2)."""
    return config.get("default_author", _DEFAULT_AUTHOR)


def _config_site_url(config: dict) -> str:
    """Canonical base URL for absolute links (closes P0-3). Trailing slash stripped."""
    url = (config.get("site_url") or _DEFAULT_SITE_URL).rstrip("/")
    return url or _DEFAULT_SITE_URL


def _resolve_site(config: dict, repo_root: Path) -> Path:
    """Resolve target site path: env override > absolute > relative-to-repo-root (closes P1-9)."""
    env = os.environ.get(_SITE_ENV)
    if env:
        return Path(env).expanduser().resolve()
    raw = config.get("site", "")
    if not raw:
        _fail(".deploy.json missing 'site'. Set it to the fabiomorus repo path (absolute or relative).")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = repo_root / p
    return p.resolve()


def _health_check(
    url: str, *, attempts: int = _HEALTH_ATTEMPTS,
    delay: float = _HEALTH_DELAY_S, timeout: float = _HEALTH_TIMEOUT_S,
) -> int:
    """GET url up to `attempts` times with `delay` backoff.

    Returns the last HTTP status (e.g. 200), or 0 if every attempt failed to
    connect (URLError/OSError). 2xx/3xx short-circuits on first success.
    """
    last = 0
    for i in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                url, method="GET", headers={"User-Agent": "deploy_post/healthcheck"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                last = resp.status
                if 200 <= last < 400:
                    return last
        except urllib.error.HTTPError as e:
            last = e.code
        except (urllib.error.URLError, OSError):
            last = 0
        if i < attempts:
            time.sleep(delay)
    return last


def _find_canonical_md(draft: Path) -> Path:
    candidates = [f for f in draft.glob("*.md") if f.name != "review.md"]
    if not candidates:
        _fail(f"No canonical .md found in {draft}.")
    slug = draft.name
    preferred = [f for f in candidates if f.stem == slug]
    if preferred:
        return preferred[0]
    if len(candidates) == 1:
        return candidates[0]
    names = ", ".join(sorted(c.name for c in candidates))
    _fail(
        f"Ambiguous canonical .md in {draft}: found [{names}] and none matches "
        f"slug '{slug}'. Name the file '{slug}.md' or keep a single .md."
    )


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
        print(
            "[deploy] WARNING: Pillow (PIL) not installed - cannot convert to "
            f"webp. Copying {src.name} as-is to {dest.name} (a .webp file may "
            "hold non-webp bytes). Install Pillow (pip install Pillow).",
            file=sys.stderr,
        )
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
    category: Optional[str], hero_url: str, author: str = _DEFAULT_AUTHOR,
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
            if "image" not in seen:
                out.append(f'image: "{hero_url}"')
                seen.add("image")
            continue
        if key == "image":
            if "image" not in seen:
                out.append(f'image: "{hero_url}"')
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
            out.append(f'author: "{author}"')
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
        out.append(f'image: "{hero_url}"')

    return "\n".join(out)


def _normalize_en_frontmatter(
    fm_text: str, slug: str, en_slug: str,
    category: Optional[str], hero_url: str, author: str = _DEFAULT_AUTHOR,
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
            if "image" not in seen:
                out.append(f'image: "{hero_url}"')
                seen.add("image")
            continue
        if key == "image":
            if "image" not in seen:
                out.append(f'image: "{hero_url}"')
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
            out.append(f'author: "{author}"')
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
        out.append(f'image: "{hero_url}"')

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
    site = _resolve_site(config, root)
    if not (site / "src" / "content" / "blog").is_dir():
        _fail(f"Site path `{site}` missing src/content/blog/. Check .deploy.json.")
    author = _config_author(config)
    site_url = _config_site_url(config)

    # Step 2
    slug = draft.name
    _validate_slug(slug)
    canonical_md = _find_canonical_md(draft)

    # Step 3
    hero_src = _find_hero(draft)

    # Step 4
    (site / "public" / "blog").mkdir(parents=True, exist_ok=True)
    hero_dest = site / "public" / "blog" / f"{slug}-hero.webp"
    _to_webp(hero_src, hero_dest)
    written: list[Path] = [hero_dest]
    hero_url = f"{site_url}/blog/{slug}-hero.webp"

    # Step 5 + detect EN
    content = canonical_md.read_text(encoding="utf-8")
    fm_raw, body = _parse_frontmatter_full(content)

    en_dir = root / "translations" / "en"
    en_md: Optional[Path] = None
    if en_dir.is_dir():
        en_files = list(en_dir.glob("*.md"))
        slug_match = [f for f in en_files if f.stem == slug]
        if slug_match:
            en_md = slug_match[0]
        elif len(en_files) == 1:
            en_md = en_files[0]
        elif len(en_files) > 1:
            print(
                f"[deploy] WARNING: {len(en_files)} files in translations/en/ and none matches slug '{slug}' - skipping EN deploy.",
                file=sys.stderr,
            )
    en_slug = en_md.stem if en_md else None

    fm_pt = _normalize_pt_frontmatter(fm_raw, slug, en_slug, args.category, hero_url, author)

    # Step 6
    pt_dest = site / "src" / "content" / "blog" / f"{slug}.md"
    pt_dest.write_text(_assemble_md(fm_pt, body), encoding="utf-8")
    written.append(pt_dest)

    # Steps 7-9: EN (skip if absent)
    if en_md:
        en_content = en_md.read_text(encoding="utf-8")
        fm_en_raw, en_body = _parse_frontmatter_full(en_content)
        fm_en = _normalize_en_frontmatter(fm_en_raw, slug, en_slug, args.category, hero_url, author)
        en_dest = site / "src" / "content" / "blog-en" / f"{en_slug}.md"
        en_dest.parent.mkdir(parents=True, exist_ok=True)
        en_dest.write_text(_assemble_md(fm_en, en_body), encoding="utf-8")
        written.append(en_dest)

    # Step 10: pnpm run build
    try:
        build = subprocess.run(
            ["pnpm", "run", "build"], cwd=str(site), capture_output=True, text=True,
            timeout=_BUILD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        _rollback(written)
        _fail(f"pnpm build timed out after {_BUILD_TIMEOUT_S}s - rolled back written files.")
    if build.returncode != 0:
        _rollback(written)
        _fail("pnpm build failed - rolled back written files.", {"stderr": build.stderr[-2000:]})

    # Step 11: deploy.sh
    if not args.dry_run:
        deploy_sh = site / "deploy.sh"
        if not deploy_sh.exists():
            _fail(f"deploy.sh not found at {deploy_sh}")
        try:
            deploy = subprocess.run(
                ["bash", "deploy.sh"],
                cwd=str(site),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=_DEPLOY_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            _fail(
                f"deploy.sh timed out after {_DEPLOY_TIMEOUT_S}s. "
                "Files remain in fabiomorus repo - revert manually if needed."
            )
        if deploy.returncode != 0:
            _fail("deploy.sh failed. Files remain in fabiomorus repo - revert manually if needed.",
                  {"stderr": deploy.stderr[-2000:]})

    # Step 11b: health check the live PT URL (skip in dry-run; nothing deployed yet).
    pt_url = f"{site_url}/blog/{slug}"
    if not args.dry_run:
        status = _health_check(pt_url)
        if not (200 <= status < 400):
            _fail(
                f"Deploy completed but health check failed for {pt_url} "
                f"(HTTP {status or 'unreachable'} after {_HEALTH_ATTEMPTS} attempts). "
                "The site may be broken - investigate."
            )

    # Step 12: success
    result: dict = {
        "status": "ok",
        "pt_url": pt_url,
        "hero": hero_url,
    }
    if en_slug:
        result["en_url"] = f"{site_url}/blog/{en_slug}"

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
