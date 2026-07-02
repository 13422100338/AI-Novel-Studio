# ADR 0003: Phase 2 UI boundaries

## Status

Accepted on 2026-07-02.

## Decision

Phase 2 implements the approved three-pane PySide6 workspace with immutable demonstration data. The
window is decomposed into reusable widgets, focused panels, and secondary pages:

```text
ui/
├── main_window.py
├── theme.py
├── demo_data.py
├── widgets/
│   ├── chat_bubble.py
│   ├── collapsible_section.py
│   └── metric_chip.py
├── panels/
│   ├── top_bar.py
│   ├── chapter_sidebar.py
│   ├── manuscript_panel.py
│   └── plot_chat_panel.py
└── pages/
    ├── brief_dialog.py
    ├── detached_chat_window.py
    ├── memory_window.py
    ├── style_rules_window.py
    ├── audit_window.py
    └── settings_dialog.py
```

`MainWindow` composes these units and routes local Qt signals. It does not own detailed panel
layouts, call a model, read a project database, or write manuscript files.

## Interaction boundary

The following Phase 2 interactions are local and intentionally temporary:

- choosing, editing, or deleting a character in the sidebar;
- editing the sample manuscript and font size;
- editing and locking Current Chapter Requirement;
- routing the plot-chat demo action into an unlocked requirement while protecting a locked one;
- sending a user chat bubble;
- freezing, marking stale, or cloning the sample Chapter Brief;
- editing sample memory and AI style-candidate text;
- opening reusable memory, style, audit, settings, Brief, and detached-chat windows.

Closing the program discards these demonstration changes. This is deliberate: Phase 2 validates
layout and interaction contracts before application services bind widgets to repositories.

## Deferred controls

- Prose generation is disabled with a Phase 3 tooltip.
- Plot chat uses a clearly labeled demonstration requirement draft until the Phase 3 model gateway
  is connected.
- Audit repair is disabled until a model gateway is present.
- Model connection fields are previews and cannot store an API key.
- Token and price chips are labeled demonstration values.
- Chapter and volume mutations do not persist until application controllers are introduced.
- Memory, knowledge, clue, style, audit, and provenance persistence belongs to later schema
  migrations and repositories.

No disabled control may fail silently: it must explain the phase that enables it. No enabled Phase
2 control may imply that a network request, model generation, or durable save occurred.

## Layout and accessibility

- The three panes use a non-collapsible horizontal splitter with the manuscript as the stretch pane.
- Minimum widths prevent the character editor or chat composer from becoming unusable strips.
- The sidebar and conversation are independently scrollable with the shared draggable-handle theme.
- All primary buttons and editors have accessible names; keyboard focus uses a visible border.
- Buttons use monochrome text/glyphs and restrained rounded styling without colored icon assets.
- Native Windows rendering is the visual reference. Offscreen Qt environments may not enumerate
  system CJK fonts, so release QA also captures a native screenshot.

## Consequences

Phase 3 can replace mock metrics and disabled model controls without restructuring the window.
Phase 4 can bind memory and knowledge pages to repositories. Phase 5 can bind Brief and generation
signals to application controllers. The UI remains testable without network access or API keys.
