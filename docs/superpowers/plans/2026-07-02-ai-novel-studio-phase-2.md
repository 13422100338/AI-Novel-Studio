# AI Novel Studio Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved three-pane PySide6 writing workspace and inspectable auxiliary pages with mock data only.

**Architecture:** `MainWindow` only composes focused widgets. Reusable visual primitives live under `ui/widgets`, independent work areas live under `ui/panels`, and secondary workspaces live under `ui/pages`. Phase 2 uses an immutable `WorkspaceDemoData` fixture and local widget signals; model calls, repositories, and persistence wiring remain later phases.

**Tech Stack:** Python 3.11+, PySide6, pytest-qt, Qt Style Sheets, existing pytest/Ruff/mypy/PyInstaller gates.

## Global Constraints

- The layout is a resizable three-pane desktop workspace with black, white, and gray styling.
- The center manuscript editor is the visual focus and remains directly editable.
- The left pane scrolls, its sections collapse, and character state has select/edit/delete controls.
- The plot area uses distinct user and assistant chat bubbles and can detach into its own window.
- The Brief, memory, knowledge, narrative-clue, style-rule, audit, and provenance surfaces use mock data and do not call models.
- Scrollbars must share one draggable-handle style.
- Buttons use restrained rounded styling and monochrome text or glyphs, not colored icon assets.
- UI code cannot call a model, bypass repositories, or invent Phase 3/4 persistence behavior.
- Public files, commits, logs, and build artifacts must not expose private identity or machine paths.

---

### Task 1: Theme, demo data, and reusable widgets

**Files:**
- Create: `src/ai_novel_studio/ui/theme.py`
- Create: `src/ai_novel_studio/ui/demo_data.py`
- Create: `src/ai_novel_studio/ui/widgets/collapsible_section.py`
- Create: `src/ai_novel_studio/ui/widgets/chat_bubble.py`
- Create: `src/ai_novel_studio/ui/widgets/metric_chip.py`
- Create: `src/ai_novel_studio/ui/widgets/__init__.py`
- Test: `tests/ui/test_ui_primitives.py`

**Interfaces:**
- `application_stylesheet() -> str` supplies the complete monochrome QSS.
- `WorkspaceDemoData.sample() -> WorkspaceDemoData` supplies immutable mock volumes, chapters, characters, Brief fields, chat messages, memory rows, style rules, and audit findings.
- `CollapsibleSection(title, content)` exposes `set_expanded(bool)` and `is_expanded()`.
- `ChatBubble(role, text)` exposes role through the `chatRole` Qt property.
- `MetricChip(label, value)` exposes `set_value(str)`.

- [ ] Write primitive tests that require a non-empty themed scrollbar handle, immutable sample data, collapsible visibility, role-specific bubbles, and metric updates.
- [ ] Run the focused tests and observe missing-module failures.
- [ ] Implement the smallest reusable components and object names needed by tests.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add phase 2 UI primitives and theme`.

### Task 2: Top bar, chapter sidebar, and three-pane shell

**Files:**
- Create: `src/ai_novel_studio/ui/panels/top_bar.py`
- Create: `src/ai_novel_studio/ui/panels/chapter_sidebar.py`
- Create: `src/ai_novel_studio/ui/panels/__init__.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Test: `tests/ui/test_workspace_shell.py`

**Interfaces:**
- `TopBar` shows project/volume, estimated input tokens, output limit, cost, memory state, and a visible settings button.
- `ChapterSidebar` is a `QScrollArea` containing collapsible chapter and character sections; it emits `chapter_selected(str)` and supports local character selection, editing, and deletion.
- `MainWindow.workspace_splitter` contains exactly `ChapterSidebar`, a center placeholder, and a right placeholder with stretch emphasis on the center.

- [ ] Write tests for the three panes, splitter handles, metrics, settings visibility, scrollability, collapsible sections, and character menu interactions.
- [ ] Run the focused tests and observe failures because the shell components are absent.
- [ ] Implement top bar, left pane, and splitter composition with stable object names and accessible labels.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: build resizable three-pane workspace shell`.

### Task 3: Manuscript editor and Chapter Brief review

**Files:**
- Create: `src/ai_novel_studio/ui/panels/manuscript_panel.py`
- Create: `src/ai_novel_studio/ui/pages/brief_dialog.py`
- Create: `src/ai_novel_studio/ui/pages/__init__.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Test: `tests/ui/test_manuscript_and_brief.py`

