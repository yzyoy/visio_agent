# Agno Refactor Orchestration Analysis

## Executive Judgment

The refactor direction in `refine/CORE_CAPABILITIES.md` and `refine/PROJECT_REFACTOR_ROADMAP.md` is sound, but the execution shape needs one adjustment: do not run five long-lived coding agents in parallel against the same mutable codebase.

That approach is not the best fit for this repository because the project is still centered on one agno-powered runtime, one large combined tool surface, multiple hidden state layers, and almost no automated regression coverage. A better approach is:

1. one master agent for architecture, sequencing, and acceptance gates;
2. one active implementation agent for the current phase;
3. one short-lived reviewer or test agent at checkpoints.

This keeps the project inside the agno framework while reducing context drift, merge conflicts, and repeated rediscovery of the same constraints.

## Real Constraints From The Current Codebase

### 1. Agno is the current application shell, not a removable wrapper

The current runtime is anchored in `my_os.py`, which directly creates:

- `OpenAIChat`
- `SqliteDb`
- `AgentOS`
- the `visio_agent`
- preview API mounting and static file serving

This means the refactor should preserve agno as the orchestration layer during migration. Replacing it too early would increase risk and break the session model that the roadmap explicitly wants to keep.

### 2. The current agent exposes too much tool surface to the model

The active agent is built in `visio_system/agents/visio_agent.py` and combines:

- `get_visio_tools(...)` from `visio_system/tools/visio_tools.py`
- `get_prompt_tools(...)` from `visio_system/tools/prompt_tools.py`

Today that means roughly 60 LLM-visible tools, including overlapping operations:

- non-idempotent vs idempotent shape creation
- multiple text update variants
- duplicate connector operations
- six-step template analysis split across many calls
- diagnostics and session tools that should not be model-facing

Because of this, more parallel agents do not create more clarity. They mostly multiply ambiguity.

### 3. Session state currently exists in more than one place

The project uses both:

- agno chat/session persistence through `SqliteDb`
- project-level dialog/session state in `visio_system/context/session_context.py`
- live mutable state inside `VisioTools`

This is a major context and coordination constraint. Two or more implementation agents working in parallel can easily reason from different snapshots of the same document lifecycle.

### 4. Some core behavior depends on import-time side effects

`visio_system/__init__.py` applies patches from `visio_system/patches/` implicitly. The roadmap is right to make this explicit later, but until that happens, import order matters. This makes broad parallel refactors more fragile than they look.

### 5. The safety net is weak right now

The roadmap assumes a phased migration, but the repo currently has little automated regression protection. That makes the following scenarios especially important:

- open -> edit -> save -> reload
- connector persistence after save
- idempotent shape and connector upsert behavior
- recursive grouped-shape analysis
- template recommendation correctness after library pruning

This is why tests should be introduced earlier in execution, not only at the last cleanup step.

## Model Capability Guidance

### Master agent

Use the strongest available reasoning model with a large context window for the master agent. Its job is not bulk editing. Its job is to:

- maintain architectural invariants;
- compress context between phases;
- decide when a phase is truly complete;
- prevent drift away from agno;
- reconcile roadmap intent with code reality.

### Implementation agent

Use a strong coding model for the current phase. It does not need full-repository context all the time. It needs:

- the relevant section of the roadmap;
- the accepted contract for the phase;
- the touched files and tests;
- the last checkpoint summary from the master agent.

### Reviewer/test agent

Use a medium-to-strong model for checkpoint review, test planning, and focused regression checks. This agent should be ephemeral and only run after implementation milestones.

### Phase difficulty by capability demand

- **Phase 0-1**: medium-high reasoning is enough if the contracts are already agreed.
- **Phase 2**: medium-high reasoning plus patience for data cleanup.
- **Phase 3-4**: highest reasoning tier recommended, because these phases change architecture boundaries and contracts.
- **Phase 5**: medium reasoning is usually enough once the MCP surface and workflow are stable.

## Context-Window Guidance

### What is reasonable

The roadmap is compatible with long-context agent execution, but only if context is layered and compressed.

Reasonable context per phase:

- the two refine documents;
- a short checkpoint summary from the previous phase;
- only the files relevant to the current phase;
- explicit acceptance criteria;
- current failing tests or validation targets.

### What is not reasonable

It is not efficient to give every subagent all of the following at once:

- the full roadmap
- the full capability document
- the entire diary history
- the full tool implementation
- the full prompt system
- the full library index

That wastes context on repeated orientation instead of execution.

### Best context-compression pattern

After every phase, the master agent should create a concise handoff containing:

1. architectural decisions locked in;
2. files changed and why;
3. test status;
4. known risks that remain;
5. the exact entry criteria for the next phase.

This is the main reason a master agent is valuable.

## Recommended Agent Topology

### Recommended

#### Master agent

Owns:

- roadmap interpretation
- phase boundaries
- agno compatibility rules
- acceptance criteria
- context compression
- final merge readiness

#### One active phase implementation agent

Owns:

- coding for the current phase only
- updating or adding tests for the current phase
- producing a short phase completion report

#### One checkpoint reviewer/test agent

Owns:

- verifying phase acceptance criteria
- checking for regressions
- identifying architectural drift
- recommending optimizations based on test results

### Optional extra agent

Only Phase 2 may justify one extra worker for data/library pruning, because it is relatively separable from the architecture carve-out. Even then, keep it scoped and temporary.

## Patterns To Avoid

Avoid these patterns if the goal is the best refactor outcome:

1. Five concurrent phase agents all editing code at once.
2. A permanent prompt agent, core agent, MCP agent, and testing agent all sharing the same mutable branch simultaneously.
3. Letting implementation agents redefine the target MCP contract independently.
4. Delaying real tests until every phase is already complete.
5. Treating MCP migration as a big-bang replacement of agno rather than a migration path that remains under agno.

## Recommended Execution Split

The roadmap should be executed in two batches because the architectural boundary is real:

### Batch 1: Foundation

Phases 0-2

Purpose:

- clean the repo and state boundary
- shrink and clarify the tool surface
- prune and trust the template/stencil assets
- add early regression tests

### Batch 2: Platform Migration

Phases 3-5

Purpose:

- carve `visio_core` out of `visio_system`
- add the MCP layer
- formalize the skill layer
- keep agno as the application and memory shell

This split is justified because Batch 1 reduces ambiguity, while Batch 2 changes architecture.

## Final Recommendation

Yes, the refactor plan is reasonable.

No, five parallel building agents are not the best way to execute it.

For the best result:

- keep agno as the governing framework;
- use one master agent plus one active builder;
- introduce tests earlier;
- split the execution into two batches;
- use reviewer/test agents only at checkpoints;
- keep all orchestration artifacts and staged outputs under `refine/` during the migration.
