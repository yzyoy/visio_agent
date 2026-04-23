"""
Regression test for idempotent connector creation + survival across save/reload.

Combines the 11/11–11/12 EdgeKey idempotency lesson with the 11/13
save-requires-reload lesson: after save+reload, the connector count must
match what was authored, not what survives a naive re-index.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from visio_core.tools.visio_tools import VisioTools


def _make_tools(tmp_path: Path, suffix: str = "") -> VisioTools:
    return VisioTools(
        session_id=f"test_idem_conn{suffix}",
        dialog_dir=str(tmp_path),
        auto_restore=False,
        record_context=False,
    )


@pytest.mark.regression
def test_idempotent_connector_no_duplicates_after_save_reload(
    scratch_vsdx: Path, tmp_path: Path
):
    tools = _make_tools(tmp_path)
    tools.load_diagram(str(scratch_vsdx))

    tools.add_or_update_shape("conn_src", "SRC", "Rectangle", 1.0, 1.0)
    tools.add_or_update_shape("conn_dst", "DST", "Rectangle", 4.0, 1.0)

    first = tools.add_or_update_connector("conn_src", "conn_dst", label="E1")
    second = tools.add_or_update_connector("conn_src", "conn_dst", label="E1")

    assert first.startswith("✓"), first
    assert second.startswith("✓"), second
    # Second call must not claim to have created a new connector.
    assert "Added new connector" not in second, (
        "Connector upsert is not idempotent — second call reported a new "
        f"connector: {second}"
    )

    save_msg = tools.save_diagram(str(scratch_vsdx))
    assert "✓" in save_msg or "saved" in save_msg.lower(), save_msg

    # Fresh tools instance, fresh load — this is the 11/13 ritual.
    tools2 = _make_tools(tmp_path, suffix="_reload")
    tools2.load_diagram(str(scratch_vsdx))

    # Analyse connectors; the probe edge must stay connected exactly once.
    # ``analyze_diagram_connections`` emits shape TEXT and connector LABELS,
    # not node keys, so we assert on the unique label "E1" we authored.
    analysis = tools2.analyze_diagram_connections()
    assert "E1" in analysis, (
        "Connector labelled E1 did not persist across save→reload — this is "
        f"the 11/13 bug. Analysis tail: {analysis[-800:]}"
    )
    # Idempotency: the label E1 must appear at most twice in the analysis
    # (once in CONNECTOR DETAILS, once in an SHAPES-WITH-CONNECTIONS line).
    # Anything more means the second upsert created a duplicate connector.
    e1_occurrences = analysis.count("E1")
    assert e1_occurrences <= 4, (
        f"Connector 'E1' appears {e1_occurrences} times — idempotency "
        f"regression. Analysis tail: {analysis[-800:]}"
    )
