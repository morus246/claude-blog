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
            fm, slug=self.SLUG, en_slug=en_slug, category=category, hero_url=self.HERO
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

    def test_author_uses_param_value(self, deploy_module):
        """When an author param is passed, it overrides whatever the frontmatter says."""
        result = deploy_module._normalize_pt_frontmatter(
            "title: T\nauthor: Whoever\n", slug=self.SLUG, en_slug=None,
            category=None, hero_url=self.HERO, author="Jane Doe",
        )
        assert 'author: "Jane Doe"' in result
        assert "Whoever" not in result

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
            fm, slug="meu-post", en_slug="my-post", category=category, hero_url=self.HERO
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

    def test_author_uses_param_value(self, deploy_module):
        """EN frontmatter also honors the author param (from config)."""
        result = deploy_module._normalize_en_frontmatter(
            "title: T\nauthor: Whoever\n", slug="meu-post", en_slug="my-post",
            category=None, hero_url=self.HERO, author="Jane Doe",
        )
        assert 'author: "Jane Doe"' in result


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

    def test_fails_when_multiple_ambiguous_md(self, deploy_module, tmp_path):
        """Multiple .md with none matching the folder slug = ambiguous -> fail, don't guess."""
        draft = tmp_path / "the-post"
        draft.mkdir()
        (draft / "one.md").write_text("---\ntitle: One\n---\nBody\n", encoding="utf-8")
        (draft / "two.md").write_text("---\ntitle: Two\n---\nBody\n", encoding="utf-8")
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


# ---- _to_webp ----

class TestToWebp:
    def test_fallback_without_pil_warns_loudly(self, deploy_module, tmp_path, monkeypatch, capsys):
        """When PIL is unavailable, raw copy MUST happen AND a warning MUST hit stderr."""
        import sys as _sys
        # Force `from PIL import Image` to raise ImportError.
        monkeypatch.setitem(_sys.modules, "PIL", None)
        src = tmp_path / "hero.jpg"
        src.write_bytes(b"\xff\xd8\xff\xe0raw-jpeg-bytes")
        dest = tmp_path / "hero.webp"

        deploy_module._to_webp(src, dest)

        assert dest.exists(), "raw copy must still happen on fallback"
        captured = capsys.readouterr()
        msg = captured.err.lower()
        assert "pil" in msg or "webp" in msg, (
            f"fallback must warn to stderr; got: {captured.err!r}"
        )


# ---- _validate_slug ----

class TestValidateSlug:
    @pytest.mark.parametrize("slug", [
        "meu-post", "10-dicas", "a", "abc123", "psicologia-online", "ansiedade"
    ])
    def test_valid_slugs_accepted(self, deploy_module, slug):
        # Must not raise.
        deploy_module._validate_slug(slug)

    @pytest.mark.parametrize("slug", [
        "Meu-Post",          # uppercase
        "meu_post",          # underscore
        "meu post",          # space
        "meu-post-",         # trailing hyphen
        "-meu",              # leading hyphen
        "caf\u00e9",         # accent (café)
        "m\u00fasica",       # accent (música)
        "a.b",               # dot
        "",                  # empty
        "post!",             # punctuation
    ])
    def test_invalid_slugs_rejected(self, deploy_module, slug):
        with pytest.raises(SystemExit) as exc:
            deploy_module._validate_slug(slug)
        assert exc.value.code == 1


# ---- config helpers ----

class TestConfigAuthor:
    def test_uses_config_default_author(self, deploy_module):
        assert deploy_module._config_author({"default_author": "Jane Doe"}) == "Jane Doe"

    def test_defaults_to_fabio_morus(self, deploy_module):
        assert deploy_module._config_author({}) == "Fabio Morus"


class TestConfigSiteUrl:
    def test_uses_config_site_url(self, deploy_module):
        assert deploy_module._config_site_url({"site_url": "https://example.com"}) == "https://example.com"

    def test_strips_trailing_slash(self, deploy_module):
        assert deploy_module._config_site_url({"site_url": "https://example.com/"}) == "https://example.com"

    def test_defaults_to_fabiomorus(self, deploy_module):
        assert deploy_module._config_site_url({}) == "https://fabiomorus.com"


