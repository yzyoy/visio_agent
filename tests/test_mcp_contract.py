"""
Batch B Phase 4 acceptance test — MCP contract parity.

The MCP surface must be derived directly from
``visio_core.tools.consolidated.CONSOLIDATED_TOOL_NAMES``. This test
asserts:

1. ``visio_mcp.MCP_TOOL_NAMES`` is identical to the consolidated tuple.
2. Every MCP spec has a summary, idempotency flag, and at least zero
   error codes (structure check).
3. The runtime registry exposes exactly the contracted names.
4. Unknown-tool invocation returns a structured ``VisioToolError``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# The registry build path goes through PromptTools -> SmartMatcher ->
# agno.models.openai, so agno must be installed for that specific test.
pytest.importorskip("agno")

from visio_core.tools.consolidated import CONSOLIDATED_TOOL_NAMES
from visio_mcp import (
    MCP_TOOL_NAMES,
    MCP_TOOL_SPECS,
    VisioToolError,
    ErrorCode,
    build_tool_registry,
)
from visio_mcp.server import invoke


def test_mcp_tool_names_match_consolidated_exactly():
    assert MCP_TOOL_NAMES == CONSOLIDATED_TOOL_NAMES, (
        "MCP_TOOL_NAMES must be derived directly from "
        "CONSOLIDATED_TOOL_NAMES with no additions or reorderings."
    )


def test_every_tool_has_a_spec_with_structured_metadata():
    spec_by_name = {spec.name: spec for spec in MCP_TOOL_SPECS}
    assert set(spec_by_name) == set(MCP_TOOL_NAMES)
    for spec in MCP_TOOL_SPECS:
        assert spec.summary, f"{spec.name} missing summary"
        assert isinstance(spec.idempotent, bool)
        assert isinstance(spec.mutates, bool)
        # Error codes must reference enum values (string equality).
        known_codes = {c.value for c in ErrorCode}
        for code in spec.error_codes:
            assert code in known_codes, (
                f"{spec.name} declares unknown error code {code!r}; "
                "extend ErrorCode enum before using it."
            )


def test_registry_exposes_exactly_the_contracted_names(tmp_path: Path):
    from visio_core.tools.visio_tools import VisioTools
    from visio_core.tools.prompt_tools import PromptTools

    visio_tools = VisioTools(
        session_id="mcp_contract_probe",
        dialog_dir=str(tmp_path),
        auto_restore=False,
        record_context=False,
    )
    prompt_tools = PromptTools(template_dir="assets/templates")
    registry = build_tool_registry(visio_tools, prompt_tools)

    assert set(registry.keys()) == set(MCP_TOOL_NAMES), (
        "Registry drift. Missing: "
        f"{set(MCP_TOOL_NAMES) - set(registry.keys())}. Unexpected: "
        f"{set(registry.keys()) - set(MCP_TOOL_NAMES)}."
    )
    for name, fn in registry.items():
        assert callable(fn), f"{name} registered as non-callable {fn!r}"


def test_invoke_raises_structured_error_on_unknown_tool():
    err = None
    try:
        invoke({}, "nonexistent_tool", x=1)
    except VisioToolError as e:
        err = e
    assert err is not None, "Invoking an unknown tool must raise."
    assert err.code == ErrorCode.SELECTOR_NOT_FOUND
    payload = err.to_dict()
    assert payload["code"] == "SELECTOR_NOT_FOUND"
    assert "nonexistent_tool" in payload["message"]
