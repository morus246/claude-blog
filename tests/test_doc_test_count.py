"""Documented-test-count coherence regression test.

Asserts that the test count advertised in README.md (the shields.io badge)
and CLAUDE.md (the `tests/` tree comment) matches the real number of test
functions in the suite.

Added after the pipeline-verification pass found the suite had grown to 187
while README body, CLAUDE.md, and three docs/ files still said "160" (and the
README badge said 187, contradicting its own body). The existing
`version-coherence` gate enforces version *strings* but nothing enforced the
documented *test count*, so it drifted silently when v1.9.1 added 27 tests.
This test catches the class-of-defect on every PR.

Stdlib + pytest only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_TEST_DEF = re.compile(r"^\s*def test_", re.MULTILINE)
_README_BADGE = re.compile(r"Tests-(\d+)%20passing")
_CLAUDE_SUITE = re.compile(r"pytest suite \((\d+) tests\)")


def _actual_test_count() -> int:
    total = 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        total += len(_TEST_DEF.findall(path.read_text(encoding="utf-8")))
    return total


def test_documented_test_count_matches_actual() -> None:
    actual = _actual_test_count()

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    badge = _README_BADGE.search(readme)
    assert badge is not None, "README.md test badge not found"
    assert int(badge.group(1)) == actual, (
        f"README badge says {badge.group(1)} tests but suite has {actual}"
    )

    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    suite = _CLAUDE_SUITE.search(claude)
    assert suite is not None, "CLAUDE.md 'pytest suite (N tests)' line not found"
    assert int(suite.group(1)) == actual, (
        f"CLAUDE.md says {suite.group(1)} tests but suite has {actual}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
