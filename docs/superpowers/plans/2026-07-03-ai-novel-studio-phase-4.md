# AI Novel Studio Phase 4 Memory and Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable, time-bounded memory and context kernel required for million-word novels: layered summaries, character and reader knowledge timelines, typed narrative clues, canon and style ledgers, FTS5 retrieval, deterministic Token budgeting, reviewable Context Manifests, and dependency invalidation.

**Architecture:** Phase 4 adds an idempotent SQLite migration and focused repositories beneath provider-neutral core services. Every memory record carries a stable ID, authority/review state, source chapter/revision/hash, and temporal boundary. `ContextBuilder` selects whole evidence blocks deterministically from repositories, writes a manifest explaining every inclusion/omission, and never calls a model or mutates canon. Model extraction produces review candidates only; promotion and edits remain explicit application operations.

**Tech Stack:** Python 3.11+, SQLite/FTS5, JSON, Markdown, PySide6, pytest, Ruff, mypy, PyInstaller.

## Global constraints

- Existing Phase 1–3 projects must migrate without data loss and migrations must remain idempotent.
- Current-chapter queries exclude facts first established in the current or later chapter unless an explicit inclusive historical query is requested.
- Display chapter numbers and titles are never identity keys; all relationships use stable UUIDs.
- AI-extracted facts, summaries, clues, and style rules begin in `REVIEW` and cannot overwrite locked human records.
- `MISDIRECTION`, `OPEN_QUESTION`, and `ATMOSPHERIC_HINT` remain distinct from factual canon and cannot be auto-repaired as contradictions.
- FTS evidence selection never authorizes deleting unselected manuscript text.
- Required context is never silently truncated. Optional whole blocks may use an explicit summary fallback or be omitted with a recorded reason.
- The user chooses output Token limits; the program computes input budget and never asks the user for a compression ratio.
- Phase 4 does not enable prose generation, Brief freezing, repair, or Agent tool loops.

---

### Task 1: Schema v2 and memory domain records

**Files:**
- Create: `src/ai_novel_studio/domain/memory.py`
- Modify: `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
- Test: `tests/integration/storage/test_memory_schema.py`
- Test: `tests/unit/domain/test_memory_records.py`

**Interfaces:**
- Produce enums `Authority`, `ReviewStatus`, `MemoryStatus`, `KnowledgeSubject`, `KnowledgeState`, `ClueType`, `ClueAction`, `SummaryLevel`, and `StyleScope`.
- Produce immutable records for characters, state events, knowledge items/events, canon entries, clues/events, summaries, style rules/samples, and memory dependencies.
- Migration 2 creates normalized tables, indexes, `context_manifests`, and standalone `memory_fts` using FTS5.

- [x] Write failing tests for enum validation, immutable records, schema version 2, all table/index names, FTS5 availability, idempotence, and preservation of existing chapters.
- [x] Run focused tests and confirm schema/domain symbols are absent.
- [x] Implement domain records with non-empty text, confidence/range, and authority invariants.
- [x] Implement migration 2 without rewriting Phase 1 tables.
- [x] Run focused tests and the full suite.
- [x] Commit `feat: add phase 4 memory schema and records`.

### Task 2: Character state and temporal knowledge repositories

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/character_memory_repository.py`
- Create: `src/ai_novel_studio/core/memory/character_timeline.py`
- Test: `tests/integration/memory/test_character_timeline.py`

**Interfaces:**
- `CharacterMemoryRepository.create_character(...) -> Character`.
- `append_state(event)`, `state_before(character_id, chapter_id)`, and `history(character_id)` preserve every chapter event.
- `create_knowledge_item(...)`, `append_knowledge_event(...)`, and `knowledge_before(subject_type, subject_id, chapter_id)` return the latest reviewed state before the chapter boundary.
- `CharacterTimeline.snapshot(character_ids, before_chapter_id)` returns participating character state plus known/suspected/misunderstood/forgotten items.

- [x] Write failing integration tests with three ordered chapters proving state history is append-only, current/future events are excluded, reader and character knowledge are separated, aliases round-trip, and invalid subjects/states are rejected.
- [x] Run focused tests and confirm repository imports fail.
- [x] Implement chapter-boundary SQL using volume/chapter sort order, never declared chapter numbers.
- [x] Implement the timeline façade and conflict reporting for multiple reviewed events at the same boundary.
- [x] Run focused tests and full suite.
- [x] Commit `feat: add temporal character and knowledge memory`.

