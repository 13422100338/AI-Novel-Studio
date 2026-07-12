# Phase 8 Project Runtime Implementation Plan

> **For implementation workers:** execute this plan task-by-task. Do not dispatch subagents unless the user explicitly asks for subagent or parallel-agent execution. Keep the user conversation in Chinese. Do not push to GitHub unless explicitly requested.

## Goal

Phase 8 turns the V3 desktop app from a demo-data workbench into a real project workbench. The user should be able to create/open a V3 project directory, see real volumes/chapters in the UI, select a chapter, edit its manuscript and current chapter requirement, and have existing Phase 5/6/7 services operate against that open project rather than `WorkspaceDemoData.sample()`.

This phase is not the full future Agents mode. It only wires the Phase 7 read-only tool retrieval foundation to the currently opened project.

## Documentation Discovery / Allowed APIs

Sources checked:

- `docs/architecture/0001-clean-room-v3.md`
  - V3 is clean-room, public identity must not include private identity or local paths.
- `docs/architecture/0002-project-data-format.md`
  - A project is a portable directory with `project.json`, `project.sqlite3`, `manuscript/`, `assets/`, `exports/`, `backups/`, and `.ai_pipeline/`.
  - `ProjectRepository.create(root, title)` creates a portable project.
  - `ProjectRepository.open(root)` opens and migrates a project.
  - `ProjectLock` provides single-writer locking with no private path stored in lock metadata.
- `docs/architecture/0007-agent-tool-loop.md`
  - Phase 7 is read-only tool retrieval and evidence trace, not full Agents mode.
  - Retrieval tools must remain read-only and budgeted.
- `src/ai_novel_studio/infrastructure/storage/project_repository.py`
  - Available APIs: `ProjectRepository.create`, `ProjectRepository.open`, `list_volumes`, `create_volume`.
- `src/ai_novel_studio/infrastructure/storage/chapter_repository.py`
  - Available APIs used by the UI runtime: `create_chapter`, `get_chapter`, `list_chapters`, `read_content`, `save_content`, `delete_chapter`, `restore_chapter`, `delete_volume`.
- `src/ai_novel_studio/infrastructure/storage/project_lock.py`
  - Available APIs: `ProjectLock.acquire`, `release`, context-manager methods.
- `src/ai_novel_studio/application/generation_context_service.py`
  - Existing generation preparation requires real `ProjectRepository`, `ChapterRepository`, `ChapterRequirementRepository`, `ChapterBriefRepository`, `GenerationRepository`, and `ContextManifestRepository`.
- `src/ai_novel_studio/application/generation_acceptance_service.py`
  - Existing draft acceptance writes through `ChapterRepository.save_content` and validates revision.
- `src/ai_novel_studio/application/agent_tool_providers.py`
  - `build_project_agent_registry(project)` creates the Phase 7 read-only retrieval registry for a real project.
- `src/ai_novel_studio/ui/main_window.py`
  - Current UI still initializes `self.data = WorkspaceDemoData.sample()`.
  - `MainWindow` accepts injected `model_runtime`, `generation_runtime`, and `agent_runtime`.
- `src/ai_novel_studio/app.py`
  - Current startup creates `MainWindow()` directly.
- `src/ai_novel_studio/application/legacy_import/*`
  - Legacy import already scans and imports old `meta.json + DOCX` projects read-only into a new V3 project.

Anti-patterns to avoid:

- Do not store absolute local paths inside `project.json`, SQLite project metadata, trace records, or release docs.
- Do not make UI widgets talk to SQLite directly. Use application services or view-model/adapters.
- Do not replace repository APIs with a new storage layer.
- Do not convert Phase 8 into full Agents mode, cloud sync, or autonomous writing.
- Do not auto-save destructive edits without preserving revision/history rules already enforced by repositories.
- Do not mutate user manuscripts, databases, backups, exports, or secrets during tests unless the test creates its own temporary project.

