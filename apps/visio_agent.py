"""
Visio Agent factory — agno-facing orchestration.

The Visio agent binds the pure-library :mod:`visio_core` surface to the
agno ``Agent`` class. It also injects the LLM into ``PromptTools`` so
:class:`visio_core.utils.smart_matcher.SmartMatcher` stays agno-free.
"""
from __future__ import annotations

from typing import Any, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from visio_core.tools.visio_tools import VisioTools
from visio_core.tools.prompt_tools import PromptTools
from visio_core.tools.consolidated import get_agent_tools
from visio_core.templates.template_manager import TemplateManager
from visio_core.context.instruction_loader import get_instruction_loader
from visio_core.context.instruction_builder import get_instruction_builder
from visio_core.context.session_context import DialogContextStore, SessionContext


def create_visio_agent(
    model: OpenAIChat,
    template_dir: str = "assets/templates",
    session_id: str = "default",
    new_session: bool = False,
    dialog_dir: str = ".state/dialog",
    instruction_profile: str = "full",
    use_dynamic_instructions: bool = True,
    db: Optional[Any] = None,
) -> Agent:
    """Build the agno Visio agent wired onto the consolidated 16-tool surface.

    Args:
        model: agno-compatible LLM model (e.g. OpenAIChat / DeepSeek).
        template_dir: Filesystem path to the curated template library.
        session_id: Session identifier for VisioTools / dialog store.
        new_session: Reset persistent session state on creation.
        dialog_dir: Directory for session dialog persistence.
        instruction_profile: Instruction profile passed to the loader
            when dynamic instructions are disabled.
        use_dynamic_instructions: Use the context-aware InstructionBuilder
            (recommended) instead of the legacy full template.
        db: Optional agno db instance for chat history persistence.
    """
    context_store = DialogContextStore(dialog_dir)
    session_context = context_store.load_context(session_id)

    if new_session:
        context_store.delete(session_id)
        session_context = SessionContext(session_id)

    visio_tools = VisioTools(
        session_id=session_id,
        dialog_dir=dialog_dir,
        auto_restore=True,
        record_context=True,
    )
    if new_session:
        try:
            visio_tools.reset_session()
        except Exception:
            pass

    prompt_tools = PromptTools(template_dir=template_dir)
    prompt_tools.set_model(model)

    template_manager = TemplateManager(template_dir)
    library_stats = template_manager.get_library_stats()

    session_context = context_store.load_context(session_id)

    if use_dynamic_instructions:
        instruction_builder = get_instruction_builder()
        is_first_message = len(session_context.operation_history) == 0
        instructions = instruction_builder.build_adaptive_instructions(
            session_context=session_context,
            library_stats=library_stats,
            is_first_message=is_first_message,
        )
    else:
        templates = template_manager.list_templates()
        template_list_preview = (
            "\n".join(
                f"  - {t['name']} ({t['filename']}): {t.get('description', '')[:50]}"
                for t in templates[:10]
            )
            if templates
            else "  - No templates available yet"
        )
        if len(templates) > 10:
            template_list_preview += f"\n  ... plus {len(templates) - 10} more templates"

        instruction_loader = get_instruction_loader()
        instructions = instruction_loader.build_instructions(
            profile=instruction_profile,
            include_chinese=True,
            include_workflows=True,
            include_prompt_gen=True,
            library_stats=library_stats,
            template_list_preview=template_list_preview,
        )

    all_tools = get_agent_tools(visio_tools, prompt_tools)

    agent = Agent(
        name="Visio Assistant",
        model=model,
        instructions=instructions,
        tools=all_tools,
        markdown=True,
        db=db,
        add_history_to_context=True,
        num_history_runs=10,
    )

    agent.visio_tools = visio_tools
    agent.prompt_tools = prompt_tools
    agent.template_manager = template_manager
    agent.session_context = session_context
    agent.context_store = context_store

    return agent
