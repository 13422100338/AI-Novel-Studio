# Phase 7 Agent Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. In this Codex session, do not dispatch subagents unless the user explicitly asks for subagent or parallel-agent execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded Agent workflow where selected models can explicitly query read-only project memory, chapter context, canon, clues, and audit evidence while discussing plot or planning revisions, without allowing the Agent to mutate manuscript, memory, canon, Briefs, or settings.

**Architecture:** Phase 7 introduces a provider-neutral JSON tool-loop first, then leaves native provider tool calls as an adapter optimization. The Agent loop lives in the application layer, uses a read-only tool registry backed by existing repositories and ContextBuilder-style budgets, records every run/tool call in SQLite, and returns final answers or repair plans only as reviewable text. UI gains an optional Agent mode and an Agent trace panel; existing generation, audit, repair, and memory write paths remain separate.

**Tech Stack:** Python 3.11+, dataclasses, `StrEnum`, SQLite, existing LLM gateway/contract runner, existing storage repositories, PySide6, pytest, ruff, mypy.

## Global Constraints

- Make the smallest correct change.
- Do not rewrite architecture.
- Do not modify user manuscripts, databases, backups, exports, API keys, or secrets during planning.
- During implementation, never silently delete, truncate, or overwrite user content.
- Keep UI, data storage, model calls, and pipeline logic separated.
- Model outputs are untrusted; validate structured outputs before saving them.
- Prefer deterministic program logic over prompt-only solutions.
- Agent tools in Phase 7 are read-only.
- Agent tools cannot write manuscript, memory, canon, clues, Briefs, style rules, model configuration, API keys, or project settings.
- Agent loops must have explicit max-iteration, max-tool-call, max-tool-result-character, and model-token budgets.
- Tool results must carry source IDs, revisions, hashes, and omission reasons where applicable.
- Agent trace records must not include API keys, complete provider response bodies, user real names, private local paths, or large raw manuscripts.
- Phase 7 does not implement autonomous full-book writing or infinite multi-Agent review loops.
- Phase 7 does not replace Phase 5 generation or Phase 6 audit/repair; it can only assist planning, discussion, evidence retrieval, and reviewable recommendations.

---

## Scope Check

Phase 7 is large enough to split into independently testable subsystems:

1. Agent schema and trace persistence.
2. Read-only tool registry and tool result budgets.
3. Provider-neutral JSON tool loop.
4. Agent task service for plot discussion and revision planning.
5. UI integration and trace viewing.
6. Strict verification, docs, and version bump.

Do not implement native provider function calling in the first pass. The first pass must work with any OpenAI-compatible model that can return JSON. Native tool support can be added later behind the same `AgentModelPort` interface.

## File Structure

- Create `src/ai_novel_studio/domain/agent.py`
  - Owns Agent run/tool-call enums and immutable records.
