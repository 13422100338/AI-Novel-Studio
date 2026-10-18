# ADR 0024: Freeze Harness selection, approval, orchestration, and memory repair contracts

## Status

Accepted

## Date

2026-08-26

## Context

The Harness design requires one manuscript authority, one run-orchestration authority, author
approval before formal writes, and deterministic validation of model output. The current repository
has most of the required boundaries, but four seams are not yet safe to connect end to end:

- the Web editor reports ProseMirror `from` / `to` positions and selected plain text, while the
  Harness currently locates that text with `content.count(...)` and applies it with
  `content.replace(..., 1)`;
- an `ApprovalRequest` can become `APPROVED` or `REJECTED` without the owning Harness run being
  advanced from `WAITING_APPROVAL` according to the actual commit outcome;
- QML ordinary chat uses the provider-neutral JSON tool loop, but that path creates legacy
  `agent_runs` records and builds part of its timeline from local request IDs instead of making
  Harness run events the single operational truth;
- the existing memory workspace already exposes useful review DTOs and single-record CAS commands,
  but its legacy surfaces also include chapter-scoped loading, bulk promotion, composite records,
  and domains that must not be collapsed into one QML review list.

This ADR freezes the public contracts that the repair tickets must implement. It is subordinate to
the domain and ownership rules in:

- `docs/harness/agent-harness-design-v0.3.md`;
- `docs/harness/agent-implementation-backend-contract-v0.1.md`;
- `docs/frontend/interface_contracts.md`.

ADR 0007 remains the basis for the provider-neutral JSON tool loop. ADR 0023 remains the boundary
that keeps Occurrence and Participant Link review separate from the existing memory workspace.

## Decision

### 1. Selection Patch

#### Ownership

The Web/Editor layer is the only owner of converting a ProseMirror selection into a verifiable
Markdown patch. It has both the structured editor state and the deterministic Markdown serializer,
so no Python or backend component may attempt to reinterpret a ProseMirror document position as a
Markdown offset.

The resulting patch is an untrusted candidate, not a formal-manuscript write command.

#### Frozen patch identity

A Selection Patch must bind all of the following:

- `schema_version`, whose only accepted value for this contract is `selection-patch-v1`;
- `chapter_id`;
- `base_revision`;
- `base_source_hash`, defined as the lowercase SHA-256 of the exact UTF-8 encoded formal Markdown
  source;
- the original selection's exact identity and half-open range in the serialized base Markdown;
- exact identities and half-open ranges for the Markdown anchors immediately before and after the
  selection, with an explicit empty-boundary representation when the selection touches the start or
  end of the document;
- a stable replacement candidate ID and the lowercase SHA-256 of the exact replacement Markdown;
- the lowercase SHA-256 of the full Markdown result produced by replaying the patch.

`schema_version` participates in validation and deterministic serialization. An unknown version is
rejected, and a semantic or encoding change requires a new version instead of silently changing
`selection-patch-v1`.

Markdown ranges use Unicode code-point offsets and half-open `[start, end)` semantics. The patch
must carry enough exact text or content hashes for the backend to verify the selected span and both
anchors without searching for a merely similar occurrence.

The only position identity is:

```text
base_revision + base_source_hash + Markdown selection [start, end)
```

The before/after anchors are exact-verification and diagnostic evidence only. They must never be
used after source drift to search for, relocate, rebase, or fuzzily repair a selection. Any base
revision, base source hash, selection range, selected-span identity, or anchor mismatch is `STALE`.

Anchor lengths, selected-span payload limits, and total patch payload limits are bounded engineering
constants owned by H-SEL1 and versioned with the schema. Their values must not drift without a
schema-version change. Anchors must not expand into an unbounded copy of the chapter or otherwise
amplify formal manuscript content in the patch payload.

The replacement candidate ID must identify the immutable draft or artifact reviewed by the author.
A UI-local row number, current selection, displayed preview, or model response index is not a
replacement identity.

