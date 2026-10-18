"""Capture C1.2 before/after responsive-panel screenshots (offscreen).

Usage (from the worktree root, using its venv):
    .\\.venv\\Scripts\\python.exe scripts\\capture_frontend_c12_before_after.py

"Before" emulates the pre-C1.2 delegate width rule (cards use the full
ListView width, i.e. they extend under the vertical scrollbar); "after" is the
fixed rule (delegate width excludes the scrollbar + 12px safety margin).
Both variants render the same seeded timeline at 360/420/520px so the pair is
directly comparable.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types  # noqa: E402
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto  # noqa: E402
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (  # noqa: E402
    MockNovelStudioFacade,
)
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider  # noqa: E402


def _find_item(root: QQuickItem, name: str) -> QQuickItem | None:
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _find_item(child, name)
        if found is not None:
            return found
    return None


def _pump(app: QGuiApplication, rounds: int = 8) -> None:
    for _ in range(rounds):
        app.processEvents()


def _seed_timeline(facade: MockNovelStudioFacade) -> None:
    model = facade.property("agentTimeline")
    items = (
        AgentTimelineItemDto(
            id="seed-user",
            kind="user_text",
            text="帮我重写这段，让人物说话更自然，并保留雾港清晨的意象。",
        ),
        AgentTimelineItemDto(
            id="seed-tool",
            kind="tool_call",
            label="read_selection",
            text="读取正文选区与章节修订：第一章 雾港的清晨（修订 3）",
            state="COMPLETED",
        ),
        AgentTimelineItemDto(
            id="seed-diff",
            kind="text_diff",
            label="修改对比 · 较长标题",
            current_text="当前：" + "清晨的雾港还浸在灰蓝色的光线里，" * 4,
            draft_text="修改：" + "灰蓝色光线下的雾港尚未苏醒，" * 4,
            state="PENDING",
        ),
        AgentTimelineItemDto(
            id="seed-confirm",
            kind="confirmation",
            label="确认操作",
            text="替换选区 / 再次修改 / 放弃（这是一段很长的确认说明文本）。",
            state="PENDING",
        ),
        AgentTimelineItemDto(
            id="seed-form",
            kind="form_card",
            label="补充设定 · 人物关系",
            text="请补充人物关系设定（Mock 表单，不写入项目）。",
            field_labels=("人物名", "关系", "备注"),
            field_values=("林默", "旧友", "待确认"),
            state="PENDING",
        ),
        AgentTimelineItemDto(
            id="seed-change",
            kind="change_set",
            label="变更提案",
            target="人物 · 林默",
            operation="更新",
            before_text="码头工人" + "很长的旧值，" * 5,
            after_text="退役水手" + "很长的新值，" * 5,
            risk="高",
            reason="Mock 提案：人物设定与第一章背景冲突" + "补充说明，" * 8,
            state="PENDING",
        ),
    )
    for item in items:
        model.append_item(item)


def main() -> int:
    app = QGuiApplication([])
    app.setApplicationName("AI Novel Studio C1.2 Before/After")
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "frontend" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    for variant, full_width in (("before", True), ("after", False)):
        engine = QQmlApplicationEngine()
        engine.addImportPath(str(app_qml_path().parent))
        facade = MockNovelStudioFacade()
        register_frontend_types(engine, facade, ThemeProvider())
        _seed_timeline(facade)
        full_width_qml = b"true" if full_width else b"false"
        engine.loadData(
            (
                b"""
                import QtQuick
                import QtQuick.Controls
                import "components"
                ApplicationWindow {
                    id: win
                    width: 520
                    height: 760
                    visible: true
                    CreativeAgentPanel {
                        anchors.fill: parent
                        timelineDelegateFullWidth: """
                + full_width_qml
                + b"""
                    }
                }
                """
            ),
            QUrl.fromLocalFile(str(app_qml_path().parent / "ba-harness.qml")),
        )
        assert engine.rootObjects(), f"{variant} harness failed to load"
        root = engine.rootObjects()[0]
        root.show()
        _pump(app)
        quick_windows = [w for w in app.topLevelWindows() if isinstance(w, QQuickWindow)]
        assert quick_windows, "no QQuickWindow"
        window = quick_windows[-1]
        content = window.contentItem()
        for width in (520, 420, 360):
            root.setWidth(width)
            _pump(app)
            time.sleep(0.05)
            _pump(app)
            panel = _find_item(content, "creativeAgentPanel")
            timeline = _find_item(content, "agentTimeline")
            if panel is None or timeline is None:
                raise AssertionError(f"panel/timeline missing: {variant} {width}px")
            target = out_dir / f"c1.2-{variant}-{width}px.png"
            saved = window.grabWindow().save(str(target))
            if not saved:
                raise AssertionError(f"failed to save {target.name}")
            print(f"OK   {target.name}")
        engine.deleteLater()
        app.processEvents()

    print("C1.2 before/after screenshots captured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
