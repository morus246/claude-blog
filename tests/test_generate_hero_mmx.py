"""Tests for generate_hero._try_mmx (mmx CLI image generation)."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
HERO_PATH = ROOT / "scripts" / "generate_hero.py"


@pytest.fixture(scope="module")
def hero_module():
    spec = importlib.util.spec_from_file_location("generate_hero", HERO_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_hero"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_try_mmx_returns_none_when_cli_not_found(hero_module, monkeypatch, tmp_path):
    """_try_mmx returns None when mmx is not in PATH."""
    monkeypatch.setattr(shutil, "which", lambda _: None)
    result = hero_module._try_mmx("anxiety tips", ["ansiedade"], tmp_path)
    assert result is None


def test_try_mmx_returns_none_on_quota_exhausted(hero_module, monkeypatch, tmp_path):
    """_try_mmx returns None when mmx quota JSON reports remaining=0."""
    import json
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mmx")

    class _QuotaResult:
        returncode = 0
        stdout = json.dumps({"remaining": 0})
        stderr = ""

    def fake_run(cmd, **kwargs):
        if "quota" in cmd:
            return _QuotaResult()
        raise AssertionError("generate should not be called after quota exhausted")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = hero_module._try_mmx("anxiety tips", ["ansiedade"], tmp_path)
    assert result is None


def test_try_mmx_returns_none_on_nonzero_exit(hero_module, monkeypatch, tmp_path):
    """_try_mmx returns None when mmx image generate exits nonzero."""
    import json
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mmx")

    class _R:
        returncode = 1
        stdout = ""
        stderr = "auth error"

    def fake_run(cmd, **kwargs):
        if "quota" in cmd:
            r = type("R", (), {"returncode": 0, "stdout": json.dumps({"remaining": 10}), "stderr": ""})()
            return r
        return _R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = hero_module._try_mmx("anxiety tips", ["ansiedade"], tmp_path)
    assert result is None


def test_try_mmx_returns_dict_on_success(hero_module, monkeypatch, tmp_path):
    """_try_mmx renames raw/hero_001.jpg to hero.jpg and returns dict."""
    import json
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mmx")

    def fake_run(cmd, **kwargs):
        if "quota" in cmd:
            r = type("R", (), {"returncode": 0, "stdout": json.dumps({"remaining": 10}), "stderr": ""})()
            return r
        # Simulate mmx writing raw/hero_001.jpg
        out_dir_flag = cmd[cmd.index("--out-dir") + 1]
        raw_dir = Path(out_dir_flag)
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "hero_001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = hero_module._try_mmx("anxiety tips", ["ansiedade"], tmp_path)
    assert result is not None
    assert result["source"] == "mmx"
    assert Path(result["path"]).name == "hero.jpg"
    assert (tmp_path / "hero.jpg").exists()
    assert (tmp_path / "hero-credit.txt").exists()


def test_try_mmx_returns_none_when_output_file_missing(hero_module, monkeypatch, tmp_path):
    """_try_mmx returns None if mmx exits 0 but does not write the output file."""
    import json
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mmx")

    def fake_run(cmd, **kwargs):
        if "quota" in cmd:
            r = type("R", (), {"returncode": 0, "stdout": json.dumps({"remaining": 5}), "stderr": ""})()
            return r
        # Create raw/ dir but no hero file
        out_dir_flag = cmd[cmd.index("--out-dir") + 1]
        Path(out_dir_flag).mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = hero_module._try_mmx("anxiety tips", ["ansiedade"], tmp_path)
    assert result is None
