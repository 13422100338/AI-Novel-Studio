# AI Novel Studio Phase 5 正文生成流水线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现基础/标准两档正式正文生成、可冻结 Chapter Brief、动态上下文交接、流式检查点、人工采用和重启恢复，同时确保模型永不直接覆盖正式正文。

**Architecture:** Phase 5 通过 SQLite schema v3 增加要求、Brief、来源、生成任务和检查点。应用服务控制状态机，阶段 4 的 ContextBuilder/Manifest 负责写前上下文，统一模型网关负责单次流式调用，ChapterRepository 只在用户明确采用后保存正文。严格模式只显示禁用状态，不提前实现阶段 6 审校或阶段 7 Agent。

**Tech Stack:** Python 3.11+、SQLite、Markdown、PySide6、现有 OpenAI-compatible 网关、pytest、pytest-qt、Ruff、mypy、PyInstaller。

## Global Constraints

- 只在 `codex/phase-5-prose-pipeline` 分支开发，不推送 GitHub。
- 不读取或修改用户真实稿件、项目数据库、备份、导出、API Key 或隐私阻止词。
- 所有测试使用合成项目和受控 `--basetemp`。
- 模型输出不可信；结构化输出和状态转换必须由程序验证。
- 正文生成、摘要/记忆提取、审校和修复保持为独立调用。
- 用户输出 Token 上限原样传递；超过已知模型能力时明确报错，不静默缩减。
- 必需上下文不截断；可选内容只能整块采用、摘要回退或记录省略。
- 流式输出先进入检查点；正式正文只由显式采用操作写入。
- 同一章节同一时刻最多一个 `PREPARING`、`READY` 或 `STREAMING` 任务。
- 严格模式禁用并说明需要阶段 6；阶段 5 不实现自动修复或 Agent 工具循环。

---

### Task 1: Schema v3 与正文流水线领域状态

**Files:**
- Create: `src/ai_novel_studio/domain/generation.py`
- Modify: `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
- Test: `tests/unit/domain/test_generation_records.py`
- Test: `tests/integration/storage/test_generation_schema.py`

**Interfaces:**
- Produce `CreationMode(BASIC, STANDARD, STRICT)`、`BriefStatus(DRAFT, FROZEN, STALE, ARCHIVED)`、`GenerationStatus(PREPARING, READY, STREAMING, PARTIAL, COMPLETED, FAILED, ACCEPTED, DISCARDED)`。
- Produce immutable `ChapterRequirement`、`ChapterBrief`、`BriefSource`、`GenerationRun`、`GenerationCheckpoint` records。
- Migration 3 creates `chapter_requirements`、`chapter_briefs`、`brief_sources`、`generation_runs`、`generation_checkpoints` and partial unique index `generation_one_active_writer`。

- [x] **Step 1: Write failing domain and migration tests** proving enum values, immutable records, non-negative revisions/Token usage, schema version 3, unique requirement per chapter, unique source/checkpoint keys, active-writer partial index, idempotence, and preservation of Phase 1–4 rows.

```python
def test_schema_v3_preserves_existing_chapter_and_limits_active_writer(project):
    assert LATEST_SCHEMA_VERSION == 3
    with pytest.raises(sqlite3.IntegrityError):
        insert_second_streaming_run_for_same_chapter(project)
```

- [x] **Step 2: Run the focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\domain\test_generation_records.py tests\integration\storage\test_generation_schema.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task1-red
```

Expected: missing `ai_novel_studio.domain.generation` and schema version remains 2.

- [x] **Step 3: Implement domain records and migration 3** without altering migrations 1–2. Use database checks for enum text, non-negative revisions/usage, foreign keys, and the active-run partial unique index.

```python
class GenerationStatus(StrEnum):
    PREPARING = "PREPARING"
    READY = "READY"
    STREAMING = "STREAMING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ACCEPTED = "ACCEPTED"
    DISCARDED = "DISCARDED"
```

- [x] **Step 4: Run focused tests, full pytest, Ruff, and mypy.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task1-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [x] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/domain/generation.py src/ai_novel_studio/infrastructure/storage/migration_manager.py tests/unit/domain/test_generation_records.py tests/integration/storage/test_generation_schema.py
git commit -m "feat: add phase 5 generation schema"
```

### Task 2: 当前章要求持久化与模型覆盖保护

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/chapter_requirement_repository.py`
- Create: `src/ai_novel_studio/application/chapter_requirement_service.py`
- Test: `tests/integration/generation/test_chapter_requirement.py`

