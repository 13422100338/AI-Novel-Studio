"""Capture Frontend Wave F1/C1/C1.1 screenshots (offscreen, software rendering).

Usage (from the worktree root, using its venv):
    .\\.venv\\Scripts\\python.exe scripts\\capture_frontend_f1_screenshots.py

TextArea mode is used (WebEngine cannot initialize offscreen). Since C1.1 the
TextArea host renders the same CreativeAgentPanel as WebEngine mode, so the
Agent timeline, TextDiffCard, form/change-set cards, selection chip, and the
collapsed AgentDock tab are genuinely exercised and asserted before saving.
The script fails (non-zero exit) when a required component is missing or not
visible, instead of producing misleading screenshots.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import create_engine  # noqa: E402
from ai_novel_studio.ui_qml.bridge.hash_utils import fnv1a_hash  # noqa: E402


def _pump(app: QGuiApplication, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


def _pump_until_agent_idle(app: QGuiApplication, facade: object, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and facade.property("agentBusy") is True:
        app.processEvents()
        time.sleep(0.02)
    _pump(app)


def _wait_until_visible(
    app: QGuiApplication,
    root: QQuickItem,
    name: str,
    timeout: float = 1.0,
) -> None:
    """Pump while the entrance animation settles, then assert visibility.

    Offscreen QML animations only advance while events are processed, so a
    plain sleep before asserting lets the animation stand still. Interleave
    event processing with short sleeps until the component is visible.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _pump(app, 4)
        try:
            _assert_visible(root, name)
            return
        except AssertionError:
            time.sleep(0.02)
    _assert_visible(root, name)


def _find_item(root: QQuickItem, name: str) -> QQuickItem | None:
    """Recursively find a QML item by objectName (covers Repeater delegates)."""
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _find_item(child, name)
        if found is not None:
            return found
    return None


def _assert_visible(root: QQuickItem, name: str) -> QQuickItem:
    """Assert a component exists and is actually visible before a capture."""
    matches = _find_all_items(root, name)
    if not matches:
        raise AssertionError(f"required component '{name}' was not found")
    visible_matches = [
        item for item in matches if item.property("visible") is True
    ]
    if not visible_matches:
        raise AssertionError(f"required component '{name}' is not visible")
    visible_item = next(
        (item for item in visible_matches if item.isVisible()),
        None,
    )
    if visible_item is None:
        raise AssertionError(f"required component '{name}' is hidden by a parent")
    return visible_item


def _find_all_items(root: QQuickItem, name: str) -> list[QQuickItem]:
    """Return every QML item with the given objectName (recursive)."""
    matches: list[QQuickItem] = []
    if root.objectName() == name:
        matches.append(root)
    for child in root.childItems():
        matches.extend(_find_all_items(child, name))
    return matches


def _selection_payload() -> str:
    text = "清晨的雾港"
    return (
        '{"chapterId":"chapter-1","baseRevision":3,"from":0,"to":6,'
        f'"selectedText":"{text}","selectedTextHash":"{fnv1a_hash(text)}"}}'
    )


def main() -> int:
    app = QGuiApplication([])
    app.setApplicationName("AI Novel Studio F1 Screenshot")
    engine = create_engine()
    if not engine.rootObjects():
        print("App.qml failed to load", file=sys.stderr)
        return 1
    engine.rootObjects()[0].show()
    _pump(app)
    quick_windows = [w for w in app.topLevelWindows() if isinstance(w, QQuickWindow)]
    if not quick_windows:
        print("No QQuickWindow available", file=sys.stderr)
        return 1
    window = quick_windows[0]
    content = window.contentItem()
    facade = engine.rootContext().contextProperty("Facade")
    theme = engine.rootContext().contextProperty("Theme")
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "frontend" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    if window.objectName() != "f1Window":
        raise AssertionError("f1Window was not created")

    # 1) Converged default writing shell per theme.
    for theme_name in ("paper", "light", "dark"):
        theme.setTheme(theme_name)
        _pump(app)
        _assert_visible(content, "manuscriptEditor")
        target = out_dir / f"c1-shell-{theme_name}.png"
        saved = window.grabWindow().save(str(target))
        if not saved:
            raise AssertionError(f"failed to save {target.name}")
        print(f"OK   {target.name}")

    # 2) Agent panel expanded with the Mock timeline (TextArea host).
    theme.setTheme("paper")
    facade.toggleAiDrawer(True)
    _pump(app)
    _assert_visible(content, "creativeAgentPanel")
    _assert_visible(content, "agentSendButton")
    target = out_dir / "c1-agent-panel.png"
    saved = window.grabWindow().save(str(target))
    if not saved:
        raise AssertionError(f"failed to save {target.name}")
    print(f"OK   {target.name}")

    # 3) Structured timeline: run a full Mock turn so TextDiffCard, the
    #    confirmation, the form card, and the change-set card all render.
    facade.startAgentTurn("帮我重写这段，让人物说话更自然。")
    _pump_until_agent_idle(app, facade, 8.0)
    for name in ("textDiffCard", "confirmationCard", "formCard", "changeSetCard"):
        _assert_visible(content, name)
    target = out_dir / "c1-agent-timeline-cards.png"
    saved = window.grabWindow().save(str(target))
    if not saved:
        raise AssertionError(f"failed to save {target.name}")
    print(f"OK   {target.name}")

    # 4) Selection-reference chip with a content-validated hash.
    facade.setSelectionReferenceJson(_selection_payload())
    _wait_until_visible(app, content, "selectionReferenceChip")
    assert facade.property("hasSelectionReference") is True
    target = out_dir / "c1-selection-reference-chip.png"
    saved = window.grabWindow().save(str(target))
    if not saved:
        raise AssertionError(f"failed to save {target.name}")
    print(f"OK   {target.name}")

    # 5) Collapsed AgentDock tab (dock shown directly; offscreen TextArea mode).
    facade.clearSelectionReference()
    facade.toggleAiDrawer(False)
    _pump(app)
    dock = _find_item(content, "agentDock")
    if dock is None:
        raise AssertionError("required component 'agentDock' was not found")
    dock.setProperty("visible", True)
    _pump(app)
    _assert_visible(content, "agentExpandTab")
    target = out_dir / "c1-agent-dock-collapsed.png"
    saved = window.grabWindow().save(str(target))
    dock.setProperty("visible", False)
    if not saved:
        raise AssertionError(f"failed to save {target.name}")
    print(f"OK   {target.name}")

    print("All C1.1 screenshots passed component assertions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
