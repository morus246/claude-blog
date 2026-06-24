"""Tests for scripts/deploy_post.py."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_PATH = ROOT / "scripts" / "deploy_post.py"


@pytest.fixture(scope="module")
def deploy_module():
    spec = importlib.util.spec_from_file_location("deploy_post", DEPLOY_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deploy_post"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_site(tmp_path: Path) -> Path:
    site = tmp_path / "fabiomorus"
    (site / "src" / "content" / "blog").mkdir(parents=True)
    (site / "src" / "content" / "blog-en").mkdir(parents=True)
    (site / "public" / "blog").mkdir(parents=True)
    (site / "deploy.sh").write_text("#!/bin/bash\nexit 0\n")
    return site


@pytest.fixture
def fake_draft(tmp_path: Path) -> Path:
    draft = tmp_path / "content" / "meu-post"
    draft.mkdir(parents=True)
    (draft / "meu-post.md").write_text(
        "---\n"
        "title: Meu Post\n"
        "description: Descrição do post.\n"
        "coverImage: https://cdn.pixabay.com/photo/example.jpg\n"
        "coverImageAlt: Imagem do post\n"
        "ogImage: https://cdn.pixabay.com/photo/example.jpg\n"
        "canonical: https://fabiomorus.com/blog/meu-post\n"
        "date: 2026-06-01\n"
        "lastUpdated: 2026-06-15\n"
        "author: Fábio Morus\n"
        "tags:\n"
        "---\n\n# Meu Post\n\nConteúdo aqui.\n",
        encoding="utf-8",
    )
    (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)
    return draft


# ---- _parse_frontmatter_full ----

class TestParseFrontmatterFull:
    def test_splits_fm_and_body(self, deploy_module):
        text = "---\ntitle: Test\n---\n\nBody here.\n"
        fm, body = deploy_module._parse_frontmatter_full(text)
        assert "title: Test" in fm
        assert "Body here." in body

    def test_no_frontmatter_returns_empty_fm(self, deploy_module):
        text = "# Just a heading\n\nBody.\n"
        fm, body = deploy_module._parse_frontmatter_full(text)
        assert fm == ""
        assert "Just a heading" in body


# ---- _normalize_pt_frontmatter ----

class TestNormalizePTFrontmatter:
    HERO = "/blog/meu-post-hero.webp"
    SLUG = "meu-post"

    def _run(self, deploy_module, fm, en_slug=None, category=None):
        return deploy_module._normalize_pt_frontmatter(
            fm, slug=self.SLUG, en_slug=en_slug, category=category, hero_rel=self.HERO
        )

    def test_coverImage_renamed_and_overridden(self, deploy_module):
        result = self._run(deploy_module, "title: T\ncoverImage: https://old.jpg\n")
        assert f'image: "{self.HERO}"' in result
        assert "coverImage:" not in result

    def test_coverImageAlt_renamed_to_imageAlt(self, deploy_module):
        result = self._run(deploy_module, "title: T\ncoverImageAlt: Alt text here\n")
        assert "imageAlt: Alt text here" in result
        assert "coverImageAlt:" not in result

    def test_ogImage_removed(self, deploy_module):
        result = self._run(deploy_module, "title: T\nogImage: https://og.jpg\n")
        assert "ogImage:" not in result

    def test_canonical_removed(self, deploy_module):
        result = self._run(deploy_module, "title: T\ncanonical: https://example.com\n")
        assert "canonical:" not in result

    def test_lastUpdated_renamed_to_lastmod(self, deploy_module):
        result = self._run(deploy_module, "title: T\nlastUpdated: 2026-06-15\n")
        assert "lastmod: 2026-06-15" in result
        assert "lastUpdated:" not in result

    def test_author_accent_stripped(self, deploy_module):
        result = self._run(deploy_module, "title: T\nauthor: Fábio Morus\n")
        assert 'author: "Fabio Morus"' in result

    def test_lang_ptbr_injected(self, deploy_module):
        result = self._run(deploy_module, "title: T\n")
        assert 'lang: "pt-BR"' in result

    def test_draft_false_injected(self, deploy_module):
        result = self._run(deploy_module, "title: T\n")
        assert "draft: false" in result

    def test_category_injected_when_provided(self, deploy_module):
        result = self._run(deploy_module, "title: T\n", category="ansiedade")
        assert 'category: "ansiedade"' in result

    def test_no_category_when_not_provided(self, deploy_module):
        result = self._run(deploy_module, "title: T\n")
        assert "category:" not in result

    def test_translationKey_generated_with_en_slug(self, deploy_module):
        result = self._run(deploy_module, "title: T\n", en_slug="my-post")
        assert 'translationKey: "pair-meu-post-my-post"' in result

    def test_no_translationKey_without_en_slug(self, deploy_module):
        result = self._run(deploy_module, "title: T\n")
        assert "translationKey:" not in result

    def test_no_duplicate_image_when_both_coverImage_and_image_present(self, deploy_module):
        """When both coverImage and image are in frontmatter, only one image: line is emitted."""
        fm = "title: T\ncoverImage: https://old.jpg\nimage: https://older.jpg\n"
        result = self._run(deploy_module, fm)
        image_lines = [l for l in result.splitlines() if l.startswith("image:")]
        assert len(image_lines) == 1, f"Expected 1 image: line, got {len(image_lines)}: {image_lines}"
        assert self.HERO in image_lines[0]


# ---- _normalize_en_frontmatter ----

class TestNormalizeENFrontmatter:
    HERO = "/blog/meu-post-hero.webp"

    def _run(self, deploy_module, fm, category=None):
        return deploy_module._normalize_en_frontmatter(
            fm, slug="meu-post", en_slug="my-post", category=category, hero_rel=self.HERO
        )

    def test_lang_set_to_en(self, deploy_module):
        result = self._run(deploy_module, "title: T\nlang: pt-BR\n")
        assert 'lang: "en"' in result
        assert "pt-BR" not in result

    def test_translatedFrom_removed(self, deploy_module):
        result = self._run(deploy_module, "title: T\ntranslatedFrom: pt-BR\n")
        assert "translatedFrom:" not in result

    def test_translatedDate_removed(self, deploy_module):
        result = self._run(deploy_module, "title: T\ntranslatedDate: 2026-06-20\n")
        assert "translatedDate:" not in result

    def test_locale_removed(self, deploy_module):
        result = self._run(deploy_module, "title: T\nlocale: pt-BR\n")
        assert "locale:" not in result

    def test_slug_field_removed(self, deploy_module):
        result = self._run(deploy_module, "title: T\nslug: meu-post\n")
        assert "slug:" not in result

    def test_translationKey_matches_pt(self, deploy_module):
        result = self._run(deploy_module, "title: T\n")
        assert 'translationKey: "pair-meu-post-my-post"' in result

    def test_lang_en_injected_when_absent(self, deploy_module):
        result = self._run(deploy_module, "title: T\n")
        assert 'lang: "en"' in result


# ---- _find_canonical_md ----

class TestFindCanonicalMd:
    def test_prefers_file_matching_folder_name(self, deploy_module, tmp_path):
        draft = tmp_path / "my-slug"
        draft.mkdir()
        (draft / "my-slug.md").write_text("---\ntitle: T\n---\nBody\n", encoding="utf-8")
        (draft / "review.md").write_text("review content", encoding="utf-8")
        result = deploy_module._find_canonical_md(draft)
        assert result.name == "my-slug.md"

    def test_ignores_review_md(self, deploy_module, tmp_path):
        draft = tmp_path / "the-post"
        draft.mkdir()
        (draft / "review.md").write_text("review", encoding="utf-8")
        (draft / "the-post.md").write_text("---\ntitle: T\n---\nBody\n", encoding="utf-8")
        result = deploy_module._find_canonical_md(draft)
        assert result.name == "the-post.md"

    def test_exits_1_when_no_md(self, deploy_module, tmp_path):
        draft = tmp_path / "empty-post"
        draft.mkdir()
        with pytest.raises(SystemExit) as exc:
            deploy_module._find_canonical_md(draft)
        assert exc.value.code == 1


# ---- _find_hero ----

class TestFindHero:
    def test_finds_hero_jpg(self, deploy_module, tmp_path):
        draft = tmp_path / "post"
        draft.mkdir()
        (draft / "hero.jpg").write_bytes(b"data")
        result = deploy_module._find_hero(draft)
        assert result.name == "hero.jpg"

    def test_finds_hero_webp(self, deploy_module, tmp_path):
        draft = tmp_path / "post"
        draft.mkdir()
        (draft / "hero.webp").write_bytes(b"data")
        result = deploy_module._find_hero(draft)
        assert result.name == "hero.webp"

    def test_finds_hero_png(self, deploy_module, tmp_path):
        draft = tmp_path / "post"
        draft.mkdir()
        (draft / "hero.png").write_bytes(b"data")
        result = deploy_module._find_hero(draft)
        assert result.name == "hero.png"

    def test_exits_1_with_clear_message_when_missing(self, deploy_module, tmp_path, capsys):
        draft = tmp_path / "post"
        draft.mkdir()
        with pytest.raises(SystemExit) as exc:
            deploy_module._find_hero(draft)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "hero" in captured.err.lower()
        assert "Phase 6.5" in captured.err


# ---- _load_config ----

class TestLoadConfig:
    def test_exits_1_with_clear_message_when_missing(self, deploy_module, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            deploy_module._load_config(tmp_path)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert ".deploy.json" in captured.err

    def test_returns_dict_when_valid(self, deploy_module, tmp_path):
        (tmp_path / ".deploy.json").write_text(
            json.dumps({"site": "/some/path"}), encoding="utf-8"
        )
        result = deploy_module._load_config(tmp_path)
        assert result["site"] == "/some/path"


# ---- dry-run integration test ----

class TestDryRun:
    def test_dry_run_skips_deploy_sh(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """--dry-run must call pnpm build but NOT call deploy.sh."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: Meu Post\ncoverImage: https://x.jpg\n---\nBody.\n",
            encoding="utf-8",
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        deploy_calls: list[list[str]] = []
        build_calls: list[list[str]] = []

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "build" in cmd:
                build_calls.append(cmd)
            elif isinstance(cmd, list) and "deploy.sh" in " ".join(cmd):
                deploy_calls.append(cmd)
            return _R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(
            deploy_module, "_load_config",
            lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        import io
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        rc = deploy_module.main()
        assert rc == 0
        assert len(build_calls) == 1, "pnpm build should be called once"
        assert len(deploy_calls) == 0, "deploy.sh must NOT be called with --dry-run"

    def test_success_json_has_pt_url(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """main() stdout on success is valid JSON with status=ok and pt_url."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: Meu Post\ncoverImage: https://x.jpg\n---\nBody.\n",
            encoding="utf-8",
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R())
        monkeypatch.setattr(
            deploy_module, "_load_config",
            lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        import io
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)

        rc = deploy_module.main()
        assert rc == 0
        data = json.loads(out.getvalue())
        assert data["status"] == "ok"
        assert "fabiomorus.com/blog/meu-post" in data["pt_url"]

    def test_build_failure_rolls_back_and_exits_1(
        self, deploy_module, tmp_path, fake_site, monkeypatch, capsys
    ):
        """When pnpm build fails, written files are removed and exit code is 1."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: T\ncoverImage: https://x.jpg\n---\nBody\n",
            encoding="utf-8",
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        class _FailR:
            returncode = 1
            stdout = ""
            stderr = "Build error: type error in component"

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _FailR())
        monkeypatch.setattr(
            deploy_module, "_load_config",
            lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        with pytest.raises(SystemExit) as exc:
            deploy_module.main()
        assert exc.value.code == 1

        # Verify rollback: PT file must not exist in site
        pt_dest = fake_site / "src" / "content" / "blog" / "meu-post.md"
        assert not pt_dest.exists(), "PT file must be rolled back on build failure"

    def test_en_translation_deployed_when_present(
        self, deploy_module, tmp_path, fake_site, monkeypatch
    ):
        """When translations/en/<slug>.md exists, EN is written to blog-en/."""
        # Set up draft with translations/en
        content_root = tmp_path / "content"
        draft = content_root / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: Meu Post\ncoverImage: https://x.jpg\n---\nBody.\n",
            encoding="utf-8",
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        # EN translation at translations/en/my-post.md
        en_dir = content_root.parent / "translations" / "en"
        en_dir.mkdir(parents=True)
        (en_dir / "my-post.md").write_text(
            "---\ntitle: My Post\nlang: pt-BR\ntranslatedFrom: pt-BR\ntranslatedDate: 2026-06-20\n"
            "locale: pt-BR\nslug: meu-post\ncoverImage: https://x.jpg\n---\nBody EN.\n",
            encoding="utf-8",
        )

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R())
        monkeypatch.setattr(
            deploy_module, "_load_config",
            lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        import io
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)

        rc = deploy_module.main()
        assert rc == 0

        # EN file must exist in blog-en/
        en_dest = fake_site / "src" / "content" / "blog-en" / "my-post.md"
        assert en_dest.exists(), "EN file must be written to blog-en/"

        # EN frontmatter must have lang: en and no translatedFrom
        en_content = en_dest.read_text(encoding="utf-8")
        assert 'lang: "en"' in en_content
        assert "translatedFrom:" not in en_content
        assert "translatedDate:" not in en_content
        assert "locale:" not in en_content
        assert "slug:" not in en_content

        # translationKey must link both slugs
        assert 'translationKey: "pair-meu-post-my-post"' in en_content

        # pt_url and en_url must both appear in output JSON
        data = json.loads(out.getvalue())
        assert "en_url" in data
        assert "my-post" in data["en_url"]


class TestENDetection:
    def test_en_translation_by_slug_match_preferred(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """When translations/en/ has multiple files, the one matching the PT slug is used."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: T\ncoverImage: https://x.jpg\n---\nBody.\n", encoding="utf-8"
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        # Two EN files — one matches the PT slug (meu-post), one doesn't
        en_dir = tmp_path / "translations" / "en"
        en_dir.mkdir(parents=True)
        (en_dir / "meu-post.md").write_text(
            "---\ntitle: My Post\ncoverImage: https://x.jpg\n---\nEN body.\n", encoding="utf-8"
        )
        (en_dir / "other-post.md").write_text(
            "---\ntitle: Other Post\ncoverImage: https://x.jpg\n---\nOther EN body.\n", encoding="utf-8"
        )

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R())
        monkeypatch.setattr(deploy_module, "_load_config", lambda root: {"site": str(fake_site)})
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        import io
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        rc = deploy_module.main()
        assert rc == 0

        # The slug-matched file (meu-post) must be deployed, not the other one
        en_dest = fake_site / "src" / "content" / "blog-en" / "meu-post.md"
        wrong_dest = fake_site / "src" / "content" / "blog-en" / "other-post.md"
        assert en_dest.exists(), "Slug-matched EN file must be deployed"
        assert not wrong_dest.exists(), "Non-matching EN file must NOT be deployed"

        data = json.loads(out.getvalue())
        assert "meu-post" in data.get("en_url", "")