#### Backend replay and commit

Before a Selection Patch can become a formal `ChangeSet` commit, the backend must:

1. read the exact current formal Markdown for `chapter_id`;
2. compare both `base_revision` and `base_source_hash` with that formal source;
3. validate every Markdown range, the selected span identity, and the before/after anchor
   identities;
4. resolve the immutable replacement candidate and verify its content hash;
5. replay the splice against the exact base Markdown and verify the declared full-result hash;
6. run the complete validation again at the transactional commit boundary;
7. submit only the replayed result through the canonical ChangeSet and chapter-revision boundary.

Revision or hash drift, invalid ranges, anchor mismatch, replacement identity mismatch, or replay
mismatch is a stale conflict. It is never repaired by searching for another occurrence.

The following are expressly forbidden:

- treating ProseMirror `from` / `to` as Markdown character offsets;
- using `content.count`, `str.replace`, first-match replacement, or selected-text uniqueness as
  authoritative location;
- trusting a client-computed full result without replaying the patch;
- allowing the client to submit AI-generated formal chapter content directly;
- bypassing ChangeSet review, author approval, or backend CAS.

The existing manual editor-save path remains a separate author-editing workflow. This decision
forbids direct formal writes from the Agent selection-approval path; it does not turn ordinary
author typing into an Agent ChangeSet.

### 2. Approval terminal semantics

`ApprovalStatus` records only the author's decision:

```text
PENDING -> APPROVED | REJECTED
```

It does not record whether a backend commit succeeded. Commit outcome and run stage are separate
facts.

Every resolved approval must leave `WAITING_APPROVAL` before the resolver returns or recovery
finishes replaying the resolution. The frozen terminal mapping is:

| Author decision and commit fact | Harness run stage | Result disposition |
|---|---|---|
| Approved and every ChangeSet operation is `APPLIED` | `COMPLETED` | `APPLIED` |
| Approved but revision/hash/replay CAS is stale | `STALE` | `STALE` |
| Approved but any ordinary validation, persistence, or commit failure occurs | `FAILED` | `FAILED` |
| User discards the candidate | `COMPLETED` | `DISCARDED` |

`DISCARDED` is a result disposition, not a new `RunStage`. Discard resolves the approval as
`REJECTED`, performs no formal commit, records the discard, and closes the run successfully as a
completed user workflow.

A ChangeSet is successful only when every intended operation is durably reported `APPLIED`.
Partial, missing, `READY`, or `FAILED` outcomes cannot produce `COMPLETED + APPLIED`. Typed
revision/hash/patch conflicts map to `STALE`; all other commit failures map to `FAILED`.

The event log and UI projection must preserve the distinction among:

- the author's approval decision;
- the deterministic commit result;
- the terminal Harness run stage;
- the user-facing disposition (`APPLIED`, `DISCARDED`, `STALE`, or `FAILED`).

An approval that is already resolved must not be resolved a second time. A persisted resolved
approval whose run is still `WAITING_APPROVAL` is an inconsistent recovery state, not a valid steady
state; recovery must use durable idempotency and commit evidence to finalize it.

### 3. Single orchestration for QML ordinary chat

All QML ordinary chat must create and advance a Harness run. The authoritative operational history
is:

```text
Harness AgentRun
-> immutable AgentRunEvent sequence
-> model-request and tool-call events
-> Harness projections
-> QML timeline
```

QML-local request IDs may be correlation IDs, but they are not run identity or run status. QML must
not synthesize authoritative tool calls, completion, failure, or approval state from timers, chat
text, or local collections.

The first unification implementation reuses the existing provider-neutral JSON tool-loop algorithm:

```json
{"action":"tool","tool_calls":[{"tool_name":"...","arguments":{}}]}
```

or:

```json
{"action":"final","final_answer":"..."}
```

The deterministic application layer continues to validate the JSON, tool names, arguments,
permissions, budgets, duplicate calls, and results. Native provider tool calling is not introduced
in this repair. Provider-specific tool protocols may only be added later behind the same stable
Harness contract.

