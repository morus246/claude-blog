"""Regression tests for scripts/generate_hero.py ladder.

Verifies the documented 4-step fallback order:
  1. MiniMax mmx CLI
  2. Unsplash API
  3. Openverse API (no key)
  4. Fail

Also covers the Unsplash key resolution fallback chain (env var -> .deploy.json).
These tests are offline: they only inspect the module docstring, the
public function names, and local file fallbacks; no network calls are issued.
"""
from __future__ import annotations

import importlib.util
import json
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


def test_unsplash_key_env_var_takes_precedence(monkeypatch, tmp_path):
    """Env var wins over .deploy.json fallback."""
    mod = _load_module()
    deploy = tmp_path / ".deploy.json"
    deploy.write_text(json.dumps({"unsplash_access_key": "fromfile"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "fromenv")
    assert mod._resolve_unsplash_key() == "fromenv"


def test_unsplash_key_falls_back_to_deploy_json(monkeypatch, tmp_path):
    """When env var is unset, .deploy.json in CWD supplies the key."""
    mod = _load_module()
    deploy = tmp_path / ".deploy.json"
    deploy.write_text(json.dumps({"unsplash_access_key": "fromfile"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    assert mod._resolve_unsplash_key() == "fromfile"


def test_unsplash_key_walks_up_to_parent_deploy_json(monkeypatch, tmp_path):
    """Key is found in a parent .deploy.json when CWD is a subdirectory."""
    mod = _load_module()
    deploy = tmp_path / ".deploy.json"
    deploy.write_text(json.dumps({"unsplash_access_key": "ancestor"}), encoding="utf-8")
    nested = tmp_path / "drafts" / "post-slug"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    assert mod._resolve_unsplash_key() == "ancestor"


def test_unsplash_key_returns_none_when_nowhere(monkeypatch, tmp_path):
    """None when neither env var nor any .deploy.json provides the key."""
    mod = _load_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    assert mod._resolve_unsplash_key() is None


def test_unsplash_key_skips_malformed_deploy_json(monkeypatch, tmp_path):
    """Malformed .deploy.json is reported and treated as no key (no crash)."""
    mod = _load_module()
    deploy = tmp_path / ".deploy.json"
    deploy.write_text("{not valid json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    assert mod._resolve_unsplash_key() is None