**Interfaces:**
- `ChapterRequirementRepository.get_or_create(chapter_id) -> ChapterRequirement`
- `save_user(chapter_id, content, is_locked, expected_revision) -> ChapterRequirement`
- `apply_model_candidate(chapter_id, content, expected_revision) -> ChapterRequirement`
- User saves may explicitly lock/unlock; model candidates reject locked requirements and stale revisions.

- [x] **Step 1: Write failing tests** for first creation, content hash, user lock/unlock, optimistic revision, model candidate protection, empty content rejection, and chapter identity by UUID rather than title/number.

```python
locked = service.save_user(chapter.id, "必须收到来信", True, expected_revision=0)
with pytest.raises(LockedRequirementError):
    service.apply_model_candidate(chapter.id, "覆盖要求", expected_revision=locked.revision)
```

- [x] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\generation\test_chapter_requirement.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task2-red
```

- [x] **Step 3: Implement repository transactions and application protection.** Hash normalized UTF-8 content with SHA-256; update with `WHERE revision = ?`; never let model calls unlock a requirement.

```python
cursor = connection.execute(
    "UPDATE chapter_requirements SET content=?, revision=revision+1 WHERE chapter_id=? AND revision=?",
    (content, chapter_id, expected_revision),
)
```

- [x] **Step 4: Run focused and full gates.**

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\generation\test_chapter_requirement.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task2-green
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task2-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [x] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/infrastructure/storage/chapter_requirement_repository.py src/ai_novel_studio/application/chapter_requirement_service.py tests/integration/generation/test_chapter_requirement.py
git commit -m "feat: persist protected chapter requirements"
```

### Task 3: Brief 仓库、来源指纹和生命周期

**Files:**
- Create: `src/ai_novel_studio/core/brief/source_fingerprint.py`
- Create: `src/ai_novel_studio/infrastructure/storage/chapter_brief_repository.py`
- Create: `src/ai_novel_studio/application/brief_lifecycle_service.py`
- Test: `tests/integration/generation/test_brief_lifecycle.py`

**Interfaces:**
- `compute_source_fingerprint(sources: tuple[BriefSource, ...]) -> str` sorts by `(source_type, source_id, source_revision, source_hash, required)`.
- Repository creates drafts and returns Brief + source snapshots.
- `BriefLifecycleService.freeze(brief_id, expected_revision)` validates current source fingerprint and required fields.
- `mark_stale_for_source(source_type, source_id, revision, hash)` preserves content.
- `clone_as_draft(brief_id) -> BriefCloneResult` archives no source record and reports added/removed/changed sources.

- [x] **Step 1: Write failing tests** for deterministic fingerprints, source ordering, draft edit, frozen immutability, one current frozen Brief per chapter, stale propagation, clone provenance, source diff, and optimistic revision conflicts.

```python
first = compute_source_fingerprint((source_b, source_a))
second = compute_source_fingerprint((source_a, source_b))
assert first == second
```

- [x] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\generation\test_brief_lifecycle.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task3-red
```

- [x] **Step 3: Implement fingerprint, repository, and legal transitions.** Freeze archives an older frozen Brief only in the same transaction that freezes the new one; stale/archived text and sources remain queryable.

```python
LEGAL_BRIEF_TRANSITIONS = {
    BriefStatus.DRAFT: {BriefStatus.FROZEN, BriefStatus.ARCHIVED},
    BriefStatus.FROZEN: {BriefStatus.STALE, BriefStatus.ARCHIVED},
    BriefStatus.STALE: {BriefStatus.ARCHIVED},
}
```

- [x] **Step 4: Run focused/full tests and static gates.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task3-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [x] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/core/brief/source_fingerprint.py src/ai_novel_studio/infrastructure/storage/chapter_brief_repository.py src/ai_novel_studio/application/brief_lifecycle_service.py tests/integration/generation/test_brief_lifecycle.py
git commit -m "feat: add reviewable chapter brief lifecycle"
```

### Task 4: ChapterBriefCompiler 与时间边界验证

