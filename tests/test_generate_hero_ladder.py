"""Regression tests for scripts/generate_hero.py ladder.

Verifies the documented 4-step fallback order:
  1. MiniMax mmx CLI
  2. Unsplash API
  3. Openverse API (no key)
  4. Fail

These tests are offline: they only inspect the module docstring and the
public function names; no network calls are issued.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HERO_SCRIPT = REPO_ROOT / "scripts" / "generate_hero.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_hero", HERO_SCRIPT)
    assert spec and spec.loader, f"could not load spec for {HERO_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ladder_order_in_docstring():
    mod = _load_module()
    doc = mod.__doc__ or ""
    assert "mmx" in doc.lower(), "tier 1 (mmx) missing from ladder docstring"
    assert "unsplash" in doc.lower(), "tier 2 (unsplash) missing from ladder docstring"
    assert "openverse" in doc.lower(), "tier 3 (openverse) missing from ladder docstring"
    # Order check
    assert doc.lower().index("mmx") < doc.lower().index("unsplash") < doc.lower().index("openverse"), (
        "ladder order changed: expected mmx -> unsplash -> openverse"
    )


def test_openverse_endpoint_constant_defined():
    mod = _load_module()
    assert hasattr(mod, "OPENVERSE_API"), "OPENVERSE_API constant removed"
    assert mod.OPENVERSE_API.startswith("https://"), "OPENVERSE_API must be HTTPS"
    assert "openverse" in mod.OPENVERSE_API, "OPENVERSE_API must point to Openverse"


def test_default_dimensions_match_og_card():
    mod = _load_module()
    assert mod.DEFAULT_WIDTH == 1200
    assert mod.DEFAULT_HEIGHT == 630