## Scope

### In scope

1. Project lifecycle UI:
   - Create V3 project.
   - Open existing V3 project.
   - Hold/release a `ProjectLock` for opened projects.
   - Show current project title/status in the top bar or a small project status area.

2. Project-backed workspace state:
   - Replace demo-only workspace source with a project-backed adapter.
   - Populate volume/chapter tree from `ProjectRepository.list_volumes()` and `ChapterRepository.list_chapters()`.
   - Select current chapter and load real title, content, revision, and word count.
   - Save manuscript edits through `ChapterRepository.save_content`.
   - Preserve existing chapter history behavior.

3. Current chapter requirement:
   - Load/create/update the current chapter requirement using `ChapterRequirementRepository`.
   - Keep existing requirement lock semantics in the UI.
   - Model-generated requirement remains a draft until user accepts/edits it.

4. Existing service wiring:
   - Wire Phase 5 generation runtime to the opened project.
   - Wire Phase 6 audit workflows to the opened project.
   - Wire Phase 7 read-only tool retrieval to the opened project through `build_project_agent_registry(project)`.

5. Import/open workflow:
   - Expose existing legacy importer as an explicit user action.
   - Import into a new V3 destination only.
   - Never modify source legacy files.
   - Show a migration report path or summary.

6. Safety and recovery:
   - Project lock failure gives a clear user-facing error.
   - Save failures do not erase editor text.
   - Stale revision conflicts are reported and require user decision.
   - Startup without a project can still show an empty welcome state.

### Out of scope

- Full Agents mode.
- Multi-agent orchestration.
- Native provider function calling.
- Cloud sync.
- Real-time collaborative editing.
- Automatic full-book generation.
- Replacing SQLite/Markdown storage.
- Rewriting the whole UI architecture.

## File Structure

Expected new files:

- `src/ai_novel_studio/application/project_workspace_service.py`
  - Application-layer facade for opening/creating projects, current chapter loading, and safe saves.
- `src/ai_novel_studio/application/project_runtime.py`
  - Builds per-project service objects: repositories, generation runtime, audit services, and read-only retrieval runtime.
- `src/ai_novel_studio/ui/pages/project_welcome.py`
  - Welcome/create/open/import entry page or panel.
- `tests/unit/application/test_project_workspace_service.py`
- `tests/integration/application/test_project_runtime.py`
- `tests/ui/test_project_runtime_ui.py`

Expected modified files:

- `src/ai_novel_studio/app.py`
  - Startup should allow a no-project welcome state and optional command-line project path if added.
- `src/ai_novel_studio/ui/main_window.py`
  - Accept project workspace/runtime injection.
  - Replace unconditional `WorkspaceDemoData.sample()` with project-backed state when a project is open.
- `src/ai_novel_studio/ui/panels/chapter_sidebar.py`
  - Add methods to load project-backed volume/chapter view models.
  - Keep UI widget storage-free.
- `src/ai_novel_studio/ui/panels/manuscript_panel.py`
  - Add methods to apply a selected chapter view model and dirty/save status.
- `src/ai_novel_studio/ui/panels/top_bar.py`
  - Show current project title/open state if not already sufficient.
- `src/ai_novel_studio/ui/pages/settings_dialog.py`
  - No major changes expected; only ensure opened-project runtime reuses current model config.
- `README.md`
  - Add Phase 8 summary after implementation.
- `src/ai_novel_studio/__init__.py` and `pyproject.toml`
  - Bump to `0.8.0` after successful implementation.
- `tests/test_package_layout.py`
  - Add/import assertions for new Phase 8 modules and version.

## Data Flow

```text
User opens/creates project
        |
        v
ProjectWorkspaceService
        |
        +-- ProjectRepository / ProjectLock
        +-- ChapterRepository
        +-- ChapterRequirementRepository
        +-- repositories for Brief, generation, audit, memory, agent trace
        |
        v
ProjectRuntime
        |
        +-- Generation runtime for Phase 5
        +-- Audit workflow services for Phase 6
        +-- Read-only retrieval runtime for Phase 7
        |
        v
MainWindow / panels receive view models only
```

