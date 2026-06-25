"""Unit tests for _is_allowed_unreachable host matching (FIND-03).

Pre-fix the helper matched on substring (``part in netloc``), so a host like
``example.com.evil.com`` was treated as allowlisted and skipped the Gate 5
HEAD check. These tests pin exact-hostname semantics. Stdlib + pytest only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = ROOT / "scripts" / "blog_preflight.py"


@pytest.fixture
def preflight_module():
    spec = importlib.util.spec_from_file_location("blog_preflight_allowlist", PREFLIGHT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["blog_preflight_allowlist"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("url,allowed", [
    # Exact allowlist entries -> allowed (skip HEAD check).
    ("https://example.com/x", True),
    ("http://example.org/y", True),
    ("https://localhost:3000/a", True),
    ("http://127.0.0.1/z", True),
    # Case-insensitive host.
    ("https://EXAMPLE.COM/x", True),
    # Port is stripped by urlparse.hostname; host still matches.
    ("https://example.com:8443/x", True),
    # Substring / lookalike hosts must NOT be treated as allowlisted.
    ("https://example.com.evil.com/x", False),
    ("https://evil-example.com/x", False),
    ("https://example.com.evil.com", False),
    ("https://notexample.com/x", False),
    # A subdomain of an allowlisted apex is NOT in the bare allowlist.
    ("https://www.example.com/x", False),
    # Unrelated host.
    ("https://evil.com/x", False),
    # No host -> not allowed.
    ("/relative/path", False),
])
def test_is_allowed_unreachable_exact_hostname(preflight_module, url, allowed):
    assert preflight_module._is_allowed_unreachable(url) is allowed
