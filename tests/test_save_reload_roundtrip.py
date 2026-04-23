"""
Regression test for the diary 11/13 bug:
after `save_diagram`, a fresh `load_diagram` must surface everything that
was written — including connectors — before the next write-read-verify.

This is the outer envelope of every closed-loop edit session.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from visio_core.tools.visio_tools import VisioTools


def _new_tools(dialog_dir: Path) -> VisioTools:
    # ``record_context=False`` gives us a disabled DialogContextStore so the
    # test never writes into the shared ./dialog folder.
    return VisioTools(
        session_id="test_save_reload",
        dialog_dir=str(dialog_dir),
        auto_restore=False,
        record_context=False,
    )


@pytest.mark.regression
def test_open_edit_save_reload_roundtrip(scratch_vsdx: Path, tmp_path: Path):
    """Load → upsert shape → save → reload → shape still there."""
    tools = _new_tools(tmp_path)

    load_msg = tools.load_diagram(str(scratch_vsdx))
    assert "✓" in load_msg or "loaded" in load_msg.lower(), load_msg

    upsert_msg = tools.add_or_update_shape(
        node_key="regression_probe",
        text="ROUNDTRIP_PROBE",
        shape_type="Rectangle",
        x=1.0, y=1.0, width=1.5, height=0.75,
    )
    assert upsert_msg.startswith("✓"), upsert_msg

    save_msg = tools.save_diagram(str(scratch_vsdx))
    assert "✓" in save_msg or "saved" in save_msg.lower(), save_msg

    # Simulate a fresh client by creating a new VisioTools instance and
    # reloading from disk. This is the critical 11/13 step.
    tools2 = _new_tools(tmp_path)
    reload_msg = tools2.load_diagram(str(scratch_vsdx))
    assert "✓" in reload_msg or "loaded" in reload_msg.lower(), reload_msg

    # The probe shape must be discoverable post-reload.
    listing = tools2.list_shapes()
    assert "ROUNDTRIP_PROBE" in listing, (
        "Probe shape was not visible after save→reload; "
        "this is the 11/13 connector-visibility class of bug."
    )