- Modify `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
  - Adds schema v5 tables for Agent run traces.
- Create `src/ai_novel_studio/infrastructure/storage/agent_repository.py`
  - Persists `agent_runs`, `agent_turns`, and `agent_tool_calls`.
- Create `src/ai_novel_studio/application/agent_tools.py`
  - Defines read-only tool request/result contracts and registry.
- Create `src/ai_novel_studio/application/agent_tool_providers.py`
  - Adapts existing chapter, memory, canon, clue, summary, style, and audit repositories into read-only tools.
- Create `src/ai_novel_studio/application/agent_loop_service.py`
  - Runs the bounded JSON tool loop and stores trace events.
- Create `src/ai_novel_studio/application/agent_task_service.py`
  - Provides plot discussion and revision-planning Agent entry points.
- Modify `src/ai_novel_studio/infrastructure/llm/schemas.py`
  - Adds `TaskPurpose.AGENT_ASSISTANT`.
- Modify `src/ai_novel_studio/application/model_tasks.py`
  - Keeps old non-Agent plot chat path intact; Agent mode uses new service.
- Modify `src/ai_novel_studio/ui/panels/plot_chat_panel.py`
  - Adds an Agent-mode toggle and trace button.
- Modify `src/ai_novel_studio/ui/main_window.py`
  - Wires Agent task service and trace window without direct storage access.
- Create `src/ai_novel_studio/ui/pages/agent_trace_window.py`
  - Displays Agent turns, tool calls, budgets, and omissions.
- Modify `src/ai_novel_studio/ui/pages/settings_dialog.py`
  - Adds route override for Agent assistant if needed.
- Create `docs/architecture/0007-agent-tool-loop.md`
  - Documents Phase 7 boundaries and future native-tool adapter path.
- Modify `README.md`, `pyproject.toml`, and `src/ai_novel_studio/__init__.py`
  - Bump to `0.7.0` after successful implementation.

Tests:

- Create `tests/unit/domain/test_agent_records.py`
- Create `tests/integration/storage/test_agent_schema.py`
- Create `tests/integration/storage/test_agent_repository.py`
- Create `tests/unit/application/test_agent_tools.py`
- Create `tests/integration/application/test_agent_tool_providers.py`
- Create `tests/unit/application/test_agent_loop_service.py`
- Create `tests/unit/application/test_agent_task_service.py`
- Modify or add UI tests under `tests/ui/`
- Modify `tests/unit/llm/test_schemas_and_routing.py`
- Modify `tests/test_package_layout.py`

## Data Model

### agent_runs

```text
id TEXT PRIMARY KEY
chapter_id TEXT REFERENCES chapters(id)
purpose TEXT NOT NULL CHECK(purpose IN ('PLOT_DISCUSSION', 'REVISION_PLAN', 'AUDIT_EXPLANATION'))
status TEXT NOT NULL CHECK(status IN ('PREPARING', 'RUNNING', 'WAITING_FOR_MODEL', 'WAITING_FOR_TOOL', 'COMPLETED', 'FAILED', 'CANCELLED'))
model_provider_id TEXT NOT NULL
model_id TEXT NOT NULL
prompt_version TEXT NOT NULL
max_iterations INTEGER NOT NULL CHECK(max_iterations > 0)
max_tool_calls INTEGER NOT NULL CHECK(max_tool_calls >= 0)
max_tool_result_chars INTEGER NOT NULL CHECK(max_tool_result_chars > 0)
used_iterations INTEGER NOT NULL DEFAULT 0 CHECK(used_iterations >= 0)
used_tool_calls INTEGER NOT NULL DEFAULT 0 CHECK(used_tool_calls >= 0)
input_tokens INTEGER CHECK(input_tokens >= 0)
output_tokens INTEGER CHECK(output_tokens >= 0)
cached_input_tokens INTEGER CHECK(cached_input_tokens >= 0)
reasoning_tokens INTEGER CHECK(reasoning_tokens >= 0)
failure_code TEXT
failure_message TEXT
started_at TEXT NOT NULL
updated_at TEXT NOT NULL
completed_at TEXT
```

### agent_turns

```text
id TEXT PRIMARY KEY
run_id TEXT NOT NULL REFERENCES agent_runs(id)
sequence INTEGER NOT NULL CHECK(sequence >= 0)
role TEXT NOT NULL CHECK(role IN ('SYSTEM', 'USER', 'ASSISTANT', 'TOOL'))
content TEXT NOT NULL
content_hash TEXT NOT NULL
omitted INTEGER NOT NULL DEFAULT 0 CHECK(omitted IN (0, 1))
created_at TEXT NOT NULL
UNIQUE(run_id, sequence)
```

### agent_tool_calls

```text
id TEXT PRIMARY KEY
run_id TEXT NOT NULL REFERENCES agent_runs(id)
turn_id TEXT REFERENCES agent_turns(id)
sequence INTEGER NOT NULL CHECK(sequence >= 0)
tool_name TEXT NOT NULL
arguments_json TEXT NOT NULL
status TEXT NOT NULL CHECK(status IN ('REQUESTED', 'VALIDATED', 'EXECUTED', 'REJECTED', 'FAILED', 'OMITTED'))
result_json TEXT NOT NULL DEFAULT '{}'
result_chars INTEGER NOT NULL DEFAULT 0 CHECK(result_chars >= 0)
source_refs_json TEXT NOT NULL DEFAULT '[]'
failure_code TEXT
failure_message TEXT
created_at TEXT NOT NULL
completed_at TEXT
UNIQUE(run_id, sequence)
```

## Agent Tool Contract

All tools use this application-layer contract:

```python
@dataclass(frozen=True, slots=True)
class AgentToolRequest:
    tool_name: AgentToolName
    arguments: Mapping[str, object]
    run_id: str
    chapter_id: str | None
    max_result_chars: int

