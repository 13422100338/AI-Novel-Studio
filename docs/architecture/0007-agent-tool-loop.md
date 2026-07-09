# ADR 0007: Read-only tool retrieval and evidence trace

Phase 7 adds a bounded read-only tool retrieval workflow for plot discussion and revision planning. It is an Agent-ready foundation, not the full future Agents mode. It does not give models direct write access to chapters, memory, canon, clues, Briefs, style rules, settings, exports, or API keys.

## Decision

Use a provider-neutral JSON tool loop first. The model must return either a `tool` action with explicit read-only retrieval calls or a `final` action with a reviewable answer. Application code validates the JSON, checks tool names and required arguments, enforces budgets, executes only registered read-only tools, and persists every turn/tool call in SQLite.

Native provider function calling can be added later behind the same `AgentModelPort` interface. Phase 7 does not depend on native tool support; a strict-JSON-capable OpenAI-compatible model is enough. Multi-agent planning, autonomous task queues, and writer/reviewer/memory-maintainer collaboration are explicitly deferred to a later major Agents version.

## Boundaries

- Retrieval tools are read-only.
- Tool results carry source type, source id, source revision, source hash, and omission reasons when content is truncated.
- Retrieval runs have max iteration, max tool call, max tool result character, and output-token limits.
- Model outputs are untrusted until validated by deterministic code.
- The model may advise, explain, or propose a plan, but it may not mutate project state.

## Relationship to other phases

- Phase 5 remains responsible for prose generation and accepting drafts.
- Phase 6 remains responsible for audit, repair proposals, and provenance.
- Phase 7 only helps the discussion/planning surface retrieve evidence from existing project memory and show a trace of what was consulted.
- Full Agents mode remains a future major-version concern, built on top of this read-only retrieval foundation.

## Persistence

Schema v5 adds `agent_runs`, `agent_turns`, and `agent_tool_calls`. These records are trace logs for reviewability, not manuscript content stores.