H-UNIFY1 uses this authoritative production tool composition:

```text
harness.core_tools.register_core_tools
-> Harness ToolRegistry
-> PermissionGateway
-> harness.tool_executor.ToolExecutor
-> CoreToolService
-> stable Backend application facades
```

Every new QML Harness tool call must pass through the frozen Harness registry, permission gateway,
executor, and run-event path. Tool implementations do not directly compose or access Repository or
SQLite objects.

The model autonomously decides whether and which registered tool to call from the tool catalog.
Keyword routing, keyword-based tool preselection, and hard-coded user-command dispatch to a tool are
forbidden. Deterministic policy may still require a tool for a declared task class or reject an
unsafe call; that is a permission/completeness gate, not keyword routing.

`application.agent_task_service.AgentTaskService`,
`application.agent_loop_service.AgentLoopService`, and
`application.agent_tool_providers.build_project_agent_registry` may be consulted only for the
provider-neutral JSON behavior and compatibility tool semantics. They are not persistence,
execution, registry-composition, or orchestration authorities for a new QML Harness run.

The legacy `agent_runs`, `agent_turns`, and `agent_tool_calls` data remains readable for
compatibility. After unification, QML ordinary chat creates no new rows in those legacy tables.
The JSON-loop behavior is reused under Harness run/event/tool persistence rather than continuing a
second run ledger.

`HarnessRunEngine` is the sole owner of ordinary-chat model iterations, tool calls, retry/failure,
cancel, and completion. The QML bridge remains a presentation adapter and command entrypoint.

### 4. Memory MVP for QML

The first QML pending-memory surface reuses the existing `MemoryWorkspaceRecord`. It does not create
a second candidate DTO, memory table, or review state machine.

Its frozen behavior is:

- the list is project-wide, not filtered to records before the active chapter;
- only pending `REVIEW` candidates supported by the existing memory review contract are shown;
- each displayed item has a stable `MemoryWorkspaceRecord.id`;
- approval targets exactly one displayed record and sends that stable ID with
  `expected_revision=record.revision`;
- the backend reloads and checks the current record, performs the approval in its application
  transaction, and returns the refreshed record;
- stale identity or revision rejects the approval and refreshes the projection;
- no item is automatically approved, and the QML MVP does not call `promote_all`;
- an aggregate legacy record is excluded unless its stable identity, revision, and exact
  transactional effect set satisfy this single-record contract.

The existing `__all__` project-load sentinel is an application/controller implementation detail.
QML must neither send nor observe it. A later explicit project-wide facade may wrap that internal
mechanism, but this ADR does not freeze a new API.

Rejection must not be simulated by deleting a candidate. If an explicit reject action is later
required, it needs a separately frozen backend review-status transition with provenance. Until that
exists, QML may omit rejection rather than physically delete or hide data as if it had been
rejected.

Occurrence, Occurrence source ranges, `SubjectOccurrenceLink`, and link source ranges do not appear
in this review list. They have separate identity, lifecycle, and multi-row consistency contracts and
require a separate review surface.

Models may create only validated candidates with `Authority.MODEL_EXTRACTED` and
`ReviewStatus.REVIEW`. A model response cannot set `APPROVED`, `LOCKED`, or another formal status.
Promotion to formal state requires an explicit author action and a backend transaction after source,
identity, and revision validation.

## Authoritative existing entrypoints

The repair tickets extend or route through these current symbols. They must not introduce
near-duplicate authorities.

### Selection and formal manuscript

- `ui_qml.editor_web.editor-core.buildSelectionReference` and
  `ui_qml.editor_web.editor.NovelEditor` are the current Web selection/serialization owners and are
  the place to replace the C1 reference with the D1 Markdown Patch contract.
- `ui_qml.bridge.editor_bridge.EditorBridge.selectionReferenceChanged` and
  `ui_qml.bridge.models.selection_reference.parse_selection_reference` are the untrusted bridge
  validation boundary.