@dataclass(frozen=True, slots=True)
class AgentSourceRef:
    source_type: str
    source_id: str
    source_revision: int
    source_hash: str

@dataclass(frozen=True, slots=True)
class AgentToolResult:
    tool_name: AgentToolName
    content: str
    source_refs: tuple[AgentSourceRef, ...]
    omitted: tuple[str, ...]
    result_hash: str
```

Allowed Phase 7 tools:

- `READ_CHAPTER_EXCERPT`
  - Arguments: `chapter_id: str`, `max_chars: int`.
  - Returns excerpt, chapter revision, content hash.
- `SEARCH_MEMORY`
  - Arguments: `query: str`, `before_chapter_id: str | None`, `limit: int`.
  - Returns memory document snippets with source IDs and review/status metadata.
- `GET_CHARACTER_STATE`
  - Arguments: `character_id: str`, `before_chapter_id: str | None`.
  - Returns latest timeline events visible before boundary.
- `GET_CHARACTER_KNOWLEDGE`
  - Arguments: `character_id: str`, `before_chapter_id: str | None`.
  - Returns character knowledge state, not reader-only knowledge unless requested by a separate flag.
- `GET_ACTIVE_CLUES`
  - Arguments: `before_chapter_id: str | None`, `limit: int`.
  - Returns active clue ledger records and clue events.
- `GET_CANON_FACTS`
  - Arguments: `query: str | None`, `limit: int`.
  - Returns locked/current canon entries.
- `GET_STYLE_GUIDE`
  - Arguments: `scope_type: str`, `scope_id: str | None`, `limit: int`.
  - Returns applicable style rules and human style samples.
- `GET_AUDIT_FINDINGS`
  - Arguments: `chapter_id: str`, `severity: str | None`, `limit: int`.
  - Returns Phase 6 findings and statuses.

Explicitly forbidden in Phase 7:

- `WRITE_CHAPTER`
- `SAVE_MEMORY`
- `PROMOTE_MEMORY`
- `APPLY_REPAIR`
- `DELETE_RECORD`
- `CHANGE_SETTINGS`
- `EXPORT_MANUSCRIPT`

These names should appear in tests as rejected tool calls if a model asks for them.

## Task 1: Agent Domain Records

**Files:**
- Create: `src/ai_novel_studio/domain/agent.py`
- Test: `tests/unit/domain/test_agent_records.py`

**Interfaces:**
- Produces:
  - `AgentPurpose`
  - `AgentRunStatus`
  - `AgentTurnRole`
  - `AgentToolName`
  - `AgentToolCallStatus`
  - `AgentRun`
  - `AgentTurn`
  - `AgentToolCall`
  - `AgentSourceRef`
  - `AgentToolResult`

- [ ] **Step 1: Write failing tests**

Create tests for stable enum values, immutable records, required IDs/text, non-negative budgets, and forbidden empty source hashes.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/domain/test_agent_records.py -q -p no:cacheprovider
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ai_novel_studio.domain.agent'`.

- [ ] **Step 2: Implement minimal records**

Create immutable dataclasses and validators mirroring `domain/audit.py`. Do not import UI, storage, or LLM modules.

