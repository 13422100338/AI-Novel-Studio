# Restore Current Chapter Requirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the directly editable Current Chapter Requirement while keeping Chapter Brief as a separate compiled artifact.

**Architecture:** The manuscript panel owns the visible requirement draft and lock state. Plot chat emits an explicit requirement-draft request; `MainWindow` routes the Phase 2 mock proposal into the manuscript panel only when it is unlocked. Brief remains a separate review dialog and identifies Current Chapter Requirement as its highest-priority human source.

**Tech Stack:** Python 3.11+, PySide6, pytest-qt, existing mock-data and UI signal architecture.

## Global Constraints

- Current Chapter Requirement is a concise human instruction with higher authority than compiled Brief fields.
- Users can directly edit and lock it.
- Plot discussion may propose a draft but cannot overwrite a locked requirement.
- Chapter Brief remains separate and is compiled from the requirement plus structured project context.
- Phase 2 uses mock data and makes no model or persistence claim.

### Task 1: Restore requirement editor and plot handoff

**Files:**
- Modify: `src/ai_novel_studio/ui/demo_data.py`
- Modify: `src/ai_novel_studio/ui/panels/manuscript_panel.py`
- Modify: `src/ai_novel_studio/ui/panels/plot_chat_panel.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Modify: `tests/ui/test_manuscript_and_brief.py`
- Modify: `tests/ui/test_plot_chat.py`

**Interfaces:**
- `ManuscriptPanel.chapter_requirement` is directly editable.
- `toggle_requirement_lock()` changes read-only state and status.
- `apply_requirement_draft(text) -> bool` refuses locked replacement.
- `PlotChatPanel.chapter_requirement_requested` is emitted only by the explicit action.

- [ ] Write failing tests for visible content, editing, lock protection, renamed chat action, and routed mock draft.
- [ ] Run focused tests and confirm failures are caused by the missing requirement API.
- [ ] Implement the minimal UI and local signal routing.
- [ ] Run focused and full tests.

### Task 2: Update design, documentation, build, and desktop copy

**Files:**
- Modify: `docs/superpowers/specs/2026-07-02-director-writer-workflow-design.md`
- Modify: `docs/architecture/0003-phase-2-ui-boundaries.md`
- Modify: `README.md`

- [ ] State the authority chain `plot discussion -> Current Chapter Requirement -> Brief -> prose`.
- [ ] Document Phase 2 mock behavior and the locked-overwrite rule.
- [ ] Run pytest, Ruff, mypy, privacy, Windows build, and EXE startup verification.
- [ ] Commit, merge locally into the active base branch, and synchronize the desktop project without pushing GitHub.