**Files:**
- Create: `src/ai_novel_studio/application/chapter_brief_compiler.py`
- Create: `src/ai_novel_studio/application/brief_context_provider.py`
- Test: `tests/integration/generation/test_chapter_brief_compiler.py`

**Interfaces:**
- `BriefCompilationRequest(chapter_id, mode, expected_requirement_revision, target_length, story_date, pov_character_id, participants)`.
- `BriefContextProvider.collect(request) -> BriefCompilationInputs` reads Phase 4 repositories before the chapter boundary.
- `CompiledBrief(brief, sources, conflicts)` is the immutable application result.
- `ChapterBriefCompiler.compile(request) -> CompiledBrief` stores a `DRAFT` and complete source snapshots.
- Compiler returns explicit `BriefConflict` values; it never guesses among same-authority canon/state conflicts.

- [x] **Step 1: Write failing tests** proving source order, current/future exclusion, requirement priority, character/reader knowledge separation, active clue actions, layered style inclusion, source revision/hash capture, missing required source warnings, and conflict-blocked freeze.

```python
compiled = compiler.compile(request)
assert compiled.sources[0].source_type == "CHAPTER_REQUIREMENT"
assert future_knowledge.id not in {source.source_id for source in compiled.sources}
```

- [x] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\generation\test_chapter_brief_compiler.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task4-red
```

- [x] **Step 3: Implement the provider and compiler** by composing existing requirement, character, knowledge, narrative, style, summary, and search repositories. Keep query logic in repositories/provider; compiler only assembles and validates.

```python
sources = (
    inputs.requirement_source,
    *inputs.character_sources,
    *inputs.knowledge_sources,
    *inputs.clue_sources,
    *inputs.style_sources,
    *inputs.history_sources,
)
```

- [x] **Step 4: Run focused/full tests and static gates.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task4-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [x] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/application/chapter_brief_compiler.py src/ai_novel_studio/application/brief_context_provider.py tests/integration/generation/test_chapter_brief_compiler.py
git commit -m "feat: compile time-bounded chapter briefs"
```

### Task 5: 生成准备、Context Manifest 与正文提示顺序

**Files:**
- Create: `src/ai_novel_studio/application/generation_context_service.py`
- Create: `src/ai_novel_studio/core/context/prose_prompt.py`
- Modify: `src/ai_novel_studio/core/context/context_manifest.py`
- Create: `src/ai_novel_studio/infrastructure/storage/generation_repository.py` with only
  preparation persistence; Task 6 extends it with the complete transition table.
- Modify: `src/ai_novel_studio/infrastructure/storage/chapter_repository.py`
- Test: `tests/integration/generation/test_generation_context.py`

**Interfaces:**
- `GenerationPreparationRequest(chapter_id, mode, brief_id, output_token_limit, model_capabilities, target_words, model_provider_id, model_id, safety_margin)`.
- `GenerationContextService.prepare(request) -> PreparedGeneration` creates a `PREPARING` run, validates BASIC/STANDARD rules, builds whole blocks, persists Manifest, and advances run to `READY`.
- `build_prose_messages(requirement, brief, selected_blocks) -> tuple[LLMMessage, ...]` uses stable system prefix and final “only prose” task.

- [x] **Step 1: Write failing tests** for BASIC without Brief, STANDARD requiring current FROZEN Brief, STRICT rejection, stale Brief rejection, user output limit preservation, model limit overflow, required block overflow before API call, recent-full preference, manifest/run linkage, and exact message order.

```python
with pytest.raises(StrictModeUnavailableError):
    service.prepare(replace(request, mode=CreationMode.STRICT))
assert prepared.run.output_token_limit == 32_000
assert prepared.messages[-1].content.endswith("只输出本章正文。")
```

- [x] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\generation\test_generation_context.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task5-red
```

- [x] **Step 3: Implement preparation and prompt building.** Persist run linkage through repositories rather than letting UI or model code write it.

```python
budget = TokenBudget(context_window, request.output_token_limit, safety_margin)
budget.validate_model_output_limit(model_capabilities.max_output_tokens)
```

- [x] **Step 4: Run focused/full tests and static gates.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task5-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [x] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/application/generation_context_service.py src/ai_novel_studio/core/context/prose_prompt.py src/ai_novel_studio/core/context/context_manifest.py src/ai_novel_studio/infrastructure/storage/generation_repository.py src/ai_novel_studio/infrastructure/storage/chapter_repository.py tests/integration/generation/test_generation_context.py
git commit -m "feat: prepare traceable prose context"
```