Widgets should not import repository classes directly. UI panels receive plain view models and emit user-intent signals. `MainWindow` or a small controller coordinates application services.

## Task 1: Project workspace service

**Files:**

- Create `src/ai_novel_studio/application/project_workspace_service.py`
- Test `tests/unit/application/test_project_workspace_service.py`

**What to implement:**

- Immutable view models:
  - `ProjectSummary`
  - `VolumeTreeItem`
  - `ChapterTreeItem`
  - `ChapterWorkspace`
  - `SaveChapterResult`
- Service methods:
  - `create_project(root: Path, title: str) -> ProjectSummary`
  - `open_project(root: Path) -> ProjectSummary`
  - `close_project() -> None`
  - `volume_tree() -> tuple[VolumeTreeItem, ...]`
  - `load_chapter(chapter_id: str) -> ChapterWorkspace`
  - `save_chapter(chapter_id: str, content: str, expected_revision: int) -> SaveChapterResult`

**References:**

- `ProjectRepository.create/open/list_volumes`
- `ProjectLock.acquire/release`
- `ChapterRepository.list_chapters/read_content/save_content`

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_project_workspace_service.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/application/project_workspace_service.py tests/unit/application/test_project_workspace_service.py
```

**Anti-pattern guards:**

- Service must not write outside the selected project root.
- Lock metadata must not include private paths.
- Tests must use temporary projects only.

## Task 2: Project runtime builder

**Files:**

- Create `src/ai_novel_studio/application/project_runtime.py`
- Test `tests/integration/application/test_project_runtime.py`

**What to implement:**

- `ProjectRuntime` dataclass/facade holding:
  - `project`
  - `workspace`
  - `generation_runtime`
  - `agent_task_service` or read-only retrieval runtime adapter
  - audit services/repositories needed by the UI
- Factory:
  - `ProjectRuntime.open(root: Path, model_runtime: ModelRuntime) -> ProjectRuntime`
  - `ProjectRuntime.create(root: Path, title: str, model_runtime: ModelRuntime) -> ProjectRuntime`
- Wire Phase 7:
  - `AgentRepository(project)`
  - `build_project_agent_registry(project)`
  - model adapter using existing `LLMGateway.complete(..., json_mode=True)` through `TaskPurpose.AGENT_ASSISTANT`
  - `AgentLoopService`
  - `AgentTaskService`

**References:**

- `ModelRuntime.gateway`
- `TaskPurpose.AGENT_ASSISTANT`
- `build_project_agent_registry(project)`
- `AgentRepository`
- `AgentLoopService`
- `AgentTaskService`

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/application/test_project_runtime.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase8runtime
```

**Anti-pattern guards:**

- Do not add native function calling.
- Do not let read-only retrieval mutate project state.
- Do not duplicate repository construction throughout UI widgets.

## Task 3: Welcome/open/create/import UI

**Files:**

- Create `src/ai_novel_studio/ui/pages/project_welcome.py`
- Modify `src/ai_novel_studio/app.py`
- Modify `src/ai_novel_studio/ui/main_window.py`
- Test `tests/ui/test_project_runtime_ui.py`

**What to implement:**

- A no-project welcome state with:
  - Create project.
  - Open project.
  - Import legacy project.
- In tests, avoid native file dialogs; expose methods that accept paths directly.
- `app.main()` still launches a usable window if no project is supplied.

**References:**