- `infrastructure.storage.chapter_repository.ChapterRepository.read_content_exact` is the exact
  formal Markdown read.
- `application.changeset_service.ChangeSetService.build` / `commit` are the ChangeSet facade.
- `application.chapter_revision_service.ChapterRevisionService.submit_revision` is the canonical
  formal chapter revision write and must enforce the repaired revision/hash CAS contract.
- `application.formal_manuscript_evidence_service.FormalManuscriptEvidenceService.hydrate` remains
  the exact formal-evidence retrieval entry; it is not a ProseMirror-to-Markdown mapper.

### Approval and terminal run state

- `harness.approval_service.ApprovalService.request_approval` / `resolve_approval` own the author
  decision lifecycle.
- `harness.approval_resolver.ApprovalResolver.resolve_and_commit` owns resolution-to-commit outcome
  coordination.
- `application.changeset_service.ChangeSetService.commit` and `OperationStatus` own operation
  results.
- `harness.run_engine.HarnessRunEngine`, `harness.event_store.HarnessEventStore`,
  `harness.run_state.RunStage`, and `harness.completion_check.CompletionChecker` own run transitions
  and deterministic completion consistency.

### QML ordinary chat and tools

- `harness.run_engine.HarnessRunEngine` and Harness `AgentRunEvent` persistence are the only new-run
  truth.
- `harness.core_tools.register_core_tools` registers the versioned resident definitions into
  `harness.tool_registry.ToolRegistry`; that Harness registry is the production catalog.
- `harness.core_tools.CoreToolService` is the production core-tool facade over stable Backend
  application services.
- `harness.permission_gateway.PermissionGateway` and
  `harness.tool_executor.ToolExecutor` are the mandatory permission and execution path for every
  new QML Harness tool call.
- Tool implementations must stay behind these Harness and Backend application boundaries and must
  not directly access Repository or SQLite.
- `application.agent_task_service.AgentTaskService`,
  `application.agent_loop_service.AgentLoopService`, and
  `application.agent_tool_providers.build_project_agent_registry` are legacy references for
  provider-neutral JSON behavior and compatibility tool semantics only. They are not new-run
  persistence, execution, registry-composition, or orchestration entrypoints.
- `ui_qml.bridge.harness_agent_bridge.HarnessAgentPort`,
  `HarnessAgentCoordinator`, and `HarnessAgentTimelineController` remain presentation adapters and
  command/projection boundaries.

### Memory review

- `application.memory_workspace_service.MemoryWorkspaceRecord` is the QML review DTO.
- `application.memory_workspace_service.MemoryWorkspaceService.promote` is the single-record,
  explicit-approval application entry and revision gate.
- `application.project_memory_workspace_gateway.ProjectMemoryWorkspaceGateway` is the adapter for
  project-wide loading and transactional promotion.
- `application.memory_analysis_service.MemoryCandidateBundle` and
  `application.memory_candidate_ingest.MemoryCandidateIngestService.ingest` are the untrusted
  model-candidate validation and REVIEW-only ingest boundary.

## Alternatives Considered

### Convert ProseMirror positions in Python or the backend

Rejected. ProseMirror positions describe its document tree, not serialized Markdown. Reconstructing
that mapping outside the Web editor creates a second serializer and cannot be made authoritative by
renaming the offsets.

### Locate selected text by uniqueness or first match

Rejected. Duplicate prose, Markdown structure, normalization, and concurrent edits make
`content.count` and first-match replacement ambiguous. Exact Markdown ranges, source identity,
anchors, and replay are required.

### Let the Web client submit the full formal chapter after approval

Rejected. It trusts a mutable client snapshot, bypasses backend replay, and turns the presentation
layer into a manuscript commit authority.

### Treat `ApprovalStatus.APPROVED` as commit success

Rejected. Approval can precede stale detection or a persistence failure. Author intent and durable
commit outcome are different facts.

