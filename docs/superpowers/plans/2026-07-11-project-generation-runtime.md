# Project Generation Runtime Implementation Plan

> **For implementation workers:** execute task-by-task with test-driven development. Do not modify user manuscripts, project databases, backups, exports, or credentials during tests. Do not push to GitHub unless explicitly requested.

**Goal:** Make every opened V3 project provide a real Phase 5 prose generation, checkpoint, recovery, discard, and acceptance runtime to the desktop UI.

**Architecture:** Add one application-layer QObject that composes existing Phase 5 repositories and services without moving storage logic into widgets. `ProjectRuntime` owns this adapter; `MainWindow` only selects the current chapter and binds signals.

**Tech Stack:** Python 3.11+, PySide6, SQLite repositories, pytest-qt.

## Task 1: Define the project generation runtime contract

- [ ] Add a failing integration test proving `ProjectRuntime` exposes a generation runtime tied to the current project.
- [ ] Add a failing UI test proving Basic-mode generation is enabled after opening a real project and creates a run for the selected chapter.
- [ ] Run focused tests and confirm the runtime is absent.

## Task 2: Compose existing Phase 5 services

- [ ] Create `application/project_generation_runtime.py`.
- [ ] Compose context preparation, message storage, streaming service, coordinator, acceptance, and recovery.
- [ ] Resolve the configured prose route and model capabilities through the existing model configuration.
- [ ] Preserve current chapter revision for safe acceptance.

## Task 3: Bind the runtime to the desktop UI

- [ ] Add the generation runtime to `ProjectRuntime`.
- [ ] Bind it when `MainWindow` opens or creates a project.
- [ ] Select the current chapter and report frozen-Brief availability.
- [ ] Start with a clean AI draft area, display recovered checkpoints, and refresh revision state after acceptance.
- [ ] Forward prose usage into the top-bar aggregate usage snapshot.

## Task 4: Verify

- [ ] Run project runtime, generation UI, and Phase 5 focused tests.
- [ ] Run the full suite, Ruff, Mypy, and launch smoke test.
- [ ] Clean test-only temporary directories.