### Task 6: GenerationRun、追加检查点与单写手约束

**Files:**
- Modify: `src/ai_novel_studio/infrastructure/storage/generation_repository.py`
- Create: `src/ai_novel_studio/infrastructure/storage/checkpoint_repository.py`
- Test: `tests/integration/generation/test_generation_state_and_checkpoints.py`

**Interfaces:**
- `GenerationRepository.create_preparing(...) -> GenerationRun`
- `transition(run_id, expected_status, target_status, **fields) -> GenerationRun` enforces a legal transition table.
- `CheckpointRepository.append(run_id, text, finish_reason=None) -> GenerationCheckpoint` atomically writes cumulative text and inserts the next sequence.
- `latest(run_id) -> GenerationCheckpoint | None` verifies path stays inside project root and hash matches.

- [x] **Step 1: Write failing tests** for all legal/illegal transitions, active-writer conflicts, cumulative append-only checkpoints, sequence uniqueness, atomic file failure rollback, path traversal rejection, hash mismatch, and preservation of previous valid checkpoint.

```python
first = checkpoints.append(run.id, "第一段")
second = checkpoints.append(run.id, "第一段\n第二段")
assert first.sequence == 0 and second.sequence == 1
assert checkpoints.read(first.id) == "第一段"
```

- [x] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\generation\test_generation_state_and_checkpoints.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task6-red
```

- [x] **Step 3: Implement repositories** using `atomic_write_text`, project-relative paths, optimistic status updates, and database rollback when file persistence fails. Never overwrite earlier checkpoint files.

```python
LEGAL_GENERATION_TRANSITIONS = {
    GenerationStatus.PREPARING: {GenerationStatus.READY, GenerationStatus.FAILED},
    GenerationStatus.READY: {GenerationStatus.STREAMING, GenerationStatus.FAILED},
    GenerationStatus.STREAMING: {
        GenerationStatus.PARTIAL,
        GenerationStatus.COMPLETED,
        GenerationStatus.FAILED,
    },
}
```

- [x] **Step 4: Run focused/full tests and static gates.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task6-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [x] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/infrastructure/storage/generation_repository.py src/ai_novel_studio/infrastructure/storage/checkpoint_repository.py tests/integration/generation/test_generation_state_and_checkpoints.py
git commit -m "feat: add recoverable generation runs"
```

### Task 7: 正文流式服务与后台协调器

**Files:**
- Create: `src/ai_novel_studio/application/prose_generation_service.py`
- Create: `src/ai_novel_studio/application/prose_generation_coordinator.py`
- Test: `tests/unit/application/test_prose_generation_service.py`
- Test: `tests/ui/test_prose_generation_coordinator.py`

**Interfaces:**
- `ProseGenerationService.stream(run_id) -> Iterator[ProseGenerationEvent]` calls `TaskPurpose.PROSE_GENERATION` exactly once.
- `cancel(run_id)` sets a cancellation token; it never starts another request.
- TEXT updates a cumulative buffer and saves checkpoints at deterministic character thresholds plus final/partial boundaries.
- REASONING is emitted separately and never added to draft text.
- Coordinator exposes Qt signals: `draft_chunk(str)`, `usage_changed(object)`, `run_changed(object)`, `failed(str)`.

- [x] **Step 1: Write failing tests** for exact prompt/Token forwarding, single paid call, text ordering, reasoning isolation, usage persistence, threshold checkpoints, completion, partial failure with/without text, cancellation, and coordinator non-blocking signals.

```python
events = tuple(service.stream(run.id))
assert gateway.stream_calls == 1
assert repository.get(run.id).status == GenerationStatus.COMPLETED
latest = checkpoints.latest(run.id)
assert latest is not None
assert checkpoints.read(latest.id) == "第一段第二段"
```