- [ ] **Step 3: Verify green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/domain/test_agent_records.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/domain/agent.py tests/unit/domain/test_agent_records.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/ai_novel_studio/domain/agent.py tests/unit/domain/test_agent_records.py
git commit -m "feat: add agent domain records"
```

## Task 2: Agent Trace Schema v5

**Files:**
- Modify: `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
- Test: `tests/integration/storage/test_agent_schema.py`
- Modify: `tests/integration/storage/test_audit_schema.py`
- Modify: `tests/integration/storage/test_generation_schema.py`

**Interfaces:**
- Consumes Phase 7 enum values from `domain/agent.py`.
- Produces schema v5 tables: `agent_runs`, `agent_turns`, `agent_tool_calls`.

- [ ] **Step 1: Write failing schema tests**

Create a v4 legacy fixture using `_migration_1` through `_migration_4`, then migrate to latest and assert:

```python
assert version == LATEST_SCHEMA_VERSION == 5
assert {"agent_runs", "agent_turns", "agent_tool_calls"} <= tables
assert "agent_runs_chapter" in indexes
assert "agent_tool_calls_run" in indexes
```

Also assert invalid status, negative budget, duplicate `(run_id, sequence)`, and invalid tool status raise `sqlite3.IntegrityError`.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/storage/test_agent_schema.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7schema
```

Expected: FAIL because schema latest is still v4.

- [ ] **Step 2: Implement migration 5**

Bump `LATEST_SCHEMA_VERSION` to `5`, add `_migration_5`, and register it. Do not modify existing tables.

- [ ] **Step 3: Update older latest-schema assertions**

Tests that compare `LATEST_SCHEMA_VERSION == 4` should become `== 5` only where they are checking the latest schema. Tests that specifically check v4 migration history should remain v4-specific.

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/storage/test_agent_schema.py tests/integration/storage/test_audit_schema.py tests/integration/storage/test_generation_schema.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7schema
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/ai_novel_studio/infrastructure/storage/migration_manager.py tests/integration/storage/test_agent_schema.py tests/integration/storage/test_audit_schema.py tests/integration/storage/test_generation_schema.py
git commit -m "feat: add agent trace schema"
```

## Task 3: Agent Repository

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/agent_repository.py`
- Test: `tests/integration/storage/test_agent_repository.py`

**Interfaces:**
- Consumes `AgentRun`, `AgentTurn`, `AgentToolCall`.
- Produces:
  - `AgentRepository.create_run(...) -> AgentRun`
  - `AgentRepository.update_run_status(run_id, status, *, failure_code=None, failure_message=None) -> AgentRun`
  - `AgentRepository.add_turn(run_id, role, content, *, omitted=False) -> AgentTurn`
  - `AgentRepository.add_tool_call(run_id, tool_name, arguments_json, *, turn_id=None) -> AgentToolCall`
  - `AgentRepository.complete_tool_call(call_id, status, result_json, result_chars, source_refs_json, *, failure_code=None, failure_message=None) -> AgentToolCall`
  - `AgentRepository.list_turns(run_id) -> tuple[AgentTurn, ...]`
  - `AgentRepository.list_tool_calls(run_id) -> tuple[AgentToolCall, ...]`

- [ ] **Step 1: Write failing repository tests**

Assert run creation, ordered turns, ordered tool calls, status updates, and hash preservation.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/storage/test_agent_repository.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7repo
```

Expected: FAIL because `agent_repository.py` does not exist.

- [ ] **Step 2: Implement repository**

Follow `AuditRepository` style. Use `new_id()`, `datetime.now(UTC)`, SHA-256 content hashes, and SQLite row mappers.

