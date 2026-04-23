# Agno Refactor Plan Batch A: Foundation

## English

## Why This Batch Exists

This batch is the necessary first half of the refactor. It reduces chaos before architecture migration starts. Without this batch, the later `visio_core` and MCP work will inherit:

- a noisy repository boundary,
- an oversized LLM-facing tool surface,
- hidden session complexity,
- low-trust template assets,
- and weak regression protection.

This batch should be completed before the platform migration batch begins.

## Batch Goal

Stabilize the current agno-based project while preserving the closed-loop workflow and preparing a safer migration path.

## Active Roles

- **Master agent**: holds the roadmap, acceptance gates, and context summaries.
- **Phase 1 subagent**: hygiene and boundary cleanup.
- **Phase 2 subagent**: tool-surface consolidation.
- **Phase 3 subagent**: library pruning and trust rebuilding.
- **Reviewer/test agent**: validates each phase before the next one starts.

Only one implementation subagent may actively edit code or assets at a time.

## Scope

This batch covers three execution phases:

1. Foundation and hygiene
2. Tool-surface consolidation
3. Library pruning and watermark cleanup

## Phase 1: Foundation And Hygiene

### Objective

Remove avoidable repo noise and unsafe state coupling without changing the core architecture yet.

### Primary Focus Areas

- `my_os.py`
- `.gitignore`
- runtime artifacts and generated files
- state folders such as dialog, logs, temporary outputs, and local database artifacts

### Required Actions

1. Remove or ignore checked-in runtime artifacts and temporary outputs.
2. Extract secrets from `my_os.py` into environment-based configuration.
3. Clarify which files are source, which files are runtime state, and which files are disposable outputs.
4. Keep agno bootstrapping intact while improving the repository boundary.
5. Create the initial regression-test skeleton early, even if coverage is still small.

### Acceptance Criteria

- no hard-coded secret remains in the main entry path;
- runtime and output artifacts are moved behind ignore rules or clear state boundaries;
- the agno entry path still boots or imports cleanly;
- an initial `tests/` structure exists for the highest-risk flows;
- the master agent writes a short checkpoint summary.

## Phase 2: Tool-Surface Consolidation

### Objective

Reduce the current model-facing tool surface into a smaller, clearer, more idempotent contract without losing the core workflow.

### Primary Focus Areas

- `visio_system/agents/visio_agent.py`
- `visio_system/tools/visio_tools.py`
- `visio_system/tools/prompt_tools.py`
- prompt-facing workflows that currently depend on many small tool calls

### Required Actions

1. Collapse overlapping shape, text, style, connector, and removal operations.
2. Replace skip-prone multi-step template-analysis calls with an atomic analysis contract.
3. Remove diagnostics and session-management helpers from the LLM-facing surface when they do not belong there.
4. Keep idempotent operations as the preferred path.
5. Preserve compatibility with the current agno-based runtime while the new contract is being introduced.

### Acceptance Criteria

- the exposed tool list is materially smaller and easier to reason about;
- the closed-loop edit path still exists;
- the template-analysis workflow is bundled or strongly simplified;
- duplicate tool intent is eliminated or clearly deprecated;
- focused regression tests cover the consolidated path;
- the master agent records the final contract for downstream phases.

## Phase 3: Library Pruning And Watermark Cleanup

### Objective

Make the template and stencil assets trustworthy enough for recommendation and editing workflows.

### Primary Focus Areas

- template and stencil libraries
- generated indexes
- recommendation quality and performance
- watermark detection and low-quality asset filtering

### Required Actions

1. Detect and remove watermarked or structurally useless templates.
2. Deduplicate low-value stencil assets where practical.
3. Preserve the lite-plus-full index strategy because it supports fast recommendation without losing depth.
4. Regenerate indexes after cleanup.
5. Add tests or verification flows for recommendation correctness and baseline performance.

### Acceptance Criteria

- the asset set is smaller, cleaner, and easier to trust;
- recommendation still works after pruning;
- low-quality or watermarked assets are filtered out in a reproducible way;
- the two-tier index design remains intact;
- the master agent writes a batch checkpoint summary for Batch B.

## Testing Requirements For Batch A

By the end of this batch, the following must exist in at least focused regression form:

- a save and reload validation path;
- an idempotent shape update test;
- an idempotent connector update test;
- a grouped-shape analysis regression test or fixture;
- a template recommendation verification path after pruning.

## Output Requirements

Keep all staged outputs, notes, and migration artifacts for this batch under `refine/`.

At minimum, the batch should leave behind:

- a checkpoint summary,
- test additions or updates,
- the current tool contract summary,
- and the list of known risks that Batch B must handle.

## Stop Conditions

Do not start Batch B until all of the following are true:

- the repository boundary is cleaner;
- the tool surface is reduced;
- early regression tests exist;
- the library cleanup decisions are recorded;
- the master agent has emitted a concise handoff summary.