- Current `app.main()` creates `MainWindow()`.
- `LegacyProjectScanner.scan`
- `LegacyProjectImporter.import_project`

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_project_runtime_ui.py tests/ui/test_main_window.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase8ui
```

**Anti-pattern guards:**

- Do not call native file dialogs in unit tests.
- Do not import legacy data into the source directory.
- Do not expose absolute source paths in migration summaries shown in release docs.

## Task 4: Project-backed chapter tree and editor binding

**Files:**

- Modify `src/ai_novel_studio/ui/panels/chapter_sidebar.py`
- Modify `src/ai_novel_studio/ui/panels/manuscript_panel.py`
- Modify `src/ai_novel_studio/ui/main_window.py`
- Test `tests/ui/test_project_runtime_ui.py`

**What to implement:**

- Sidebar can render project-backed volume/chapter view models.
- Selecting a chapter loads:
  - title
  - content
  - revision
  - word count
  - current chapter requirement
- Manuscript save action writes through `ProjectWorkspaceService.save_chapter`.
- Editor dirty state is visible.
- Stale revision error is shown without overwriting editor content.

**References:**

- `ChapterSidebar.chapter_selected`
- `ManuscriptPanel.editor`
- `ChapterRepository.save_content(expected_revision=...)`

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_project_runtime_ui.py tests/integration/storage/test_chapter_repository.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase8binding
```

**Anti-pattern guards:**

- Do not auto-save on every keystroke in the first implementation.
- Do not bypass `ChapterRepository.save_content`.
- Do not silently discard unsaved editor content when selecting another chapter.

## Task 5: Current chapter requirement persistence

**Files:**

- Modify `src/ai_novel_studio/application/project_workspace_service.py`
- Modify `src/ai_novel_studio/ui/main_window.py`
- Modify `src/ai_novel_studio/ui/panels/manuscript_panel.py`
- Test `tests/integration/application/test_project_runtime.py`
- Test `tests/ui/test_project_runtime_ui.py`

**What to implement:**

- Load current chapter requirement through `ChapterRequirementRepository`.
- If a selected chapter has no requirement, create an empty editable requirement record or expose a clear “not created yet” UI state; choose one deterministic behavior and test it.
- Save user edits explicitly.
- Keep lock semantics UI-only until a durable lock field is added in a future schema.

**References:**

- `src/ai_novel_studio/infrastructure/storage/chapter_requirement_repository.py`
- Existing `ManuscriptPanel.requirement_locked()` and `apply_requirement_draft()`

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/application/test_project_runtime.py tests/ui/test_project_runtime_ui.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase8requirements
```

**Anti-pattern guards:**

- Do not treat model-generated requirement as confirmed user instruction until user accepts/edits/saves.
- Do not overwrite locked UI requirement.

## Task 6: Wire Phase 5/6/7 services to open project

**Files:**

- Modify `src/ai_novel_studio/application/project_runtime.py`
- Modify `src/ai_novel_studio/ui/main_window.py`
- Tests:
  - `tests/integration/application/test_project_runtime.py`
  - `tests/ui/test_project_runtime_ui.py`
  - existing Phase 5/6/7 tests

**What to implement:**

- Phase 5:
  - Real project generation preparation and recovery services are available through `ProjectRuntime`.
  - UI generation buttons use current project/chapter IDs instead of demo IDs.
- Phase 6:
  - Deterministic/model audit requests use current chapter ID, current revision, and current hash.
- Phase 7:
  - “工具检索” uses current project `AgentTaskService`.
  - Trace window can display real `AgentRepository.list_turns` and `list_tool_calls` for the last run.

**References:**

- `GenerationContextService.prepare`
- `GenerationAcceptanceService.accept/discard`
- `GenerationRecoveryService.scan`
- `AuditRepository`
- `AgentRepository.list_turns/list_tool_calls`

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/application/test_project_runtime.py tests/ui/test_project_runtime_ui.py tests/ui/test_agent_mode_ui.py tests/integration/application/test_agent_tool_providers.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase8services
```

**Anti-pattern guards:**

- Do not use hard-coded `"ui-current-chapter"` once a project is open.
- Do not let UI widgets instantiate repositories.
- Do not make retrieval tools write memory/canon/clue/style data.