### Task 3: Canon, narrative-clue, and layered-style ledgers

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/narrative_memory_repository.py`
- Create: `src/ai_novel_studio/infrastructure/storage/style_repository.py`
- Create: `src/ai_novel_studio/core/memory/canon_ledger.py`
- Create: `src/ai_novel_studio/core/memory/narrative_clue_ledger.py`
- Create: `src/ai_novel_studio/core/context/style_retriever.py`
- Test: `tests/integration/memory/test_narrative_and_style_ledgers.py`

**Interfaces:**
- Canon queries resolve higher authority first and report same-authority conflicts instead of guessing.
- Clue queries expose typed active clues and time-bounded actions (`PLANT`, `REINFORCE`, `REDIRECT`, `REVEAL`, `RESOLVE`, `ABANDON`).
- Locked human Misdirection/Open Question/Atmospheric Hint records reject model mutation.
- `StyleRetriever.for_task(book_id, scene_scope, character_ids, chapter_id)` compiles BOOK, GENRE_OR_SCENE, CHARACTER, and CHAPTER layers in authority order and keeps human samples immutable.

- [ ] Write failing tests for canon authority, conflict reporting, clue type protection, action history, active-at-chapter filtering, layered style precedence, occurrence limits, and immutable human samples.
- [ ] Run focused tests and confirm missing repositories.
- [ ] Implement ledgers with explicit candidate/confirmed transitions and no model overwrite path.
- [ ] Implement style retrieval without merging AI annotations into source samples.
- [ ] Run focused tests and full suite.
- [ ] Commit `feat: add canon clue and layered style ledgers`.

### Task 4: Layered summaries, candidate promotion, and invalidation

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/summary_repository.py`
- Create: `src/ai_novel_studio/core/memory/summary_tree.py`
- Create: `src/ai_novel_studio/core/memory/memory_invalidation.py`
- Modify: `src/ai_novel_studio/infrastructure/storage/chapter_repository.py`
- Test: `tests/integration/memory/test_summary_and_invalidation.py`

**Interfaces:**
- `SummaryRepository.add_candidate(...)` records L1 chapter, L2 arc, L3 volume, or L4 book summaries with source revisions/hashes and `REVIEW` status.
- `promote(summary_id, expected_revision)` requires explicit review and cannot replace locked human content.
- `SummaryTree.best_available(scope, before_chapter_id)` prefers current reviewed summaries and exposes stale candidates separately.
- `MemoryInvalidationService.invalidate_chapter(chapter_id, new_revision, new_hash)` marks dependent summaries, search documents, candidate memories, and manifests stale while preserving their prior content for audit.
- Chapter save performs dependency invalidation in the same SQLite transaction as the new chapter revision metadata.

- [ ] Write failing tests for all four summary levels, source provenance, explicit promotion, optimistic revision checks, typo/no-rebuild choice, story-change invalidation, transitive summary staleness, and preservation of stale text.
- [ ] Run focused tests and confirm missing services.
- [ ] Implement summary storage/tree and dependency graph.
- [ ] Integrate invalidation into chapter saves without weakening rollback behavior.
- [ ] Run focused tests and full suite.
- [ ] Commit `feat: add summary tree and memory invalidation`.