class TestResolveSite:
    def test_absolute_path_returned_as_is(self, deploy_module, tmp_path):
        abs_path = tmp_path / "site"
        abs_path.mkdir()
        assert deploy_module._resolve_site({"site": str(abs_path)}, tmp_path) == abs_path.resolve()

    def test_relative_path_resolved_against_repo_root(self, deploy_module, tmp_path):
        (tmp_path / "relative-site").mkdir()
        result = deploy_module._resolve_site({"site": "relative-site"}, tmp_path)
        assert result == (tmp_path / "relative-site").resolve()

    def test_env_override_takes_precedence(self, deploy_module, tmp_path, monkeypatch):
        env_site = tmp_path / "env-site"
        env_site.mkdir()
        monkeypatch.setenv("CLAUDE_BLOG_SITE", str(env_site))
        # config.site points elsewhere; env must win
        assert deploy_module._resolve_site({"site": "relative-site"}, tmp_path) == env_site.resolve()


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

    def test_build_call_has_timeout(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """subprocess.run for pnpm build must be invoked with a positive timeout kwarg."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: T\ncoverImage: https://x.jpg\n---\nBody\n", encoding="utf-8"
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        seen: list[dict] = []

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "build" in cmd:
                seen.append(kwargs)
            return _R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(
            deploy_module, "_load_config", lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        import io
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)

        rc = deploy_module.main()
        assert rc == 0
        assert seen, "build subprocess.run must be called"
        assert "timeout" in seen[0], "build must pass a timeout"
        assert seen[0]["timeout"] > 0

    def test_build_timeout_rolls_back_and_fails(
        self, deploy_module, tmp_path, fake_site, monkeypatch
    ):
        """If pnpm build hits TimeoutExpired, written files roll back and exit is 1."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: T\ncoverImage: https://x.jpg\n---\nBody\n", encoding="utf-8"
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "build" in cmd:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 1))
            return _R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(
            deploy_module, "_load_config", lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        with pytest.raises(SystemExit) as exc:
            deploy_module.main()
        assert exc.value.code == 1
        pt_dest = fake_site / "src" / "content" / "blog" / "meu-post.md"
        assert not pt_dest.exists(), "PT file must be rolled back on build timeout"

    def test_pt_url_uses_config_site_url(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """pt_url/hero in output JSON use config site_url, not hardcoded fabiomorus.com."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: T\ncoverImage: https://x.jpg\n---\nBody\n", encoding="utf-8"
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R())
        monkeypatch.setattr(
            deploy_module, "_load_config",
            lambda root: {"site": str(fake_site), "site_url": "https://example.com"},
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        import io
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)

        rc = deploy_module.main()
        assert rc == 0
        data = json.loads(out.getvalue())
        assert "example.com/blog/meu-post" in data["pt_url"], data
        assert "fabiomorus.com" not in data["pt_url"], data
        assert "example.com/blog/meu-post-hero.webp" in data["hero"], data

    def test_author_flows_from_config_to_pt_file(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """config default_author is written into the deployed PT frontmatter."""
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: T\nauthor: Whoever\ncoverImage: https://x.jpg\n---\nBody\n", encoding="utf-8"
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R())
        monkeypatch.setattr(
            deploy_module, "_load_config",
            lambda root: {"site": str(fake_site), "default_author": "Jane Doe"},
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)

        sys.argv = ["deploy_post.py", "--draft", str(draft), "--dry-run"]
        import io
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)

        rc = deploy_module.main()
        assert rc == 0
        pt_content = (fake_site / "src" / "content" / "blog" / "meu-post.md").read_text(encoding="utf-8")
        assert 'author: "Jane Doe"' in pt_content
        assert "Whoever" not in pt_content

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

        # Two EN files - one matches the PT slug (meu-post), one doesn't
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


# ---- _health_check ----

class TestHealthCheck:
    def _fake_resp(self, status):
        class _R:
            def __init__(s): s.status = status
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return _R()

    def test_returns_status_on_success(self, deploy_module, monkeypatch):
        called = []
        def fake_urlopen(req, timeout=None):
            called.append(req.full_url)
            return self._fake_resp(200)
        monkeypatch.setattr(deploy_module.urllib.request, "urlopen", fake_urlopen)
        status = deploy_module._health_check("https://example.com/x")
        assert status == 200
        assert len(called) == 1, "success must short-circuit (no retries)"

    def test_retries_then_returns_last_status(self, deploy_module, monkeypatch):
        calls = {"n": 0}
        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            raise deploy_module.urllib.error.HTTPError(req.full_url, 500, "err", {}, None)
        monkeypatch.setattr(deploy_module.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(deploy_module.time, "sleep", lambda s: None)
        status = deploy_module._health_check("https://example.com/x", attempts=3, delay=0)
        assert status == 500
        assert calls["n"] == 3, "must retry attempts times"

    def test_returns_zero_on_connection_error(self, deploy_module, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise deploy_module.urllib.error.URLError("no route")
        monkeypatch.setattr(deploy_module.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(deploy_module.time, "sleep", lambda s: None)
        status = deploy_module._health_check("https://example.com/x", attempts=2, delay=0)
        assert status == 0


# ---- health check integration with main() (non-dry-run) ----

class TestHealthCheckDeploy:
    def _setup_draft(self, tmp_path):
        draft = tmp_path / "content" / "meu-post"
        draft.mkdir(parents=True)
        (draft / "meu-post.md").write_text(
            "---\ntitle: T\ncoverImage: https://x.jpg\n---\nBody\n", encoding="utf-8"
        )
        (draft / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)
        return draft

    def test_success_when_health_check_ok(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """Non-dry-run deploy with healthy live site returns status=ok."""
        draft = self._setup_draft(tmp_path)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R())
        monkeypatch.setattr(
            deploy_module, "_load_config", lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)
        monkeypatch.setattr(deploy_module, "_health_check", lambda url, **kw: 200)

        sys.argv = ["deploy_post.py", "--draft", str(draft)]  # no --dry-run
        import io
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)

        rc = deploy_module.main()
        assert rc == 0
        data = json.loads(out.getvalue())
        assert data["status"] == "ok"

    def test_fails_when_health_check_broken(self, deploy_module, tmp_path, fake_site, monkeypatch):
        """Non-dry-run deploy where live site returns 500 must exit 1 (deploy happened but site broken)."""
        draft = self._setup_draft(tmp_path)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R())
        monkeypatch.setattr(
            deploy_module, "_load_config", lambda root: {"site": str(fake_site)}
        )
        monkeypatch.setattr(deploy_module, "_get_repo_root", lambda: tmp_path)
        monkeypatch.setattr(deploy_module, "_health_check", lambda url, **kw: 500)

        sys.argv = ["deploy_post.py", "--draft", str(draft)]  # no --dry-run
        with pytest.raises(SystemExit) as exc:
            deploy_module.main()
        assert exc.value.code == 1
