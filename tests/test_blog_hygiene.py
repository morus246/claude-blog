"""tests/test_blog_hygiene.py: Unit tests for scripts/blog_hygiene.py.

Covers: slugify, lazy-loading injection, alt-text warnings, TOC insertion.
Stdlib + pytest only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import blog_hygiene  # noqa: E402


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic_ascii(self) -> None:
        assert blog_hygiene._slugify("Hello World") == "hello-world"

    def test_accent_stripping_ptbr(self) -> None:
        assert blog_hygiene._slugify("Pânico") == "panico"

    def test_cedilla_stripped(self) -> None:
        assert blog_hygiene._slugify("Reconheça") == "reconheca"

    def test_question_mark_removed(self) -> None:
        assert blog_hygiene._slugify("Como Parar?") == "como-parar"

    def test_colon_removed(self) -> None:
        assert blog_hygiene._slugify("Passo 1: Reconheça") == "passo-1-reconheca"

    def test_multiple_spaces_collapsed(self) -> None:
        assert blog_hygiene._slugify("A  B") == "a-b"

    def test_already_ascii(self) -> None:
        assert blog_hygiene._slugify("Section One") == "section-one"


# ---------------------------------------------------------------------------
# fix_html_lazy_loading
# ---------------------------------------------------------------------------

class TestLazyLoading:
    def test_adds_lazy_to_img_without_loading(self) -> None:
        html = '<img src="foo.jpg" alt="test">'
        result, count = blog_hygiene.fix_html_lazy_loading(html)
        assert 'loading="lazy"' in result
        assert count == 1

    def test_no_op_if_loading_lazy_already_present(self) -> None:
        html = '<img src="foo.jpg" loading="lazy" alt="test">'
        result, count = blog_hygiene.fix_html_lazy_loading(html)
        assert result == html
        assert count == 0

    def test_no_op_if_loading_eager_present(self) -> None:
        # LCP image; intentionally eager, must not be overwritten
        html = '<img src="hero.jpg" loading="eager">'
        result, count = blog_hygiene.fix_html_lazy_loading(html)
        assert count == 0
        assert 'loading="eager"' in result

    def test_fixes_multiple_imgs(self) -> None:
        html = '<img src="a.jpg"><img src="b.jpg" loading="eager"><img src="c.jpg">'
        result, count = blog_hygiene.fix_html_lazy_loading(html)
        assert count == 2
        assert result.count('loading="lazy"') == 2

    def test_result_contains_original_attrs(self) -> None:
        html = '<img src="x.png" alt="desc" class="hero">'
        result, _ = blog_hygiene.fix_html_lazy_loading(html)
        assert 'alt="desc"' in result
        assert 'class="hero"' in result


# ---------------------------------------------------------------------------
# warn_missing_alt
# ---------------------------------------------------------------------------

class TestAltWarnings:
    def test_warns_missing_alt(self) -> None:
        html = '<img src="foo.jpg">'
        missing = blog_hygiene.warn_missing_alt(html)
        assert "foo.jpg" in missing

    def test_no_warning_if_alt_present(self) -> None:
        html = '<img src="foo.jpg" alt="A description">'
        missing = blog_hygiene.warn_missing_alt(html)
        assert missing == []

    def test_empty_alt_is_acceptable(self) -> None:
        html = '<img src="foo.jpg" alt="">'
        missing = blog_hygiene.warn_missing_alt(html)
        assert missing == []

    def test_multiple_imgs_only_missing_flagged(self) -> None:
        html = '<img src="a.jpg"><img src="b.jpg" alt="ok"><img src="c.jpg">'
        missing = blog_hygiene.warn_missing_alt(html)
        assert "a.jpg" in missing
        assert "c.jpg" in missing
        assert "b.jpg" not in missing


# ---------------------------------------------------------------------------
# insert_toc
# ---------------------------------------------------------------------------

def _make_post(word_count: int, has_toc: bool = False, lang: str = "pt") -> str:
    """Build a minimal mock post with the given word count."""
    body_words = "palavra " * word_count
    toc_block = "**Neste artigo:**\n- [Section One](#section-one)\n\n" if has_toc else ""
    lang_field = f'\nlang: "{lang}"' if lang != "pt" else ""
    return (
        f"---\ntitle: Test Post{lang_field}\ndate: 2026-01-01\n---\n\n"
        f"Intro paragraph.\n\n"
        f"{toc_block}"
        f"## Section One\n\n{body_words}\n\n## Section Two\n\nMore content.\n"
    )


class TestTOCInsertion:
    def test_toc_inserted_for_long_post(self) -> None:
        md = _make_post(2100)
        result, inserted = blog_hygiene.insert_toc(md)
        assert inserted is True
        assert "**Neste artigo:**" in result

    def test_toc_skipped_for_short_post(self) -> None:
        md = _make_post(1500)
        result, inserted = blog_hygiene.insert_toc(md)
        assert inserted is False
        assert "**Neste artigo:**" not in result

    def test_toc_not_duplicated_if_already_present(self) -> None:
        md = _make_post(2100, has_toc=True)
        result, inserted = blog_hygiene.insert_toc(md)
        assert inserted is False
        assert result.count("**Neste artigo:**") == 1

    def test_toc_contains_correct_h2_links(self) -> None:
        md = _make_post(2100)
        result, inserted = blog_hygiene.insert_toc(md)
        assert inserted is True
        assert "[Section One](#section-one)" in result
        assert "[Section Two](#section-two)" in result

    def test_en_label_for_english_post(self) -> None:
        md = _make_post(2100, lang="en")
        result, inserted = blog_hygiene.insert_toc(md)
        assert inserted is True
        assert "**In this article:**" in result
        assert "**Neste artigo:**" not in result

    def test_toc_inserted_before_first_h2(self) -> None:
        md = _make_post(2100)
        result, inserted = blog_hygiene.insert_toc(md)
        assert inserted is True
        toc_pos = result.index("**Neste artigo:**")
        h2_pos = result.index("## Section One")
        assert toc_pos < h2_pos

    def test_ptbr_heading_slugified_correctly(self) -> None:
        body = "palavra " * 2200
        md = (
            "---\ntitle: Test\n---\n\nIntro.\n\n"
            f"## Como Parar um Ataque de Pânico?\n\n{body}"
        )
        result, inserted = blog_hygiene.insert_toc(md)
        assert inserted is True
        assert "[Como Parar um Ataque de Pânico?](#como-parar-um-ataque-de-panico)" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