- [x] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\application\test_prose_generation_service.py tests\ui\test_prose_generation_coordinator.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task7-red
```

- [x] **Step 3: Implement service and coordinator.** The service transitions `READY -> STREAMING` before the gateway call; any exception is sanitized before persistence/UI emission.

```python
for event in gateway.stream(TaskPurpose.PROSE_GENERATION, messages, output_limit):
    if event.kind == StreamEventKind.TEXT:
        buffer.append(event.text)
    elif event.kind == StreamEventKind.REASONING:
        yield ProseGenerationEvent.reasoning(event.text)
```

- [x] **Step 4: Run focused/full tests and static gates.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task7-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [x] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/application/prose_generation_service.py src/ai_novel_studio/application/prose_generation_coordinator.py tests/unit/application/test_prose_generation_service.py tests/ui/test_prose_generation_coordinator.py
git commit -m "feat: stream prose into durable checkpoints"
```

### Task 8: 草稿采用、放弃与重启恢复

**Files:**
- Create: `src/ai_novel_studio/application/generation_acceptance_service.py`
- Create: `src/ai_novel_studio/application/generation_recovery_service.py`
- Modify: `src/ai_novel_studio/infrastructure/storage/chapter_repository.py`
- Test: `tests/integration/generation/test_generation_acceptance_and_recovery.py`

**Interfaces:**
- `accept(run_id, expected_chapter_revision, allow_partial=False) -> AcceptedGeneration`
- `discard(run_id) -> GenerationRun` preserves checkpoints.
- `GenerationRecoveryService.scan() -> tuple[RecoverableGeneration, ...]` returns PREPARING/READY/STREAMING/PARTIAL runs and never calls a model.
- Acceptance snapshots prior正文, writes checkpoint text, records accepted chapter revision, and triggers existing memory invalidation.

- [ ] **Step 1: Write failing tests** proving formal正文 unchanged before accept, completed acceptance, explicit partial acceptance, default partial rejection, concurrent chapter revision rejection, duplicate acceptance rejection, version snapshot creation, hash validation, memory invalidation, discard preservation, and no API calls during recovery.

```python
assert chapters.read_content(chapter.id) == "旧正文"
accepted = service.accept(run.id, expected_chapter_revision=0)
assert chapters.read_content(chapter.id) == "生成正文"
assert chapters.list_versions(chapter.id)[0].content_hash == old_hash
```

- [ ] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\generation\test_generation_acceptance_and_recovery.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task8-red
```

- [ ] **Step 3: Implement acceptance and recovery.** Add an expected-revision guard to `ChapterRepository.save_content`; if the chapter changed, preserve the run/checkpoint and reject adoption.

```python
updated = chapters.save_content(
    run.chapter_id,
    draft,
    source="ai_generation",
    reason=f"accepted generation run {run.id}",
    expected_revision=expected_chapter_revision,
)
```

- [ ] **Step 4: Run focused/full tests and static gates.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task8-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [ ] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/application/generation_acceptance_service.py src/ai_novel_studio/application/generation_recovery_service.py src/ai_novel_studio/infrastructure/storage/chapter_repository.py tests/integration/generation/test_generation_acceptance_and_recovery.py
git commit -m "feat: accept and recover generated drafts safely"
```

### Task 9: Brief 与正文 UI 服务接入

**Files:**
- Modify: `src/ai_novel_studio/ui/pages/brief_dialog.py`
- Modify: `src/ai_novel_studio/ui/panels/manuscript_panel.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Test: `tests/ui/test_phase_5_brief_and_generation.py`

**Interfaces:**
- `BriefDialog.bind(service, chapter_id)` loads real draft/frozen/stale state while retaining offline demo compatibility.
- `ManuscriptPanel` exposes mode, Token limit, generated-draft viewer, cancel/adopt/discard/retry signals, and a separate formal正文 editor.
- `MainWindow` injects Phase 5 services when a project runtime is available; offline demo does not write storage or call a model.

- [ ] **Step 1: Write failing UI tests** for BASIC enabled, STANDARD disabled without FROZEN Brief, STRICT disabled with explanation, freeze/clone metadata, prepare confirmation, streaming draft separation, cancel, partial label, adopt confirmation, recovery entry, and Token usage fields.

```python
panel.mode_combo.setCurrentText("标准")
assert panel.generate_button.isEnabled() is False
brief_state.emit(frozen_brief)
assert panel.generate_button.isEnabled() is True
assert panel.editor.toPlainText() == "正式正文未变化"
```

- [ ] **Step 2: Run focused tests and verify RED.**

```powershell
.venv\Scripts\python.exe -m pytest tests\ui\test_phase_5_brief_and_generation.py -q -p no:cacheprovider --basetemp .test-temp\phase5-task9-red
```

- [ ] **Step 3: Implement service-driven UI binding** with Qt signals only. Do not call SQLite or provider adapters from widgets. Keep current black/white theme and existing resizable layout.

```python
self.generation_requested.emit(
    self.mode_combo.currentData(),
    self.output_token_limit.value(),
)
```

- [ ] **Step 4: Run UI/full tests and static gates.**

```powershell
.venv\Scripts\python.exe -m pytest tests\ui -q -p no:cacheprovider --basetemp .test-temp\phase5-task9-ui
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-task9-full
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [ ] **Step 5: Commit.**

