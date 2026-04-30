"""
Phase 2 contract test — the consolidated LLM-facing surface.

This is the single source of truth for the Batch A tool contract.
If it fails, some downstream prompt/skill rely on a tool name that is
no longer in the consolidated surface and the change is a breaking one.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

# ``PromptTools`` transitively imports agno via SmartMatcher. Without agno
# the contract test cannot build the surface — skip cleanly in that case.
pytest.importorskip("agno")

from visio_core.tools.consolidated import (
    CONSOLIDATED_TOOL_NAMES,
    get_consolidated_tools,
    get_agent_tools,
)


EXPECTED_NAMES = {
    "recommend_template",
    "search_templates",
    "analyze_template",
    "search_stencils",
    "get_stencil",
    "open_document",
    "create_from_template",
    "save_document",
    "render_page",
    "upsert_shape",
    "upsert_connector",
    "update_text",
    "remove_shape",
    "edit_shape",
    "insert_from_stencil",
}


def _make_pair(tmp_path: Path):
    from visio_core.tools.visio_tools import VisioTools
    from visio_core.tools.prompt_tools import PromptTools

    visio_tools = VisioTools(
        session_id="contract_probe",
        dialog_dir=str(tmp_path),
        auto_restore=False,
        record_context=False,
    )
    prompt_tools = PromptTools(template_dir="assets/templates")
    return visio_tools, prompt_tools


def test_consolidated_names_match_declared_constant():
    assert set(CONSOLIDATED_TOOL_NAMES) == EXPECTED_NAMES


def test_primary_surface_has_exactly_the_declared_tools(tmp_path):
    visio_tools, prompt_tools = _make_pair(tmp_path)
    tools = get_consolidated_tools(visio_tools, prompt_tools)
    names = [t.__name__ for t in tools]

    assert len(names) == len(set(names)), f"Duplicate names in primary surface: {names}"
    assert set(names) == EXPECTED_NAMES, (
        f"Primary surface drift. Missing: {EXPECTED_NAMES - set(names)}. "
        f"Unexpected: {set(names) - EXPECTED_NAMES}."
    )


def test_primary_surface_is_not_inflated(tmp_path):
    """The whole point of Batch A Phase 2 is reduction. Guard the ceiling.

    Post-Batch-B consolidation lands the final 15-tool ceiling from
    ``refine/CORE_CAPABILITIES.md`` §2.1. Do not grow it without retiring
    one first.
    """
    visio_tools, prompt_tools = _make_pair(tmp_path)
    tools = get_consolidated_tools(visio_tools, prompt_tools)
    assert len(tools) <= 15, (
        f"Primary surface grew to {len(tools)} tools; roadmap ceiling is "
        "15. Do not add new LLM-facing tools without retiring one first."
    )


def test_agent_tools_match_consolidated_surface_exactly(tmp_path):
    """Post-refactor: the deprecation alias band has been retired. The
    agno-facing agent tool list is now identical to the consolidated
    15-tool surface. No legacy names, no parallel paths.
    """
    visio_tools, prompt_tools = _make_pair(tmp_path)
    agent_tools = get_agent_tools(visio_tools, prompt_tools)
    consolidated = get_consolidated_tools(visio_tools, prompt_tools)
    assert len(agent_tools) == len(consolidated) == 15
    assert {t.__name__ for t in agent_tools} == EXPECTED_NAMES


def test_recommend_template_signature_matches_skill_contract(tmp_path):
    visio_tools, prompt_tools = _make_pair(tmp_path)
    tools = {tool.__name__: tool for tool in get_consolidated_tools(visio_tools, prompt_tools)}
    recommend = tools["recommend_template"]
    params = inspect.signature(recommend).parameters

    assert "requirement" in params, "recommend_template must accept a natural-language requirement"
    assert "top_k" in params, "recommend_template must accept top_k"
    assert "candidate_templates_json" not in params, (
        "recommend_template must no longer expose the legacy candidate_templates_json argument"
    )


def test_diagnostic_and_session_tools_are_not_llm_facing(tmp_path):
    """Session/diagnostic helpers stay internal. They must not appear under
    their raw names on the primary surface."""
    visio_tools, prompt_tools = _make_pair(tmp_path)
    primary = {t.__name__ for t in get_consolidated_tools(visio_tools, prompt_tools)}
    forbidden = {
        "set_session", "reset_session", "get_session_context",
        "cleanup_diagram_connectors", "validate_diagram_connectors",
        "verify_connector_persisted", "get_log_summary",
        "ensure_all_shapes_have_keys",
        "validate_prompt_tools", "get_available_visio_tools",
        "cleanup_analysis_temp_files",
        # 6-step facade must be collapsed into analyze_template
        "load_template_for_analysis", "get_diagram_info_from_loaded",
        "list_shapes_from_loaded", "analyze_connections_from_loaded",
        "list_position_from_loaded",
    }
    leaked = primary & forbidden
    assert not leaked, f"Internal-only tools leaked to the LLM surface: {leaked}"
