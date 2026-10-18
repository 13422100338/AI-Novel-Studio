"""Capture C1.3 post-fix screenshots from the real App.qml (offscreen).

The real TextArea-mode shell is used; the drawer width is driven through the
actual SlidingDrawer component so the same CreativeAgentPanel is verified at
360 / 420 / 520px. Every capture is preceded by geometry assertions: all
instantiated delegates have height > 0, consecutive delegates do not overlap,
and the last delegate bottom fits inside the ListView contentHeight.
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
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto  # noqa: E402

_CARD_NAMES = (
    "agentTextBlock",
    "agentRunStatus",
    "toolCallCard",
    "choiceCard",
    "textDiffCard",
    "confirmationCard",
    "formCard",
    "changeSetCard",
)


def _find_all(root: QQuickItem, name: str) -> list[QQuickItem]:
    matches: list[QQuickItem] = []
    if root.objectName() == name:
        matches.append(root)
    for child in root.childItems():
        matches.extend(_find_all(child, name))
    return matches


def _pump(app: QGuiApplication, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


def _run_agent_turn(app: QGuiApplication, facade: object, prompt: str) -> None:
    facade.startAgentTurn(prompt)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and facade.property("agentBusy") is True:
        app.processEvents()
        time.sleep(0.02)
    _pump(app, 20)


def _assert_geometry(
    content: QQuickItem,
    timeline: QQuickItem,
    visible_content: QQuickItem,
) -> None:
    """Fail before saving if any vertical layout invariant is broken."""
    rows: list[tuple[str, QQuickItem, QQuickItem]] = []
    for name in _CARD_NAMES:
        for card in _find_all(content, name):
            loader = card.parentItem()
            if loader is not None and loader.parentItem() is visible_content:
                rows.append((name, loader, card))
    rows.sort(key=lambda row: row[1].y())
    assert rows, "no timeline delegates instantiated"
    prev_bottom: float | None = None
    for kind, loader, _ in rows:
        assert loader.height() > 0, f"{kind} delegate height <= 0"
        y = loader.y()
        if prev_bottom is not None:
            assert y >= prev_bottom + 8 - 2, (
                f"{kind} overlaps previous row: y={y} prev_bottom={prev_bottom}"
            )
        prev_bottom = y + loader.height()
    assert prev_bottom is not None
    content_height = timeline.property("contentHeight")
    assert prev_bottom <= content_height + 1, (
        f"last delegate bottom {prev_bottom} exceeds contentHeight {content_height}"
    )


def main() -> int:
    app = QGuiApplication([])
    app.setApplicationName("AI Novel Studio C1.3 After")
    engine = create_engine()
    if not engine.rootObjects():
        print("App.qml failed to load", file=sys.stderr)
        return 1
    root = engine.rootObjects()[0]
    root.show()
    _pump(app)
    quick_windows = [w for w in app.topLevelWindows() if isinstance(w, QQuickWindow)]
    if not quick_windows:
        print("No QQuickWindow available", file=sys.stderr)
        return 1
    window = quick_windows[0]
    content = window.contentItem()
    facade = engine.rootContext().contextProperty("Facade")
    model = facade.property("agentTimeline")
    drawer = _find_all(content, "slidingDrawer")[0]
    panel = next(item for item in _find_all(content, "creativeAgentPanel") if item.isVisible())
    timeline = next(item for item in _find_all(content, "agentTimeline") if item.isVisible())
    visible_content = timeline.property("contentItem")
    # Instantiate every delegate so geometry assertions cover the full timeline.
    panel.setProperty("timelineCacheBuffer", 6000)

    out_dir = Path(__file__).resolve().parent.parent / "docs" / "frontend" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    facade.toggleAiDrawer(True)
    _pump(app)

    for width in (520, 420, 360):
        model.clear()
        drawer.setProperty("drawerWidth", width)
        _pump(app, 20)
        _run_agent_turn(app, facade, "扩写：让人物说话更自然，并保留雾港清晨的意象。")
        _run_agent_turn(app, facade, "精简：把这一段压缩到一半长度。")
        _run_agent_turn(app, facade, "重写：让林默的对话更有克制感。")
        _assert_geometry(content, timeline, visible_content)
        target = out_dir / f"c1.3-after-real-multi-turn-{width}px.png"
        if not window.grabWindow().save(str(target)):
            raise AssertionError(f"failed to save {target.name}")
        print(f"OK   {target.name}")

    # Long diff + confirmation (two rounds of events).
    model.clear()
    drawer.setProperty("drawerWidth", 420)
    _pump(app)
    long_current = "当前：" + "雾港的清晨还浸在灰蓝色的光线里，" * 30
    long_draft = "修改：" + "灰蓝色光线下的雾港尚未苏醒，" * 30
    for index in range(2):
        model.append_item(
            AgentTimelineItemDto(
                id=f"ld-user-{index}",
                kind="user_text",
                text="帮我重写这段长文本，保留全部意象。",
            )
        )
        model.append_item(
            AgentTimelineItemDto(
                id=f"ld-diff-{index}",
                kind="text_diff",
                label="修改对比 · 长文",
                current_text=long_current,
                draft_text=long_draft,
            )
        )
        model.append_item(
            AgentTimelineItemDto(
                id=f"ld-conf-{index}",
                kind="confirmation",
                label="确认操作",
                text="替换选区 / 再次修改 / 放弃",
            )
        )
    _pump(app, 40)
    _assert_geometry(content, timeline, visible_content)
    target = out_dir / "c1.3-after-long-diff.png"
    if not window.grabWindow().save(str(target)):
        raise AssertionError(f"failed to save {target.name}")
    print(f"OK   {target.name}")

    # Form + change-set (two rounds).
    model.clear()
    drawer.setProperty("drawerWidth", 360)
    _pump(app)
    for index in range(2):
        model.append_item(
            AgentTimelineItemDto(
                id=f"fc-form-{index}",
                kind="form_card",
                label="补充设定 · 人物关系",
                text="请补充人物关系设定（Mock 表单，不写入项目）。",
                field_labels=("人物名", "关系", "备注"),
                field_values=("林默", "旧友", "待确认"),
            )
        )
        model.append_item(
            AgentTimelineItemDto(
                id=f"fc-change-{index}",
                kind="change_set",
                label="变更提案",
                target="人物 · 林默",
                operation="更新",
                before_text="码头工人",
                after_text="退役水手",
                risk="高",
                reason="Mock 提案：人物设定与第一章背景冲突",
            )
        )
    _pump(app, 40)
    _assert_geometry(content, timeline, visible_content)
    target = out_dir / "c1.3-after-form-and-changeset.png"
    if not window.grabWindow().save(str(target)):
        raise AssertionError(f"failed to save {target.name}")
    print(f"OK   {target.name}")

    print("All C1.3 after screenshots passed geometry assertions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
