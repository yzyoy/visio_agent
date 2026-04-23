# Agno Refactor Plan Batch B: Platform Migration

## English

## Why This Batch Exists

This batch is separated from Batch A because it changes architecture boundaries, package responsibilities, and agent-facing contracts. It should only begin after the foundation batch has reduced noise, stabilized contracts, and added early regression protection.

Trying to combine this batch with the cleanup work would overload both model context and change risk.

## Batch Goal

Migrate the project toward the target layered architecture while still keeping agno as the top-level framework and runtime shell.

## Active Roles

- **Master agent**: guards architectural invariants, migration order, and final acceptance.
- **Phase 4 subagent**: core-library carve-out and MCP introduction.
- **Phase 5 subagent**: skill layer, agno-compatible integration, and final workflow hardening.
- **Reviewer/test agent**: validates end-to-end migration quality at each checkpoint.

Only one implementation subagent may actively modify code at a time.

## Scope

This batch covers two execution phases:

4. Core-library carve-out and MCP layer
5. Skill layer and final agno-compatible integration

## Phase 4: Core Library And MCP Migration

### Objective

Separate the pure Python library concerns from the agent-facing layer, then introduce the MCP server as the capability boundary for future orchestration.

### Primary Focus Areas

- `visio_system/` to `visio_core/` migration path
- patch application strategy
- MCP server structure
- tool contracts and error model
- document/session handling boundaries

### Required Actions

1. Carve out a clean `visio_core` layer from the current `visio_system` responsibilities.
2. Keep agent-specific instructions and orchestration logic out of the core library.
3. Make patch application explicit rather than hidden behind import side effects.
4. Introduce the MCP server with a small, capability-oriented tool contract.
5. Preserve idempotent semantics and explicit error codes.
6. Keep agno as the application shell during this migration instead of replacing it.

### Acceptance Criteria

- `visio_core` has a clearer pure-library boundary;
- MCP is introduced as a migration layer with a defined contract;
- patch behavior is explicit and testable;
- the model-facing surface is aligned with the new capability contract;
- core round-trip flows remain testable;
- the master agent records the migration decisions and unresolved risks.

## Phase 5: Skill Layer And Final Integration

### Objective

Move workflow knowledge out of oversized inline instructions and into a reusable skill layer while preserving agno compatibility and the closed-loop editing path.

### Primary Focus Areas

- skill file structure
- workflow checklists
- agno integration path
- MCP usage conventions
- end-to-end validation

### Required Actions

1. Create the Visio skill and its supporting checklists.
2. Encode the canonical workflow: recommend -> analyze -> plan -> edit -> save -> reopen -> verify -> render.
3. Keep the skill aligned with the reduced MCP or tool contract.
4. Ensure agno remains the top-level runtime that benefits from the new structure.
5. Validate the full scenario using the new layered arrangement.

### Acceptance Criteria

- the skill captures the core workflow clearly;
- the save/reopen and idempotency rules are enforced by guidance and tests;
- the agno runtime still works with the migrated structure;
- end-to-end closed-loop validation succeeds;
- the final checkpoint summary describes what is production-ready and what remains transitional.

## Testing Requirements For Batch B

By the end of this batch, the project should have focused coverage or validation for:

- core import boundaries;
- open -> edit -> save -> reopen round-trip;
- connector persistence after save and reload;
- grouped-shape analysis in the new structure;
- MCP contract correctness for the main tool paths;
- skill-driven end-to-end scenario execution.

## Integration Principles

Use these principles throughout Batch B:

1. agno remains the governing shell;
2. MCP is introduced as a capability layer, not a product rewrite;
3. skills describe workflow, not hidden business logic;
4. the core library must be usable independently of agent orchestration;
5. every contract change must be reflected in tests and checkpoint summaries.

## Output Requirements

Keep migration artifacts, staged implementation outputs, and validation summaries under `refine/`.

At minimum, this batch should leave behind:

- the migration checkpoint summary,
- MCP contract notes,
- skill-layer notes,
- final validation results,
- and a clear list of remaining replacement steps for the legacy path.

## Stop Conditions

Do not call the refactor complete until all of the following are true:

- agno still governs the runtime shell;
- the new layered boundaries are understandable and testable;
- the MCP and skill layers are aligned with the reduced capability contract;
- the end-to-end workflow validates successfully;
- the master agent has emitted a final readiness summary.
