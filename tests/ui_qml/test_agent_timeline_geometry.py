"""C1.3: Agent timeline vertical geometry tests.

These tests assert that every timeline delegate has a real height, that
delegates are laid out in order without overlap, that dynamic appends and
multi-turn Mock runs keep the list consistent, and that Flow-wrapped buttons
and long text grow the parent card instead of overlapping.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider

_ACTIVE_ENGINES: list[QQmlApplicationEngine] = []
_ACTIVE_FRONTS: list[tuple[MockNovelStudioFacade, ThemeProvider]] = []
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
_SPACING = 8
_TOLERANCE = 2.0


@pytest.fixture(autouse=True)
def _delete_active_engines() -> None:
    """Destroy QML engines deterministically after each test."""
    yield
    for engine in _ACTIVE_ENGINES:
        engine.deleteLater()
    _ACTIVE_ENGINES.clear()
    _ACTIVE_FRONTS.clear()


def _find_all(root: QQuickItem, name: str) -> list[QQuickItem]:
    matches: list[QQuickItem] = []
    if root.objectName() == name:
        matches.append(root)
    for child in root.childItems():
        matches.extend(_find_all(child, name))
    return matches


def _load_panel(
    qtbot: QtBot,
    facade: MockNovelStudioFacade,
    *,
    width: int = 420,
    height: int = 900,
) -> tuple[QQmlApplicationEngine, QQuickItem, QQuickItem, QQuickWindow]:
    """Load the real CreativeAgentPanel with all delegates instantiated."""
    engine = QQmlApplicationEngine()
    _ACTIVE_ENGINES.append(engine)
    engine.addImportPath(str(Path(app_qml_path()).parent))
    theme = ThemeProvider()
    register_frontend_types(engine, facade, theme)
    # Keep the Python wrappers alive; otherwise the QObjects can be garbage
    # collected and QML bindings fail with "Cannot read property 'tokens'".
    _ACTIVE_FRONTS.append((facade, theme))
    harness = (
        b"""
        import QtQuick
        import QtQuick.Controls
        import "components"
        ApplicationWindow {
            id: win
            width: %d
            height: %d
            visible: true
            CreativeAgentPanel {
                anchors.fill: parent
                timelineCacheBuffer: 6000
            }
        }
        """
        % (width, height)
    )
    engine.loadData(
        harness,
        QUrl.fromLocalFile(str(Path(app_qml_path()).parent / "geometry-harness.qml")),
    )
    assert engine.rootObjects(), "geometry harness failed to load"
    root = engine.rootObjects()[0]
    root.show()
    qtbot.waitUntil(lambda: root.width() > 0, timeout=5000)
    content = root.contentItem()
    qtbot.waitUntil(lambda: content.width() > 0, timeout=5000)
    timeline = _find_all(content, "agentTimeline")[0]
    return engine, content, timeline, root


def _delegates(content: QQuickItem) -> list[tuple[str, QQuickItem, QQuickItem]]:
    """Collect (kind, loader, card) for every instantiated card, by y order."""
    rows: list[tuple[str, QQuickItem, QQuickItem]] = []
    for name in _CARD_NAMES:
        for card in _find_all(content, name):
            loader = card.parentItem()
            if loader is not None:
                rows.append((name, loader, card))
    rows.sort(key=lambda row: row[1].y())
    return rows


def _assert_no_overlap(rows: list[tuple[str, QQuickItem, QQuickItem]]) -> float:
    """Assert heights > 0, delegate covers the card, and rows do not overlap."""
    assert rows, "no timeline delegates were instantiated"
    prev_bottom: float | None = None
    for kind, loader, card in rows:
        assert loader.height() > 0, f"{kind} delegate height <= 0"
        assert card.height() > 0, f"{kind} card height <= 0"
        assert card.implicitHeight() > 0, f"{kind} card implicitHeight <= 0"
        assert (
            loader.height() >= card.implicitHeight() - 0.5
        ), f"{kind} delegate {loader.height()} < loaded implicitHeight {card.implicitHeight()}"
        y = loader.y()
        if prev_bottom is not None:
            assert y >= prev_bottom + _SPACING - _TOLERANCE, (
                f"{kind} overlaps previous row: y={y} prev_bottom={prev_bottom}"
            )
        prev_bottom = y + loader.height()
    return prev_bottom


def _assert_fits_horizontally(content: QQuickItem, timeline: QQuickItem) -> None:
    for _, loader, card in _delegates(content):
        assert card.width() <= loader.width() + 1, "card wider than its delegate"
        assert (
            loader.width() <= timeline.width() - 10 - 12 + 1
        ), "delegate wider than the timeline content area"


def _assert_buttons_disjoint(card: QQuickItem, labels: tuple[str, ...]) -> None:
    buttons = [
        item
        for item in _find_all(card, "")
        if (
            item.property("primary") is not None
            and item.property("text") in labels
            and item.height() > 0
        )
    ]
    assert len(buttons) == len(labels), f"expected {labels} buttons, found {len(buttons)}"
    rects = []
    for button in buttons:
        pos = button.mapToItem(card, 0, 0)
        rects.append((pos.x(), pos.y(), button.width(), button.height()))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            x1, y1, w1, h1 = rects[i]
            x2, y2, w2, h2 = rects[j]
            x_overlap = x1 < x2 + w2 and x2 < x1 + w1
            y_overlap = y1 < y2 + h2 and y2 < y1 + h1
            assert not (x_overlap and y_overlap), f"buttons overlap: {rects[i]} vs {rects[j]}"


def _pump_until_agent_idle(qtbot: QtBot, facade: MockNovelStudioFacade) -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and facade.property("agentBusy") is True:
        qtbot.wait(20)
    qtbot.wait(20)


def _seed_item(facade: MockNovelStudioFacade, kind: str, **extra: object) -> str:
    model = facade.property("agentTimeline")
    item_id = f"{kind}-{model.rowCount()}"
    model.append_item(AgentTimelineItemDto(id=item_id, kind=kind, **extra))
    return item_id


def test_all_card_kinds_have_positive_height_and_no_overlap(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade()
    _seed_item(facade, "user_text", text="帮我重写这段，让人物说话更自然。")
    _seed_item(facade, "run_status", label="正在读取当前章节", busy=True, status="RUNNING")
    _seed_item(facade, "tool_call", label="read_selection", text="读取正文选区与章节修订")
    _seed_item(
        facade,
        "text_diff",
        label="修改对比",
        current_text="当前文本",
        draft_text="修改文本",
    )
    _seed_item(facade, "confirmation", label="确认操作", text="替换选区 / 再次修改 / 放弃")
    _seed_item(
        facade,
        "form_card",
        label="补充设定",
        field_labels=("人物名", "关系"),
        field_values=("林默", "旧友"),
    )
    _seed_item(
        facade,
        "change_set",
        label="变更提案",
        target="人物 · 林默",
        operation="更新",
        before_text="旧",
        after_text="新",
        risk="低",
        reason="Mock 来源",
    )
    _seed_item(facade, "choice_card", options=("方案 A", "方案 B"))
    _seed_item(facade, "warning", text="已停止 Mock 任务")

    _, content, timeline, _ = _load_panel(qtbot, facade, width=420)
    qtbot.waitUntil(lambda: len(_delegates(content)) >= 9, timeout=5000)

    bottom = _assert_no_overlap(_delegates(content))
    _assert_fits_horizontally(content, timeline)
    content_height = timeline.property("contentHeight")
    assert bottom <= content_height + 1


def test_flow_wrap_grows_card_and_keeps_buttons_disjoint(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade()
    _seed_item(
        facade,
        "change_set",
        label="变更提案",
        target="人物 · 林默",
        operation="更新",
        before_text="码头工人",
        after_text="退役水手",
        risk="高",
        reason="Mock 提案：人物设定与第一章背景冲突",
    )
    _, content, timeline, root = _load_panel(qtbot, facade, width=520)
    qtbot.waitUntil(lambda: bool(_find_all(content, "changeSetCard")), timeout=5000)
    card = _find_all(content, "changeSetCard")[0]
    tall = card.height()

    root.setWidth(220)
    qtbot.waitUntil(lambda: card.height() != tall, timeout=5000)
    qtbot.wait(50)
    short = card.height()
    assert short >= tall, f"narrower panel should not shrink wrapped card ({short} < {tall})"
    _assert_buttons_disjoint(card, ("放弃", "编辑", "确认"))
    _assert_no_overlap(_delegates(content))


def test_long_text_cards_scroll_without_overlap(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade()
    long_current = "当前：" + "雾港的清晨还浸在灰蓝色的光线里，" * 30
    long_draft = "修改：" + "灰蓝色光线下的雾港尚未苏醒，" * 30
    long_reason = "来源理由：" + "人物设定与第一章背景冲突，" * 20 + "\n" + "补充说明" * 30
    _seed_item(facade, "user_text", text="这是一条很长的用户说明，" * 30)
    _seed_item(facade, "tool_call", label="read_selection", text="很长的工具调用说明，" * 30)
    _seed_item(
        facade,
        "text_diff",
        label="修改对比 · 长文",
        current_text=long_current,
        draft_text=long_draft,
    )
    _seed_item(
        facade,
        "form_card",
        label="补充设定 · 长字段",
        text="三个很长的表单字段",
        field_labels=("人物名", "关系", "备注"),
        field_values=("林默", "旧友" + "很长" * 20, "待确认" + "很长" * 20),
    )
    _seed_item(
        facade,
        "change_set",
        label="变更提案",
        target="人物 · 林默" + "很长" * 10,
        operation="更新",
        before_text="码头工人" + "很长" * 20,
        after_text="退役水手" + "很长" * 20,
        risk="高",
        reason=long_reason,
    )

    _, content, timeline, _ = _load_panel(qtbot, facade, width=360, height=500)
    qtbot.waitUntil(lambda: bool(_find_all(content, "changeSetCard")), timeout=5000)
    qtbot.wait(80)

    bottom = _assert_no_overlap(_delegates(content))
    _assert_fits_horizontally(content, timeline)
    content_height = timeline.property("contentHeight")
    assert bottom <= content_height + 1
    assert content_height > timeline.height(), "long timeline should be scrollable"

    timeline.setProperty("contentY", content_height - timeline.height())
    qtbot.wait(50)
    last = _delegates(content)[-1]
    assert last[1].y() + last[1].height() <= content_height + 1

    composer = _find_all(content, "agentComposer")[0]
    panel = _find_all(content, "creativeAgentPanel")[0]
    composer_top = composer.mapToItem(panel, 0, 0).y()
    timeline_bottom = timeline.mapToItem(panel, 0, timeline.height()).y()
    assert composer_top >= timeline_bottom - 1, "composer is covered by the timeline"


def test_dynamic_append_keeps_rows_ordered(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade()
    _, content, timeline, _ = _load_panel(qtbot, facade, width=420)
    kinds = (
        ("user_text", dict(text="动态追加：扩写")),
        ("run_status", dict(label="正在读取", busy=True, status="RUNNING")),
        ("tool_call", dict(label="read_selection", text="读取选区")),
        ("tool_result", dict(label="read_selection", text="已读取 80 字")),
        ("text_diff", dict(label="修改对比", current_text="当前", draft_text="修改")),
        ("confirmation", dict(label="确认操作", text="确认 / 取消")),
        ("form_card", dict(label="补充设定", field_labels=("人物名",), field_values=("林默",))),
        (
            "change_set",
            dict(
                label="变更提案",
                target="人物",
                operation="更新",
                before_text="旧",
                after_text="新",
                risk="低",
                reason="来源",
            ),
        ),
    )
    previous_content_height = 0.0
    for _index, (kind, extra) in enumerate(kinds):
        _seed_item(facade, kind, **extra)
        qtbot.waitUntil(
            lambda prev=previous_content_height: (
                timeline.property("contentHeight") > prev
            ),
            timeout=5000,
        )
        qtbot.wait(30)
        rows = _delegates(content)
        if rows:
            _assert_no_overlap(rows)
        previous_content_height = timeline.property("contentHeight")


def test_multi_turn_no_overlap_autoscroll_and_old_buttons(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    _, content, timeline, _ = _load_panel(qtbot, facade, width=420, height=520)

    previous = 0.0
    for prompt in ("扩写：让人物说话更自然。", "精简：压缩到一半。", "重写：更有克制感。"):
        facade.startAgentTurn(prompt)
        _pump_until_agent_idle(qtbot, facade)
        rows = _delegates(content)
        _assert_no_overlap(rows)
        content_height = timeline.property("contentHeight")
        assert content_height > previous, "contentHeight did not grow across turns"
        previous = content_height

    # Auto-scroll keeps the view at the bottom.
    qtbot.waitUntil(lambda: timeline.property("contentY") > 0, timeout=5000)

    # Old cards remain interactive: approve the first diff card.
    diff_cards = _find_all(content, "textDiffCard")
    assert diff_cards, "no textDiffCard after multi-turn"
    first_diff = diff_cards[0]
    item_id = first_diff.property("itemId")
    approve = next(
        (
            item
            for item in _find_all(first_diff, "")
            if (
                item.property("primary") is not None
                and item.property("text") == "确认替换"
            )
        ),
        None,
    )
    assert approve is not None
    QMetaObject.invokeMethod(approve, "clicked")
    model = facade.property("agentTimeline")
    states = {item.id: item.state for item in model.items()}
    assert states.get(item_id) == "APPLIED"


def test_run_status_card_carries_neon_border_states(qtbot: QtBot) -> None:
    """The production run_status card is wired to the shader neon border:
    busy -> thinking loop, DONE -> success single sweep, idle otherwise
    (prototype B production integration)."""
    facade = MockNovelStudioFacade()
    _seed_item(facade, "run_status", label="正在读取当前章节", busy=True, status="RUNNING")
    _, content, _, _ = _load_panel(qtbot, facade, width=420)

    qtbot.waitUntil(
        lambda: bool(_find_all(content, "agentRunStatusNeon")),
        timeout=5000,
    )
    status_card = _find_all(content, "agentRunStatus")[0]
    neon = _find_all(content, "agentRunStatusNeon")[0]
    assert neon is not None
    assert neon.property("active") is True
    assert neon.property("state") == "thinking"
    assert bool(neon.property("loopAnimRunning")) is True

    # Transition to DONE: one success sweep, then it stops.
    neon.setProperty("flowDuration", 60)
    status_card.setProperty("busy", False)
    status_card.setProperty("status", "DONE")
    qtbot.waitUntil(lambda: neon.property("state") == "success", timeout=5000)
    qtbot.waitUntil(
        lambda: bool(neon.property("singleFinished")) is True,
        timeout=2000,
    )
    assert bool(neon.property("animationRunning")) is False

    # Back to an idle state: static border, no flow.
    status_card.setProperty("status", "")
    qtbot.waitUntil(lambda: neon.property("state") == "idle", timeout=5000)
    assert neon.property("active") is False
    assert bool(neon.property("loopAnimRunning")) is False
