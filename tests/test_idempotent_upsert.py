"""
Regression test for idempotent shape creation.

Running the same `add_or_update_shape` with the same `node_key` twice must
not create two shapes. The second call should report an update, not an add.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from visio_core.tools.visio_tools import VisioTools


@pytest.mark.regression
def test_idempotent_shape_upsert_no_duplicates(scratch_vsdx: Path, tmp_path: Path):
    tools = VisioTools(
        session_id="test_idem_shape",
        dialog_dir=str(tmp_path),
        auto_restore=False,
        record_context=False,
    )
    tools.load_diagram(str(scratch_vsdx))

    first = tools.add_or_update_shape(
        node_key="idem_node",
        text="IDEM_PROBE",
        shape_type="Rectangle",
        x=2.0, y=2.0,
    )
    second = tools.add_or_update_shape(
        node_key="idem_node",
        text="IDEM_PROBE",
        shape_type="Rectangle",
        x=2.0, y=2.0,
    )

    assert first.startswith("✓"), first
    assert second.startswith("✓"), second

    # Second call must not claim to have created a new shape.
    assert "Added new shape" not in second, (
        "Second upsert must be idempotent — expected 'Updated' / 'unchanged' "
        f"but got: {second}"
    )

    # And the listing must not contain two shapes bearing the probe text.
    listing = tools.list_shapes()
    occurrences = listing.count("IDEM_PROBE")
    assert occurrences == 1, (
        f"Expected exactly 1 shape tagged IDEM_PROBE, found {occurrences}. "
        "Idempotent upsert is broken."
    )
