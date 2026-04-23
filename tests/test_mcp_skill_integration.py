"""
Priority 6 acceptance — deterministic MCP/skill closed-loop coverage.

This suite exercises the MCP registry path end-to-end *without* a live
LLM: no DeepSeek / OpenAI key required, no network I/O. The test is a
"registry + invoke + output-shape" probe, not a full skill execution.

What it covers
--------------
1. ``build_server_registry`` applies patches and returns the exact
   consolidated tool set (parity with ``CONSOLIDATED_TOOL_NAMES``).
2. Purely read-only tools that do not hit an LLM are invokable through
   the registry and return non-empty string payloads:
       - ``search_templates`` (with and without keywords)
       - ``search_stencils`` (without keywords)
3. The skill layer points at the consolidated tool names (so the two
   halves of the migration stay in lock-step).

What is **not** covered here (requires CI + network)
----------------------------------------------------
- Real LLM-driven ``recommend_template`` / ``analyze_template``.
- Full skill-driven scenario execution (the agno agent loop).
- The stdio MCP transport itself (``serve_stdio``) — exercised manually.

See ``tests/test_skill_manifest.py`` for the structural skill checks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("agno")

from visio_mcp import MCP_TOOL_NAMES
from visio_mcp.server import build_server_registry, invoke


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_FILE = REPO_ROOT / "skills" / "visio" / "SKILL.md"


@pytest.fixture(scope="module")
def mcp_registry(tmp_path_factory: pytest.TempPathFactory):
    """Build one registry for the whole module; ``apply_patches`` is idempotent."""
    dialog_dir = tmp_path_factory.mktemp("mcp_integration_dialog")
    return build_server_registry(
        template_dir=str(REPO_ROOT / "assets" / "templates"),
        dialog_dir=str(dialog_dir),
        session_id="mcp_integration_probe",
    )


def test_registry_matches_contract_exactly(mcp_registry):
    assert set(mcp_registry.keys()) == set(MCP_TOOL_NAMES)
    # Contract is declarative — order-insensitive membership is the
    # real guarantee; the contract test in test_mcp_contract.py owns
    # the ordering assertion.


def test_search_templates_empty_keywords_lists_library(mcp_registry):
    """`search_templates` with no keywords must return the full listing."""
    out = invoke(mcp_registry, "search_templates")
    assert isinstance(out, str) and out.strip(), (
        "search_templates() must return a non-empty string even when the "
        "library is empty (it should say so)."
    )


def test_search_templates_with_keyword_returns_deterministic_shape(mcp_registry):
    """Keyword search path is deterministic (no LLM) — only index lookups."""
    out = invoke(mcp_registry, "search_templates", keywords=["flowchart"])
    assert isinstance(out, str) and out.strip()


def test_search_stencils_empty_keywords_lists_library(mcp_registry):
    out = invoke(mcp_registry, "search_stencils")
    assert isinstance(out, str) and out.strip()


def test_unknown_tool_raises_structured_error(mcp_registry):
    """Invoking an unregistered name must produce a ``VisioToolError``.

    Shape duplication of ``test_mcp_contract.py`` is intentional — this
    test uses the *real* populated registry so we catch the case where a
    collision between a registered and unknown name would shadow the
    error path.
    """
    from visio_mcp import VisioToolError, ErrorCode

    with pytest.raises(VisioToolError) as excinfo:
        invoke(mcp_registry, "this_tool_does_not_exist", x=1)
    assert excinfo.value.code == ErrorCode.SELECTOR_NOT_FOUND


def test_skill_manifest_references_consolidated_tool_names():
    """The skill file must target the canonical tool names.

    This is the simplest deterministic guard that the skill-driven
    agent would not receive stale tool references when it runs under
    CI. Heavier end-to-end execution remains CI-only.
    """
    assert SKILL_FILE.exists(), f"Missing {SKILL_FILE}"
    content = SKILL_FILE.read_text(encoding="utf-8")

    # A small curated set — not the full 15 — to keep the test
    # meaningful without coupling it to skill prose.
    required_mentions = [
        "recommend_template",
        "analyze_template",
        "upsert_shape",
        "upsert_connector",
        "save_document",
        "edit_shape",
    ]
    missing = [name for name in required_mentions if name not in content]
    assert not missing, (
        f"Skill file {SKILL_FILE} is missing references to: {missing}. "
        "When the consolidated tool surface changes, update the skill "
        "so the agent keeps calling the right names."
    )
