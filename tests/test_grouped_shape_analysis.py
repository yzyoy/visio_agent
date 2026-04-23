"""
Regression test for the 11/2 group-nested-shape gap.

This test is intentionally permissive today: it verifies that the structural
analyzer is *wired* and does not silently drop on a non-trivial template.
Batch B will tighten this into an exact group-recursion assertion once a
dedicated grouped fixture is added under ``tests/fixtures/``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from visio_core.tools.visio_tools import VisioTools


@pytest.mark.regression
def test_structural_listing_returns_nonempty_for_real_template(
    scratch_vsdx: Path, tmp_path: Path
):
    tools = VisioTools(
        session_id="test_group",
        dialog_dir=str(tmp_path),
        auto_restore=False,
        record_context=False,
    )
    tools.load_diagram(str(scratch_vsdx))

    listing = tools.list_shapes()
    # A real template fixture must surface at least one shape.
    assert listing and len(listing.strip()) > 0, "list_shapes returned empty"
    # The current list_shapes may or may not recurse into groups; when Batch B
    # adds the grouped fixture, flip this to a strict count assertion.
    pytest.importorskip("vsdx")
