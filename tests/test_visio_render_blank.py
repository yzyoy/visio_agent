from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from visio_core.tools.consolidated import _build_upsert_connector
from visio_core.utils import visio_render
from visio_core.utils.diagram_builder import DiagramBuilder
from visio_core.utils.exceptions import VisioError


def test_blank_backend_output_raises_instead_of_returning_png(tmp_path, monkeypatch):
    src = tmp_path / "diagram.vsdx"
    src.write_bytes(b"fake-vsdx")

    def write_blank(_src: Path, _page: int, _dpi: int, out_png: Path) -> None:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        out_png.write_bytes(b"blank-png")

    monkeypatch.setattr(visio_render, "_backend_order", lambda: ["libreoffice"])
    monkeypatch.setattr(visio_render, "_libreoffice_available", lambda: True)
    monkeypatch.setattr(visio_render, "_render_with_libreoffice", write_blank)
    monkeypatch.setattr(visio_render, "_is_blank_png", lambda _path: True)

    with pytest.raises(VisioError) as exc_info:
        visio_render.render_vsdx_page_to_png(
            str(src),
            allowed_extra_path=str(src),
        )

    message = str(exc_info.value)
    assert "detected as blank" in message
    assert "libreoffice" in message
    assert b"blank-png" not in message.encode("utf-8")


def test_blank_preview_cache_is_discarded_and_re_rendered(tmp_path, monkeypatch):
    src = tmp_path / "diagram.vsdx"
    src.write_bytes(b"fake-vsdx")
    preview_dir = tmp_path / "preview-cache"
    preview_dir.mkdir()

    revision = visio_render._source_revision(src)
    key = visio_render._preview_cache_key(src.resolve(), 0, revision)
    cached = preview_dir / f"{key}.png"
    cached.write_bytes(b"blank-cache")

    blank_checks = []

    def is_blank(path: Path) -> bool:
        blank_checks.append(path)
        return path == cached and path.read_bytes() == b"blank-cache"

    def render_png(**_kwargs) -> bytes:
        return b"fresh-render"

    monkeypatch.setattr(visio_render, "_preview_cache_dir", lambda: preview_dir)
    monkeypatch.setattr(visio_render, "_is_blank_png", is_blank)
    monkeypatch.setattr(visio_render, "render_vsdx_page_to_png", render_png)

    result = visio_render.render_and_cache_preview(
        str(src),
        allowed_extra_path=str(src),
    )

    assert result["cached"] is False
    assert result["bytes"] == b"fresh-render"
    assert cached.read_bytes() == b"fresh-render"
    assert blank_checks


def test_upsert_connector_accepts_public_port_names():
    calls = []

    class DummyTools:
        def add_or_update_connector(self, **kwargs):
            calls.append(kwargs)
            return "ok"

    upsert_connector = _build_upsert_connector(DummyTools())

    assert (
        upsert_connector(
            from_node_key="a",
            to_node_key="b",
            label="yes",
            router="right_angle",
            from_port="Bottom",
            to_port="Top",
        )
        == "ok"
    )

    assert calls == [
        {
            "from_node_key": "a",
            "to_node_key": "b",
            "label": "yes",
            "routing_style": "right_angle",
            "from_glue_point": "Bottom",
            "to_glue_point": "Top",
        }
    ]


def test_connects_table_preserves_top_connection_index_zero():
    ns_uri = "http://schemas.microsoft.com/office/visio/2012/main"
    page_xml = ET.Element(f"{{{ns_uri}}}Page")
    connector = SimpleNamespace(ID="10")
    from_shape = SimpleNamespace(ID="1")
    to_shape = SimpleNamespace(ID="2")
    builder = SimpleNamespace(current_page=SimpleNamespace(xml=page_xml))

    DiagramBuilder._update_connector_connects(
        builder,
        connector,
        from_shape,
        to_shape,
        0,
        0,
    )

    connects = list(page_xml.iter(f"{{{ns_uri}}}Connect"))
    assert len(connects) == 4
    assert connects[0].get("ToCell") == "Connections.X0"
    assert connects[1].get("ToCell") == "Connections.Y0"
    assert connects[2].get("ToCell") == "Connections.X0"
    assert connects[3].get("ToCell") == "Connections.Y0"

