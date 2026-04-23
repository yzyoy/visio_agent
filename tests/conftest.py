"""
Pytest fixtures for the regression suite.

Design intent:
- Tests exercise ``visio_core`` without requiring network access, the
  agno agent, or a real LLM.
- Each mutating test copies a read-only template fixture into a tmp_path,
  so the source-of-truth VSDX files are never modified in place.
- Patches MUST be applied explicitly via ``visio_core.apply_patches()``
  because the connector-visibility behaviour relies on the patched
  ``vsdx`` library. ``apply_patches()`` is idempotent.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# Apply vsdx-library patches explicitly via the canonical entry point.
# No import-time side effects; ``apply_patches()`` is idempotent.
try:
    from visio_core.patches import apply_patches as _apply_patches
    _apply_patches()
except Exception:  # pragma: no cover
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent

# Canonical fixtures are small, real VSDX files already in the repo.
# Order matters: prefer a small, purpose-built structured template that has
# at least one shape on its first page, because ``DiagramBuilder`` clones an
# existing shape when a new one is requested by type. A zero-shape page (as
# in ``assets/templates/transformer_architecture.vsdx``) fails the mutation tests.
CANDIDATE_FIXTURES = [
    # Canonical regression fixture (134 shapes, no "SRC"/"DST"/"E1" text
    # collisions with the regression probes). ``find_shape_by_fallback``
    # will not misadopt pre-existing shapes.
    REPO_ROOT / "tests" / "fixtures" / "transformer_architecture.vsdx",
    REPO_ROOT / "assets" / "templates" / "transformer_architecture.vsdx",
    REPO_ROOT / "assets" / "templates" / "transformer.vsdx",
]


def _page_has_shapes(path: Path) -> bool:
    """Return True if the first page of ``path`` has at least one shape.

    Guards against empty-canvas fixtures that trip the "Available shape
    types on page: none" fail path inside ``DiagramBuilder``.
    """
    try:
        import vsdx  # local import: tests may run without vsdx installed
    except Exception:
        # Cannot verify, so trust existence as a fallback.
        return True
    try:
        doc = vsdx.VisioFile(str(path))
        pages = getattr(doc, "pages", []) or []
        if not pages:
            return False
        shapes = getattr(pages[0], "all_shapes", []) or []
        return len(shapes) > 0
    except Exception:
        return False


def _first_available_fixture() -> Path | None:
    for path in CANDIDATE_FIXTURES:
        if not (path.exists() and path.stat().st_size > 0):
            continue
        if _page_has_shapes(path):
            return path
    return None


@pytest.fixture(scope="session")
def fixture_vsdx_path() -> Path:
    """Absolute path to a small, real VSDX fixture. Skips if unavailable."""
    path = _first_available_fixture()
    if not path:
        pytest.skip(
            "No VSDX fixture available for regression tests. "
            "Expected at least one of: "
            + ", ".join(str(p) for p in CANDIDATE_FIXTURES)
        )
    return path


@pytest.fixture()
def scratch_vsdx(tmp_path: Path, fixture_vsdx_path: Path) -> Path:
    """Return a mutable copy of the fixture VSDX in a per-test tmp dir."""
    dst = tmp_path / fixture_vsdx_path.name
    shutil.copy2(fixture_vsdx_path, dst)
    return dst


@pytest.fixture()
def chdir_repo_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Some tools resolve relative paths against CWD — pin it to repo root."""
    monkeypatch.chdir(REPO_ROOT)
    return REPO_ROOT
