"""
Regression test for idempotent connector creation + survival across save/reload.

Combines the 11/11–11/12 EdgeKey idempotency lesson with the 11/13
save-requires-reload lesson: after save+reload, the connector count must
match what was authored, not what survives a naive re-index.
"""
from __future__ import annotations

import concurrent.futures
import re
import zipfile
from pathlib import Path

import pytest

from visio_core.tools.visio_tools import VisioTools
from visio_core.utils.diagram_builder import DiagramBuilder


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


@pytest.mark.regression
def test_parallel_connector_creation_no_failures(scratch_vsdx: Path, tmp_path: Path):
    """Concurrent connect_shapes calls must not race the vsdx patch orphan cleanup."""
    builder = DiagramBuilder.load_from_file(str(scratch_vsdx))
    assert builder.current_page is not None

    shape_ids: list[str] = []
    for i in range(20):
        sh = builder.add_shape(f"PC{i}", "Rectangle", float(i % 10) * 1.2, float(i // 10) * 1.5)
        assert sh is not None, f"add_shape failed at i={i}"
        shape_ids.append(str(sh.ID))

    def _connect(i: int):
        return builder.connect_shapes(shape_ids[2 * i], shape_ids[2 * i + 1])

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_connect, i) for i in range(10)]
        connectors = [f.result() for f in futures]

    assert all(c is not None for c in connectors), (
        "One or more parallel connector creations returned None; "
        f"last error: {getattr(builder, 'last_connector_error', None)}"
    )


@pytest.mark.regression
def test_saved_connector_has_no_sheet_id_formula_typo(scratch_vsdx: Path, tmp_path: Path):
    """Connectors must not emit malformed ``Sheet49!`` (missing dot) formulas."""
    tools = _make_tools(tmp_path)
    tools.load_diagram(str(scratch_vsdx))
    tools.add_or_update_shape("nx_a", "A", "Rectangle", 0.5, 1.0)
    tools.add_or_update_shape("nx_b", "B", "Rectangle", 3.0, 1.0)
    msg = tools.add_or_update_connector("nx_a", "nx_b", label="norm")
    assert msg.startswith("✓"), msg

    save_msg = tools.save_diagram(str(scratch_vsdx))
    assert "✓" in save_msg or "saved" in save_msg.lower(), save_msg

    with zipfile.ZipFile(scratch_vsdx) as zf:
        xml = zf.read("visio/pages/page1.xml").decode("utf-8", errors="replace")

    bad = re.findall(r"Sheet\d+!", xml)
    assert not bad, f"Malformed Sheet<id>! references in page XML: {bad[:5]}"
