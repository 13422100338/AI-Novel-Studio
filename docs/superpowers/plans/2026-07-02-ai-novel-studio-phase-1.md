# AI Novel Studio Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable V3 project data kernel and a read-only legacy-project importer with verifiable reports.

**Architecture:** Domain dataclasses own stable UUID identities and invariants. SQLite stores structure and revision metadata while UTF-8 Markdown files remain the only canonical manuscript content. Application services coordinate repositories, atomic filesystem writes, backup, integrity checks, and read-only legacy import.

**Tech Stack:** Python 3.11+, standard-library `sqlite3`, `zipfile`, `xml.etree.ElementTree`, `dataclasses`, pytest, Ruff, mypy.

## Global Constraints

- V3 is a clean-room implementation and must not copy legacy source code or Git history.
- Markdown/UTF-8 is the only canonical manuscript format; DOCX and TXT are import/export formats.
- Cross-module identity uses UUIDs; titles and declared chapter numbers are editable metadata.
- Database changes are transactional and schema migrations are versioned and idempotent.
- Manuscript writes use a temporary file followed by atomic replacement.
- Replacing chapter content creates a recoverable version first; deleting a chapter moves it to trash.
- Legacy import is read-only and produces a preview plus a final verification report.
- Public files, commits, logs, and build artifacts must not expose private identity or machine paths.

---

### Task 1: Stable domain identities and records

**Files:**
- Create: `src/ai_novel_studio/domain/identifiers.py`
- Create: `src/ai_novel_studio/domain/project.py`
- Create: `src/ai_novel_studio/domain/volume.py`
- Create: `src/ai_novel_studio/domain/chapter.py`
- Test: `tests/unit/domain/test_records.py`

**Interfaces:**
- Produces `new_id() -> str` and `validate_id(value: str) -> str`.
- Produces immutable `Project`, `Volume`, `Chapter`, and `ChapterVersion` records.

- [ ] Write tests proving generated IDs are UUIDs, malformed IDs are rejected, and record construction preserves editable metadata independently from identity.
- [ ] Run the focused tests and observe the expected import failure.
- [ ] Implement the minimal typed records and validation.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: define stable project domain records`.

### Task 2: Project layout and versioned SQLite database

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/project_layout.py`
- Create: `src/ai_novel_studio/infrastructure/storage/database.py`
- Create: `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
- Create: `src/ai_novel_studio/infrastructure/storage/project_repository.py`
- Test: `tests/integration/storage/test_project_repository.py`

**Interfaces:**
- Produces `ProjectLayout.at(root: Path)`, `Database.connect()`, and `MigrationManager.migrate()`.
- Produces `ProjectRepository.create(root, title)` and `ProjectRepository.open(root)`.
- Project creation writes `project.json`, creates required directories, initializes SQLite, and inserts one default volume.

- [ ] Write tests for project creation, schema version, idempotent migration, reopen, and duplicate/non-empty target rejection.
- [ ] Run focused tests and observe failure because storage modules do not exist.
- [ ] Implement layout, SQLite connection pragmas, migration ledger, schema, manifest serialization, and repository lifecycle.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add versioned project storage kernel`.

### Task 3: Safe volume and chapter lifecycle

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/atomic_file.py`
- Create: `src/ai_novel_studio/infrastructure/storage/chapter_repository.py`
- Test: `tests/integration/storage/test_chapter_repository.py`

**Interfaces:**
- Produces volume create/list/delete with explicit chapter reassignment.
- Produces chapter create/list/read/save/delete/restore.
- `save_content` snapshots the previous Markdown into `.ai_pipeline/history` before replacement and increments revision.
- `delete_chapter` moves canonical content into `.ai_pipeline/trash` and marks the row deleted without destroying identity.

- [ ] Write tests for UTF-8 Markdown creation, atomic overwrite, hash-backed history, chapter ordering, delete/restore, and volume deletion with reassignment.
- [ ] Run focused tests and verify expected missing-module failure.
- [ ] Implement minimal transactional metadata changes and atomic file operations.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add recoverable chapter lifecycle`.

### Task 4: Integrity checks, single-writer lock, and backup

**Files:**
- Create: `src/ai_novel_studio/infrastructure/storage/integrity.py`
- Create: `src/ai_novel_studio/infrastructure/storage/project_lock.py`
- Create: `src/ai_novel_studio/infrastructure/storage/backup_service.py`
- Test: `tests/integration/storage/test_recovery_services.py`

**Interfaces:**
- Produces `IntegrityChecker.check() -> IntegrityReport` with structured issues.
- Produces `ProjectLock.acquire()`/`release()` using an exclusive lock file containing no private path.
- Produces `BackupService.create_backup()` as a timestamped ZIP and `prune(keep)`.

- [ ] Write tests for missing manuscript detection, hash mismatch detection, competing writer rejection, backup content, and retention pruning.
- [ ] Run focused tests and observe failure.
- [ ] Implement the checker, lock, deterministic ZIP inclusion rules, and pruning.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add project integrity and backup services`.

### Task 5: Read-only legacy preview and importer

**Files:**
- Create: `src/ai_novel_studio/application/legacy_import/__init__.py`
- Create: `src/ai_novel_studio/application/legacy_import/models.py`
- Create: `src/ai_novel_studio/application/legacy_import/docx_reader.py`
- Create: `src/ai_novel_studio/application/legacy_import/scanner.py`
- Create: `src/ai_novel_studio/application/legacy_import/importer.py`
- Test: `tests/migration/test_legacy_import.py`

**Interfaces:**
- Produces `LegacyProjectScanner.scan(root) -> MigrationPreview` without modifying the source.
- Produces `LegacyProjectImporter.import_project(preview, destination) -> MigrationReport`.
- DOCX extraction uses only ZIP/XML standard-library parsing; corrupt/missing documents become explicit report issues.
- Duplicate names and numbers are accepted because destination identity is UUID-based.

- [ ] Build synthetic legacy fixtures in tests and assert preview counts, missing/corrupt DOCX issues, source immutability, Markdown conversion, stable IDs, and content hashes.
- [ ] Run focused tests and observe failure.
- [ ] Implement defensive JSON scanning, DOCX paragraph extraction, import coordination, and JSON report writing.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add verified legacy project importer`.

### Task 6: Public API, diagnostics, and phase verification

**Files:**
- Modify: `src/ai_novel_studio/infrastructure/storage/__init__.py`
- Modify: `README.md`
- Create: `docs/architecture/0002-project-data-format.md`
- Test: `tests/test_package_layout.py`

**Interfaces:**
- Storage package exports the repositories and safety services intended for later application/UI phases.
- Documentation defines the project tree, canonical-content rule, recovery behavior, and migration limitations.

- [ ] Extend package-layout tests to import all Phase 1 modules.
- [ ] Run tests and observe failures before exports/documented APIs are added.
- [ ] Add exports and documentation, without adding Phase 2 UI or Phase 3 model behavior.
- [ ] Run the complete pytest suite, Ruff, mypy, privacy scan, and Windows build verification.
- [ ] Review the plan line-by-line, record any deferred items, and commit as `docs: document phase 1 project data format`.

