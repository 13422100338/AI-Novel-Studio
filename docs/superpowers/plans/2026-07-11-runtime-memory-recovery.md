# Runtime and Memory Recovery Implementation Plan

> **For implementation workers:** execute this plan task-by-task. Use test-driven development. Do not modify user manuscripts, project databases, backups, exports, or API credentials during verification. Do not push to GitHub unless explicitly requested.

**Goal:** Restore UI construction compatibility and make imported-manuscript memory rebuilding recover from a previous fallback summary.

**Architecture:** Keep the UI independent of a concrete model gateway by injecting or safely resolving the optional memory analyzer. Keep memory rebuilding deterministic when a model is unavailable, but distinguish a local fallback summary from a model-derived candidate so a later successful analysis can replace it and add missing candidate records.

**Tech Stack:** Python 3.11+, PySide6, pytest, existing SQLite repositories.

## Task 1: Decouple MainWindow from a concrete gateway

**Files:**

- Modify: `tests/ui/test_agent_mode_ui.py`
- Modify: `tests/ui/test_plot_chat.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`

**Steps:**

- [ ] Add a regression test proving a coordinator-only runtime can construct `MainWindow` and retain the fallback memory service.
- [ ] Run the focused UI tests and observe the existing `gateway` attribute error.
- [ ] Resolve the memory analyzer only when the supplied runtime exposes a compatible gateway; keep it optional for coordinator-only test runtimes.
- [ ] Re-run the focused UI tests.

## Task 2: Allow fallback summaries to be upgraded

**Files:**

- Modify: `tests/integration/application/test_manuscript_memory_build_service.py`
- Modify: `src/ai_novel_studio/application/manuscript_memory_build_service.py`

**Steps:**

- [ ] Add a regression test: a first fallback run followed by a model-backed run for the same chapter creates a model summary and character-state candidates.
- [ ] Run the focused integration test and observe that the current-summary shortcut skips the model-backed pass.
- [ ] Treat only a current model-derived summary as complete; let a fallback candidate be superseded through the existing summary repository.
- [ ] Re-run the focused integration test.

## Task 3: Verification and release hygiene report

**Files:**

- No product-data writes.

**Steps:**

- [ ] Run affected UI and memory tests using an explicit temporary test directory.
- [ ] Run Ruff and Mypy on modified files.
- [ ] Run the full suite after the targeted tests are green.
- [ ] Report the remaining P0 tasks: project runtime composition, real Brief/audit wiring, and environment/privacy cleanup.