## Task 7: Legacy import UI bridge

**Files:**

- Modify `src/ai_novel_studio/ui/pages/project_welcome.py`
- Modify `src/ai_novel_studio/application/project_workspace_service.py` if needed
- Test `tests/ui/test_project_runtime_ui.py`
- Keep `tests/migration/test_legacy_import.py` passing

**What to implement:**

- A UI-level flow that:
  - scans source with `LegacyProjectScanner.scan(source_root)`;
  - shows preview summary;
  - imports with `LegacyProjectImporter.import_project(preview, destination)`;
  - opens the new V3 project after successful import.
- Tests should call path-accepting methods directly rather than file dialogs.

**References:**

- `LegacyProjectScanner.scan`
- `LegacyProjectImporter.import_project`
- `MigrationReport`

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_project_runtime_ui.py tests/migration/test_legacy_import.py -q -p no:cacheprovider --basetemp C:\CodexPytest\phase8import
```

**Anti-pattern guards:**

- Do not modify source legacy files.
- Do not expose absolute source paths in release docs.
- Do not treat preserved legacy AI summaries as approved V3 memory automatically.

## Task 8: Documentation, version 0.8.0, and final verification

**Files:**

- Create `docs/architecture/0008-project-runtime.md`
- Modify `README.md`
- Modify `pyproject.toml`
- Modify `src/ai_novel_studio/__init__.py`
- Modify `tests/test_package_layout.py`

**What to document:**

- Project lifecycle and lock boundary.
- Demo-data fallback vs opened-project runtime.
- UI widgets remain storage-free.
- Explicit-save policy for manuscript and chapter requirement.
- How Phase 5/6/7 services attach to the opened project.
- What remains future scope: full Agents mode, cloud sync, collaboration, autosave.

**Verification:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_package_layout.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\CodexPytest\phase8full
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/ai_novel_studio
rg -n "s[k]-proj|s[k]-[A-Za-z0-9]{8,}|C:\\\\Users\\\\" README.md docs src tests pyproject.toml
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_release.ps1
```

Expected:

- All tests pass.
- Ruff passes.
- Mypy passes.
- Privacy scan has no high-risk key or private path hits, and the local release privacy blocklist passes.

## Acceptance Criteria

Phase 8 is complete when:

- The app can start without a project and show a create/open/import entry point.
- A newly created V3 project can be opened in the UI.
- An existing V3 project can be opened and migrated to latest schema.
- The sidebar displays real volumes and chapters.
- Selecting a chapter loads real manuscript content and requirement.
- Saving manuscript edits goes through `ChapterRepository.save_content` and preserves history.
- Requirement edits are explicit and do not silently overwrite locked UI state.
- Phase 5 generation runtime no longer depends on demo IDs when a project is open.
- Phase 6 audit uses the selected chapter identity/revision/hash.
- Phase 7 “工具检索” runs against the current project memory and trace tables.
- Legacy import is accessible as an explicit import-to-new-project flow.
- No user manuscripts, backups, exports, real API keys, or private local paths are modified or leaked outside temporary tests.
- Version is `0.8.0`.
- Full pytest, ruff, mypy, and privacy scan pass.

## Suggested Commit Slices

1. `feat: add project workspace service`
2. `feat: build project runtime services`
3. `feat: add project welcome open create import UI`
4. `feat: bind chapter editor to open projects`
5. `feat: persist chapter requirements in project runtime`
6. `feat: wire generation audit and retrieval to open project`
7. `docs: document phase 8 project runtime`

## Notes for the next implementation session

- Start with tests for `ProjectWorkspaceService`; it is the key seam that keeps UI and storage separated.
- Keep the first UI implementation conservative: explicit open/create/import actions, explicit save, and clear error messages.
- If the service wiring becomes too large, stop after Tasks 1-5 with a project-backed editor MVP and leave Tasks 6-8 for the next approved implementation run.