- [ ] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/storage/test_agent_repository.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7repo
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/infrastructure/storage/agent_repository.py tests/integration/storage/test_agent_repository.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/ai_novel_studio/infrastructure/storage/agent_repository.py tests/integration/storage/test_agent_repository.py
git commit -m "feat: persist agent run traces"
```

## Task 4: Read-Only Agent Tool Registry

**Files:**
- Create: `src/ai_novel_studio/application/agent_tools.py`
- Test: `tests/unit/application/test_agent_tools.py`

**Interfaces:**
- Produces:
  - `AgentToolRequest`
  - `AgentToolExecution`
  - `AgentTool`
  - `AgentToolRegistry`
  - `AgentToolValidationError`
  - `AgentToolBudgetError`

- [ ] **Step 1: Write failing tests**

Tests must prove:

- unknown tool is rejected;
- forbidden write-like tool names are rejected;
- missing required arguments are rejected;
- result content is truncated or omitted according to `max_result_chars`;
- registry returns source refs and omission reasons.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_agent_tools.py -q -p no:cacheprovider
```

Expected: FAIL because `agent_tools.py` does not exist.

- [ ] **Step 2: Implement registry**

Implement a pure application-layer registry with no storage dependencies. Each registered tool is a callable:

```python
class AgentTool(Protocol):
    name: AgentToolName
    required_arguments: tuple[str, ...]
    def execute(self, request: AgentToolRequest) -> AgentToolResult: ...
```

The registry validates tool name, argument presence, and budget before executing.

- [ ] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_agent_tools.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/application/agent_tools.py tests/unit/application/test_agent_tools.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/ai_novel_studio/application/agent_tools.py tests/unit/application/test_agent_tools.py
git commit -m "feat: add read-only agent tool registry"
```

## Task 5: Project Read-Only Tool Providers

**Files:**
- Create: `src/ai_novel_studio/application/agent_tool_providers.py`
- Test: `tests/integration/application/test_agent_tool_providers.py`

**Interfaces:**
- Consumes existing repositories:
  - `ChapterRepository`
  - `SearchRepository`
  - `CharacterMemoryRepository`
  - `NarrativeMemoryRepository`
  - `SummaryRepository`
  - `StyleRepository`
  - `AuditRepository`
- Produces `build_project_agent_registry(...) -> AgentToolRegistry`.

- [ ] **Step 1: Write failing integration tests**

Create a synthetic project with chapters, memory documents, character events, canon/clue/style records, and audit findings. Assert each allowed tool returns bounded, source-referenced content.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/application/test_agent_tool_providers.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7tools
```

Expected: FAIL because `agent_tool_providers.py` does not exist.

- [ ] **Step 2: Implement providers one by one**

Implement in this order:

1. `ReadChapterExcerptTool`
2. `SearchMemoryTool`
3. `GetCharacterStateTool`
4. `GetCharacterKnowledgeTool`
5. `GetActiveCluesTool`
6. `GetCanonFactsTool`
7. `GetStyleGuideTool`
8. `GetAuditFindingsTool`

Every tool must:

- return source IDs, revisions, and hashes;
- respect `max_result_chars`;
- avoid absolute local paths;
- avoid reading deleted chapters unless explicitly requested by a future permission.

- [ ] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/application/test_agent_tool_providers.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7tools
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/application/agent_tool_providers.py tests/integration/application/test_agent_tool_providers.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/ai_novel_studio/application/agent_tool_providers.py tests/integration/application/test_agent_tool_providers.py
git commit -m "feat: expose read-only project tools to agents"
```

## Task 6: Provider-Neutral JSON Agent Loop

**Files:**
- Create: `src/ai_novel_studio/application/agent_loop_service.py`
- Modify: `src/ai_novel_studio/infrastructure/llm/schemas.py`
- Modify: `tests/unit/llm/test_schemas_and_routing.py`
- Test: `tests/unit/application/test_agent_loop_service.py`

**Interfaces:**
- Adds `TaskPurpose.AGENT_ASSISTANT = "agent_assistant"`.
- Produces:
  - `AgentLoopRequest`
  - `AgentLoopResult`
  - `AgentModelPort`
  - `AgentLoopService.run(request) -> AgentLoopResult`

The model response contract for the first implementation is:

```json
{
  "action": "tool",
  "tool_calls": [
    {
      "tool_name": "SEARCH_MEMORY",
      "arguments": {"query": "old letter", "before_chapter_id": "chapter-1", "limit": 5}
    }
  ],
  "assistant_note": "why this tool is needed"
}
```

or:

```json
{
  "action": "final",
  "final_answer": "answer to user",
  "used_sources": [{"source_type": "summary", "source_id": "summary-1"}]
}
```

- [ ] **Step 1: Write failing tests**

Tests must prove:

- the loop can execute a tool request and then produce final answer;
- unknown/forbidden tools are rejected and recorded;
- max iterations stops runaway loops;
- max tool calls stops tool spam;
- invalid JSON fails without executing tools;
- all turns/tool calls are stored through `AgentRepository`;
- no tool result exceeds `max_tool_result_chars`.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_agent_loop_service.py tests/unit/llm/test_schemas_and_routing.py -q -p no:cacheprovider
```