### Keep QML chat on legacy `agent_runs`

Rejected. A second run ledger makes cancellation, tools, recovery, status, and diagnostics
disagree with Harness projections.

### Promote the repository-bound legacy Agent registry into Harness

Rejected. `build_project_agent_registry` directly composes repository-backed legacy tools. Making
it the H-UNIFY1 production registry would preserve a second execution/composition authority and
allow the Tool layer to bypass stable Backend application facades.

### Introduce native provider tool calling during unification

Rejected. It expands the repair into provider-specific behavior before the single Harness truth is
established. The existing provider-neutral JSON loop already provides a deterministic first
contract.

### Route tools from user-message keywords

Rejected. It prevents model-driven tool choice, is brittle across natural-language phrasing, and
creates hidden behavior outside the tool loop and permission gateway.

### Create a new QML memory DTO or pending-memory table

Rejected. `MemoryWorkspaceRecord` and the existing backend repositories already carry stable source,
authority, review, and revision data. A parallel store would create a second memory authority.

### Auto-promote, bulk-promote, delete-to-reject, or mix Occurrences into the same list

Rejected. These options erase per-record author intent, weaken CAS/provenance, or combine domains
with different transactional and lifecycle rules.

## Consequences

- H-SEL1 must replace the current selected-text search/replace path with a Web-produced Markdown
  Patch and add backend revision/hash replay validation before formal commit.
- The Web editor gains responsibility for deterministic Markdown range/anchor construction, while
  the backend remains responsible for distrust, replay, CAS, approval, and formal writes.
- H-APPR1 must classify commit results and transition the run on every approval-resolution path;
  UI code can no longer infer “applied” from the approval boolean.
- H-UNIFY1 must separate the reusable JSON-loop algorithm from legacy `AgentRepository`
  persistence, compose tools through the Harness registry/gateway/executor/CoreToolService path,
  and emit Harness model/tool events instead.
- Historical legacy Agent records remain available, but their continued existence does not grant
  them orchestration authority for new QML work.
- The QML memory MVP is intentionally narrower than legacy memory UI capabilities: one project-wide
  pending list and one explicit CAS approval at a time.
- Existing bulk promotion and composite memory helpers may remain for compatibility, but they are
  not QML MVP entrypoints and do not weaken this contract.
- Occurrence and Participant Link review remains separate work.

## Non-goals

- Implementing any production code, test, schema, migration, or data backfill in this ticket.
- Changing the backend worktree board or any ticket ownership.
- Defining a native provider tool-calling protocol.
- Migrating or deleting historical `agent_runs`, `agent_turns`, or `agent_tool_calls`.
- Redesigning the ordinary manual editor-save workflow.
- Defining a general multi-document patch format or arbitrary cross-chapter patch.
- Adding automatic memory approval, bulk QML approval, or delete-based rejection.
- Adding Occurrence or Participant Link review to the memory workspace.
- Freezing the later natural-language knowledge-operation UI beyond its dependency on these
  selection, approval, orchestration, and memory boundaries.

## Follow-up dependency order

Implementation must proceed in this order:

```text
H-SEL1
-> H-APPR1
-> H-UNIFY1
-> H-STATUS1
-> MEM-QML1
-> MEM-BUILD1
-> H-KNOW1
-> E2
```

- `H-SEL1` establishes verifiable candidate identity and formal-source replay.
- `H-APPR1` can then terminate approved, stale, failed, and discarded outcomes correctly.
- `H-UNIFY1` moves QML ordinary chat and its JSON tool loop under Harness truth.
- `H-STATUS1` projects the now-authoritative run, tool, approval, and terminal facts.
- `MEM-QML1` exposes the bounded project-wide single-record review surface.
- `MEM-BUILD1` connects validated REVIEW-only candidate production to that surface.
- `H-KNOW1` builds natural-language knowledge proposals on the repaired approval and orchestration
  contracts.
- `E2` is the end-to-end gate after every preceding boundary is integrated.
