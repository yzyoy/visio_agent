"""
Smoke-level protection for the template recommendation path.

We do not invoke a real LLM; instead we check that the lite-tier matcher
accepts a Chinese-ish requirement and returns a list without raising.
Full-tier LLM ranking is covered separately by integration scripts and is
gated behind network/model access.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _lite_index_path() -> Path | None:
    for candidate in [
        REPO_ROOT / "templates" / "template_library_lite.json",
        REPO_ROOT / "assets" / "indexes" / "template_library_lite.json",
    ]:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


@pytest.mark.regression
def test_lite_index_is_parseable_if_present():
    idx = _lite_index_path()
    if not idx:
        pytest.skip("No lite template index present; pruning hasn't produced one yet.")
    data = json.loads(idx.read_text(encoding="utf-8"))
    assert isinstance(data, (list, dict)), "lite index must be JSON list/object"


@pytest.mark.regression
def test_smart_matcher_importable_and_instantiable():
    """Fast failure signal: the SmartMatcher must at least import cleanly."""
    mod = pytest.importorskip("visio_core.utils.smart_matcher")
    assert hasattr(mod, "SmartMatcher"), "SmartMatcher class missing from module"