Expected: FAIL because `AgentLoopService` and `TaskPurpose.AGENT_ASSISTANT` do not exist.

- [ ] **Step 2: Add task purpose and routing tests**

Update `TaskPurpose` and route resolution so Agent assistant defaults to the plot route unless an override is configured later.

- [ ] **Step 3: Implement JSON loop**

Use existing `LLMContractRunner`-style validation. The service should:

1. create `agent_run`;
2. add system/user turns;
3. call model through `AgentModelPort.complete_json(...)`;
4. validate `action`;
5. execute allowed tools through `AgentToolRegistry`;
6. append tool result turns;
7. stop on final answer or budget exhaustion;
8. mark run `COMPLETED` or `FAILED`.

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_agent_loop_service.py tests/unit/llm/test_schemas_and_routing.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/application/agent_loop_service.py src/ai_novel_studio/infrastructure/llm/schemas.py tests/unit/application/test_agent_loop_service.py tests/unit/llm/test_schemas_and_routing.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/ai_novel_studio/application/agent_loop_service.py src/ai_novel_studio/infrastructure/llm/schemas.py tests/unit/application/test_agent_loop_service.py tests/unit/llm/test_schemas_and_routing.py
git commit -m "feat: add bounded agent tool loop"
```

## Task 7: Agent Task Service

**Files:**
- Create: `src/ai_novel_studio/application/agent_task_service.py`
- Test: `tests/unit/application/test_agent_task_service.py`

**Interfaces:**
- Consumes `AgentLoopService`.
- Produces:
  - `AgentTaskService.discuss_plot_with_tools(...) -> AgentLoopResult`
  - `AgentTaskService.plan_revision_with_tools(...) -> AgentLoopResult`
  - `AGENT_ASSISTANT_PROMPT_VERSION = "agent-assistant-v1"`

- [ ] **Step 1: Write failing tests**

Tests must assert prompt order:

1. fixed Agent system boundary;
2. current user request;
3. current manuscript excerpt;
4. current chapter requirement;
5. allowed tool catalog;
6. explicit instruction to answer with JSON action contract.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_agent_task_service.py -q -p no:cacheprovider
```

Expected: FAIL because `agent_task_service.py` does not exist.

- [ ] **Step 2: Implement task service**

The prompt must say:

- tools are read-only;
- tool results are evidence, not authority;
- do not claim to have read material unless a tool result provided it;
- do not modify manuscript, memory, canon, clues, Briefs, style, or settings;
- provide final answer as advice or a reviewable plan.

- [ ] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_agent_task_service.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/application/agent_task_service.py tests/unit/application/test_agent_task_service.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/ai_novel_studio/application/agent_task_service.py tests/unit/application/test_agent_task_service.py
git commit -m "feat: add agent task prompts"
```

## Task 8: UI Agent Mode and Trace Window

**Files:**
- Modify: `src/ai_novel_studio/ui/panels/plot_chat_panel.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Create: `src/ai_novel_studio/ui/pages/agent_trace_window.py`
- Test: `tests/ui/test_agent_mode_ui.py`