**Interfaces:**
- `ManuscriptPanel` provides chapter title, mode, target words, output-token limit, font-size control, editable `QPlainTextEdit`, Brief/audit/reference actions, word count, save state, and pipeline state.
- Font-size changes update the editor immediately without changing content.
- `BriefDialog` displays status, source fingerprint summary, warnings, editable structured sections, source badges, and freeze/clone actions; local actions only change mock state.

- [ ] Write tests for editability, output limit above 3000, font sizing, word count, Brief opening, draft-to-frozen transition, and stale clone behavior.
- [ ] Run focused tests and observe missing widgets.
- [ ] Implement the center panel and model-free Brief dialog.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add manuscript and Brief review workspace`.

### Task 4: Chat bubbles and detached plot workspace

**Files:**
- Create: `src/ai_novel_studio/ui/panels/plot_chat_panel.py`
- Create: `src/ai_novel_studio/ui/pages/detached_chat_window.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Test: `tests/ui/test_plot_chat.py`

**Interfaces:**
- `PlotChatPanel` renders scrollable left/right bubbles, a multiline composer, send action, “generate Brief draft” action, model label, and detach action.
- Sending appends a user bubble and clears the composer; Phase 2 generates no assistant network reply.
- `DetachedChatWindow` hosts the same conversation presentation and a local copy of current messages without transferring widget ownership from the main window.

- [ ] Write tests for bubble roles and alignment, send behavior, no fabricated assistant response, Brief signal, and detached-window creation.
- [ ] Run focused tests and observe failures.
- [ ] Implement the chat panel and detached view with safe local signals.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add detachable plot chat workspace`.

### Task 5: Memory, style, and audit pages

**Files:**
- Create: `src/ai_novel_studio/ui/pages/memory_window.py`
- Create: `src/ai_novel_studio/ui/pages/style_rules_window.py`
- Create: `src/ai_novel_studio/ui/pages/audit_window.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Test: `tests/ui/test_auxiliary_pages.py`

**Interfaces:**
- `MemoryWindow` explains the memory system and provides editable tabs for compressed history, character state, character knowledge, reader knowledge, canon, narrative clues, and stale dependencies.
- `StyleRulesWindow` separates book voice, scene rules, character voice, anti-pattern limits, immutable human samples, and model candidates.
- `AuditWindow` separates deterministic and model findings, shows evidence and severity, and exposes disabled model-dependent repair actions plus local accept/reject mock controls.
- Main-window actions open one reusable instance of each page.

- [ ] Write tests for required tabs, explanation text, editable mock records, immutable sample display, finding categories, and reusable page instances.
- [ ] Run focused tests and observe failures.
- [ ] Implement secondary pages and main-window routing.
- [ ] Run focused and full tests.
- [ ] Commit as `feat: add memory style and audit workspaces`.

### Task 6: Visual polish, accessibility, documentation, and release gates

**Files:**
- Modify: `src/ai_novel_studio/ui/theme.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Modify: `README.md`
- Create: `docs/architecture/0003-phase-2-ui-boundaries.md`
- Create: `tests/ui/test_accessibility_and_layout.py`

**Interfaces:**
- All primary actions have tooltips or accessible names, keyboard focus remains visible, and minimum panel widths prevent controls collapsing into unusable strips.
- Main window can render at 1366×768 and 1920×1080 without hiding the editor or composer.
- Documentation states which controls are mock-only until later phases.

- [ ] Write tests for accessible names, minimum widths, panel stretch factors, scroll-area resizability, and model-free controls.
- [ ] Run tests and observe missing accessibility/layout guarantees.
- [ ] Refine QSS and layout, update documentation, and render a representative screenshot for visual inspection.
- [ ] Run full pytest, Ruff, mypy, privacy scan, Windows build, and EXE startup verification.
- [ ] Commit as `docs: document phase 2 UI boundaries`.