### Task 5: FTS5 history indexing and time-bounded retrieval

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/search_repository.py`
- Create: `src/ai_novel_studio/core/context/history_retriever.py`
- Test: `tests/integration/context/test_history_retriever.py`

**Interfaces:**
- `SearchRepository.index_document(document)` upserts chapter text, summaries, canon, clues, and approved memory with source revision/hash.
- `HistoryRetriever.search(query, before_chapter_id, participants=(), limit=20)` combines FTS5 rank, manual pin weight, participant match, chapter distance, review state, and temporal exclusion.
- Results include stable source ID, chapter ID, revision, hash, excerpt, score components, and stale flag.

- [ ] Write failing tests for Chinese/ASCII FTS queries, stable upsert, participant boost, pinned boost, stale demotion, current/future exclusion, deterministic tie-breaking, and no vector dependency.
- [ ] Run focused tests and confirm missing search layer.
- [ ] Implement FTS synchronization and bounded snippets.
- [ ] Implement deterministic scoring and source tracing.
- [ ] Run focused tests and full suite.
- [ ] Commit `feat: add temporal fts history retrieval`.

### Task 6: Token budget, Context Manifest, and dynamic context builder

**Files:**
- Create: `src/ai_novel_studio/core/context/token_budget.py`
- Create: `src/ai_novel_studio/core/context/context_manifest.py`
- Create: `src/ai_novel_studio/core/context/context_builder.py`
- Test: `tests/unit/context/test_token_budget.py`
- Test: `tests/integration/context/test_context_builder.py`

**Interfaces:**
- `TokenBudget(context_window, output_limit, safety_margin).input_limit` rejects impossible user limits with a concrete error and never silently clamps them.
- `ContextBlock` carries category, stable source, revision/hash, priority, required flag, complete content, optional summary fallback, temporal boundary, and rationale.
- `ContextBuilder.build(request) -> BuiltContext` preserves required blocks, chooses recent full chapters before older summaries, adds relevant FTS evidence, uses whole-block fallbacks, and records every omission.
- `ContextManifestRepository.save(manifest)` atomically writes reviewable JSON under `.ai_pipeline/manifests` and stores its database reference.

- [ ] Write failing tests for the 128K/16K/4K = 108K calculation, user-limit overflow, required overflow, no middle truncation, previous-chapter preference, fallback selection, deterministic ordering, and complete inclusion/omission manifest fields.
- [ ] Run focused tests and confirm missing context types.
- [ ] Implement a deterministic conservative estimator and budget allocator.
- [ ] Implement manifest serialization and atomic persistence.
- [ ] Implement context assembly independent of models and UI.
- [ ] Run focused tests, full suite, Ruff, and mypy.
- [ ] Commit `feat: add reviewable dynamic context builder`.

### Task 7: Candidate memory extraction and review workspace binding

**Files:**
- Create: `src/ai_novel_studio/application/memory_analysis_service.py`
- Create: `src/ai_novel_studio/application/memory_workspace_service.py`
- Modify: `src/ai_novel_studio/ui/pages/memory_window.py`
- Test: `tests/unit/application/test_memory_analysis_service.py`
- Test: `tests/ui/test_phase_4_memory_workspace.py`

**Interfaces:**
- `MemoryAnalysisService.extract_candidates(chapter_id, revision, text)` routes through `MEMORY_EXTRACTION`, validates a structured bundle, and returns candidates only.
- `MemoryWorkspaceService` loads reviewed current memory, stale dependencies, compressed summaries, knowledge timelines, clues, canon, and source metadata for a chapter boundary; edits call repositories explicitly.
- `MemoryWindow.bind(service, before_chapter_id)` displays source/revision/authority/review status, permits user edits and promotion, and never silently promotes AI output.

- [ ] Write failing tests for prompt/source order, contract rejection, candidate-only behavior, locked-record protection, chapter-boundary display, direct user edits, review/promotion, and stale warnings.
- [ ] Run focused tests and confirm missing services/UI behavior.
- [ ] Implement extraction contracts and review application services.
- [ ] Bind the existing memory page through injected services while retaining offline demo compatibility.
- [ ] Run focused tests and full suite.
- [ ] Commit `feat: connect phase 4 memory review workspace`.

### Task 8: Documentation, pressure checks, Windows build, and Desktop sync

**Files:**
- Create: `docs/architecture/0005-memory-and-context-kernel.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-02-director-writer-workflow-design.md`
- Modify: `src/ai_novel_studio/__init__.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Document data ownership, temporal semantics, authority, candidate promotion, FTS scoring, budget policy, manifest format, invalidation, and Phase 4/5 boundaries.

- [ ] Add representative 100+ chapter retrieval/budget fixtures without generating user manuscript content or committing databases.
- [ ] Update package version to `0.4.0` with a metadata consistency test.
- [ ] Run all tests with a controlled temp directory, Ruff, mypy, source/history/dist privacy scans, and Windows build.
- [ ] Verify the EXE startup probe, commit documentation, fast-forward merge to `codex/phase-1-data-kernel`, and delete the feature branch.
- [ ] Sync the clean Desktop repository and `dist`, rerun Desktop verification, compare EXE hashes, and do not push GitHub.

## Self-review

- Spec coverage: L0–L4 summaries, character state, character/reader knowledge, typed clues, layered style, FTS5, time filtering, Context Manifest, Token budget, candidate promotion, and invalidation each have an implementation task.
- Authority boundary: model extraction never promotes or overwrites human-confirmed records.
- Temporal boundary: repository and retriever tests exclude current/future chapter events by stable sort order.
- Context fidelity: whole blocks and explicit fallbacks prevent silent middle truncation; evidence mapping remains separate from manuscript editing.
- Phase boundary: Phase 5 owns generation state/checkpoints and Phase 6 owns repair.
- Privacy: no sample uses real names, local manuscripts, API keys, or committed project databases.