```powershell
git add src/ai_novel_studio/ui/pages/brief_dialog.py src/ai_novel_studio/ui/panels/manuscript_panel.py src/ai_novel_studio/ui/main_window.py tests/ui/test_phase_5_brief_and_generation.py
git commit -m "feat: connect phase 5 generation workspace"
```

### Task 10: 压力验证、文档、0.5.0 构建与桌面同步

**Files:**
- Create: `docs/architecture/0006-prose-generation-pipeline.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-02-director-writer-workflow-design.md`
- Modify: `src/ai_novel_studio/__init__.py`
- Modify: `pyproject.toml`
- Modify: `docs/superpowers/plans/2026-07-03-ai-novel-studio-phase-5.md`
- Test: `tests/integration/generation/test_generation_pressure.py`
- Test: `tests/test_package_layout.py`

**Interfaces:**
- Version becomes `0.5.0` in package and build metadata.
- ADR documents ownership, legal transitions, prompt order, Token policy, checkpoint format, adoption boundary, recovery, and Phase 5/6/7 separation.

- [ ] **Step 1: Add failing version and pressure tests.** Create 100+ synthetic chapters, prepare STANDARD context, stream a long synthetic response through multiple checkpoints, recover it, and accept it without committing generated databases/files.

```python
assert ai_novel_studio.__version__ == "0.5.0"
assert len(checkpoints.list_for_run(run.id)) >= 3
assert recovery.scan()[0].run_id == run.id
```

- [ ] **Step 2: Update version and documentation.** Do not include real names, private paths, manuscripts, keys, model response bodies, local databases, or build caches.

```toml
[project]
version = "0.5.0"
```

- [ ] **Step 3: Run final source gates with controlled temp.**

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-temp\phase5-final
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_release.ps1
```

- [ ] **Step 4: Build and probe Windows EXE.** Require the build script to stop on any native command failure; start the EXE offscreen, confirm it remains alive for five seconds, then stop the probe.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
$env:QT_QPA_PLATFORM = "offscreen"
$process = Start-Process dist\AI-Novel-Studio\AI-Novel-Studio.exe -PassThru -WindowStyle Hidden
```

- [ ] **Step 5: Commit, fast-forward merge, delete feature branch, and sync Desktop.** Re-run Desktop tests using the development interpreter with Desktop `PYTHONPATH`, run Desktop privacy verification, compare EXE SHA-256, and do not push GitHub.

```powershell
git add README.md docs src pyproject.toml tests
git commit -m "chore: complete phase 5 prose pipeline"
git switch codex/phase-1-data-kernel
git merge --ff-only codex/phase-5-prose-pipeline
```

## Self-review

- Spec coverage: BASIC/STANDARD/disabled STRICT, requirement persistence, Brief lifecycle, time-bounded compiler, Context Manifest, user Token limit, single paid stream, checkpoints, acceptance, recovery, UI, pressure/build/privacy are each assigned to a task.
- Storage boundary: UI and model gateway never write project data directly; application services call repositories.
- Manuscript safety: generation cannot call `ChapterRepository.save_content` before explicit acceptance.
- Model boundary: prose, memory extraction, audit, and repair remain separate tasks.
- Recovery boundary: restart scans state/checkpoints and never retries a provider call automatically.
- Phase boundary: deterministic/model audit and repair remain Phase 6; Agent tools remain Phase 7.