**Interfaces:**
- Plot chat panel exposes:
  - `agent_mode_enabled() -> bool`
  - `agent_trace_requested = Signal()`
  - existing chat send signal remains unchanged.
- Main window routes plot chat through normal `ModelTaskService` when Agent mode is off, and through `AgentTaskService` when Agent mode is on.

- [ ] **Step 1: Write failing UI tests**

Tests must prove:

- Agent mode toggle exists and defaults off;
- normal plot chat still uses old model coordinator;
- Agent mode sends current manuscript and requirement to Agent runtime;
- trace window opens and displays run status, turns, tool calls, and omissions.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_agent_mode_ui.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7ui
```

Expected: FAIL because Agent UI does not exist.

- [ ] **Step 2: Implement UI widgets**

Keep UI simple:

- a toggle labeled `Agent 模式`;
- a small tooltip explaining read-only tool use;
- a `工具轨迹` button;
- trace window with two tables: turns and tool calls.

- [ ] **Step 3: Wire main window without storage access from widgets**

MainWindow may hold an application service, but widgets must not access repositories or SQLite.

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_agent_mode_ui.py tests/ui/test_auxiliary_pages.py tests/unit/application/test_agent_task_service.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7ui
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/ui/panels/plot_chat_panel.py src/ai_novel_studio/ui/main_window.py src/ai_novel_studio/ui/pages/agent_trace_window.py tests/ui/test_agent_mode_ui.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/ai_novel_studio/ui/panels/plot_chat_panel.py src/ai_novel_studio/ui/main_window.py src/ai_novel_studio/ui/pages/agent_trace_window.py tests/ui/test_agent_mode_ui.py
git commit -m "feat: add agent mode UI and trace viewer"
```

## Task 9: Settings Route and Capability Display

**Files:**
- Modify: `src/ai_novel_studio/ui/pages/settings_dialog.py`
- Modify: `src/ai_novel_studio/infrastructure/llm/schemas.py`
- Modify: `src/ai_novel_studio/infrastructure/llm/config_repository.py`
- Test: `tests/ui/test_phase_3_model_ui.py`
- Test: `tests/unit/llm/test_schemas_and_routing.py`

**Interfaces:**
- Agent assistant route can override default plot route.
- Capability display shows `tools` as supported/unsupported/unknown, but Phase 7 JSON loop does not require native tools.

- [ ] **Step 1: Write failing tests**

Assert settings dialog contains an `Agent 助手（可覆盖）` route combo and saves it as a route override.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_phase_3_model_ui.py tests/unit/llm/test_schemas_and_routing.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7settings
```

Expected: FAIL because no Agent route exists.

- [ ] **Step 2: Implement route override**

Do not require native tool support; just show the capability if known. The JSON tool loop can run on a strict-JSON-capable model.

- [ ] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_phase_3_model_ui.py tests/unit/llm/test_schemas_and_routing.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7settings
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/ui/pages/settings_dialog.py src/ai_novel_studio/infrastructure/llm/config_repository.py src/ai_novel_studio/infrastructure/llm/schemas.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/ai_novel_studio/ui/pages/settings_dialog.py src/ai_novel_studio/infrastructure/llm/config_repository.py src/ai_novel_studio/infrastructure/llm/schemas.py tests/ui/test_phase_3_model_ui.py tests/unit/llm/test_schemas_and_routing.py
git commit -m "feat: add agent model route setting"
```

## Task 10: Documentation and Version 0.7.0

**Files:**
- Create: `docs/architecture/0007-agent-tool-loop.md`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `src/ai_novel_studio/__init__.py`
- Modify: `tests/test_package_layout.py`

**Interfaces:**
- Version becomes `0.7.0`.
- Architecture doc states Phase 7 is read-only Agent retrieval, not autonomous full-book writing.

- [ ] **Step 1: Write/update failing version test**

Update package layout test:

```python
assert ai_novel_studio.__version__ == "0.7.0"
assert metadata["project"]["version"] == ai_novel_studio.__version__
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_package_layout.py::test_phase_seven_package_version_matches_build_metadata -q -p no:cacheprovider
```

Expected: FAIL while version is still `0.6.0`.

- [ ] **Step 2: Write architecture doc**

`docs/architecture/0007-agent-tool-loop.md` must cover:

- JSON tool loop first;
- future native provider tool calls behind same interface;
- read-only tools;
- source refs and hashes;
- budget limits;
- trace persistence;
- no direct storage mutation by models;
- relation to Phase 5 generation and Phase 6 audit/repair.

- [ ] **Step 3: Update version and README**

Set:

```toml
version = "0.7.0"
```

and:

```python
__version__ = "0.7.0"
```

README summary should mention read-only Agent tool retrieval and trace viewing. Do not include the user's real name or local private path.

- [ ] **Step 4: Verify docs and package metadata**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_package_layout.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/ai_novel_studio
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add docs/architecture/0007-agent-tool-loop.md README.md pyproject.toml src/ai_novel_studio/__init__.py tests/test_package_layout.py
git commit -m "docs: document phase 7 agent tool loop"
```

## Task 11: Full Verification

**Files:**
- Test only unless failures require fixes in already-touched Phase 7 files.

- [ ] **Step 1: Run full test suite**

Use a short Windows basetemp path to avoid long-path failures:

```powershell
New-Item -ItemType Directory -Force C:\CodexPytest | Out-Null
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\CodexPytest\phase7full
```

Expected: all tests pass.

- [ ] **Step 2: Run lint and type check**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/ai_novel_studio
```

Expected: PASS.

- [ ] **Step 3: Run privacy scan**

```powershell
rg -n "s[k]-[A-Za-z0-9]|s[k]-proj|api[_-]?k[e]y|C:\\\\Users\\\\" README.md docs src tests pyproject.toml
```

Expected: no sensitive matches in release docs/source. If test fixtures intentionally mention credential field names, verify no plaintext secret is present.

- [ ] **Step 4: Check Git state**

```powershell
git status --short --branch
git log -8 --oneline
```

Expected: clean working tree after final commit.

## Phase 7 Acceptance Criteria

Phase 7 is complete when:

- The app has schema v5 Agent trace tables.
- Agent runs, turns, and tool calls are persisted.
- Agent tools are read-only and reject write-like requests.
- The Agent loop can execute bounded JSON tool calls and produce final answers.
- Every tool result carries source refs, hashes, and omission reasons.
- Budgets stop runaway loops and excessive tool output.
- Plot chat can optionally use Agent mode.
- The user can inspect Agent tool traces.
- Existing non-Agent chat, Brief, prose generation, audit, repair, and strict-mode acceptance still pass tests.
- Version is `0.7.0`.
- Full pytest, ruff, mypy, and privacy scan pass.

## Non-Goals

- No autonomous full-book writing.
- No parallel writer Agents.
- No native provider-specific function calling in the first implementation.
- No automatic manuscript mutation from Agent answers.
- No automatic memory/canon/Brief/style mutation from Agent answers.
- No cloud sync or remote database.
- No new paid model retry loop beyond the existing gateway retry policy.

## Self-Review

- Spec coverage: This plan covers the Phase 7 scope from existing architecture notes: sequential Agent scheduling, frozen/structured memory tools, read-only permissions, and budgets.
- Placeholder scan: No placeholders are intentionally left; native function calling is explicitly a non-goal for this first pass.
- Type consistency: The plan consistently uses `AgentRun`, `AgentTurn`, `AgentToolCall`, `AgentToolRegistry`, `AgentLoopService`, and `TaskPurpose.AGENT_ASSISTANT`.
- Scope check: The plan is large but split into independently testable tasks. If implementation time becomes too high, Tasks 1-6 produce a backend-only Agent MVP, and Tasks 7-10 can follow as UI/release tasks.
