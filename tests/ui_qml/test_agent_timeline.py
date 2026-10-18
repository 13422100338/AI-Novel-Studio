"""Frontend Wave C1.1: Agent timeline model and Mock Agent flow."""

import hashlib
import json
import time

from ai_novel_studio.application.selection_patch import (
    ANCHOR_CODEPOINTS,
    SCHEMA_VERSION,
)
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.models.agent_timeline_model import (
    ROLE_KIND,
    ROLE_LABEL,
    ROLE_OPERATION,
    ROLE_STATE,
    ROLE_TARGET,
    ROLE_TEXT,
    AgentTimelineModel,
)


def _selection_payload(source: str, selected: str) -> str:
    start = source.index(selected)
    end = start + len(selected)

    def span(span_start: int, span_end: int) -> dict[str, object]:
        text = source[span_start:span_end]
        return {
            "start": span_start,
            "end": span_end,
            "text": text,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "chapter_id": "chapter-1",
            "base_revision": 3,
            "base_source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "selection": span(start, end),
            "before_anchor": span(max(0, start - ANCHOR_CODEPOINTS), start),
            "after_anchor": span(
                end,
                min(len(source), end + ANCHOR_CODEPOINTS),
            ),
        },
        ensure_ascii=False,
    )


def _pump_until(app, facade: MockNovelStudioFacade, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and facade.property("agentBusy"):
        app.processEvents()


def _kinds(facade: MockNovelStudioFacade) -> list[str]:
    model = facade.property("agentTimeline")
    return [model.data(model.index(i), ROLE_KIND) for i in range(model.rowCount())]


def _find_item(facade: MockNovelStudioFacade, kind: str) -> AgentTimelineItemDto:
    model = facade.property("agentTimeline")
    for i in range(model.rowCount()):
        if model.data(model.index(i), ROLE_KIND) == kind:
            return model.items()[i]
    raise AssertionError(f"no {kind} event in timeline")


def test_agent_timeline_model_roles() -> None:
    model = AgentTimelineModel()
    model.append_item(
        AgentTimelineItemDto(
            id="t1",
            kind="change_set",
            label="变更提案",
            target="人物 · 林默",
            operation="更新",
            before_text="码头工人",
            after_text="退役水手",
            risk="低",
            reason="Mock 提案",
            state="PENDING",
        )
    )
    index = model.index(0)
    assert model.data(index, ROLE_KIND) == "change_set"
    assert model.data(index, ROLE_LABEL) == "变更提案"
    assert model.data(index, ROLE_TARGET) == "人物 · 林默"
    assert model.data(index, ROLE_OPERATION) == "更新"
    assert model.data(index, ROLE_STATE) == "PENDING"
    assert model.roleNames()[ROLE_STATE] == b"state"


def test_agent_timeline_model_update_item_is_precise() -> None:
    """Spec 18.6: update one row via dataChanged, never reset the list."""
    model = AgentTimelineModel()
    model.append_item(AgentTimelineItemDto(id="a1", kind="assistant_text", text="第一段"))
    model.append_item(AgentTimelineItemDto(id="a2", kind="assistant_text", text="第二段"))
    emitted: list[tuple[int, int]] = []

    def on_data_changed(top, bottom, _roles) -> None:
        emitted.append((top.row(), bottom.row()))

    model.dataChanged.connect(on_data_changed)

    assert model.update_item("a1", text="第一段（更新）", status="RUNNING") is True
    assert model.items()[0].text == "第一段（更新）"
    assert model.items()[0].status == "RUNNING"
    assert model.items()[1].text == "第二段"
    assert emitted == [(0, 0)]

    assert model.update_item("missing", text="x") is False
    assert emitted == [(0, 0)]


def test_mock_agent_emits_structured_timeline(qapp) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)

    facade.startAgentTurn("帮我重写这段，让人物说话更自然。")
    _pump_until(qapp, facade, 5.0)

    assert facade.property("agentBusy") is False
    kinds = _kinds(facade)
    assert kinds[0] == "user_text"
    for expected in (
        "run_status",
        "tool_call",
        "tool_result",
        "text_diff",
        "confirmation",
        "form_card",
        "change_set",
    ):
        assert expected in kinds, f"missing {expected} in {kinds}"


def test_mock_agent_uses_selection_reference_in_diff(qapp) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    text = "清晨的雾港"
    source = str(facade.property("currentChapterBody"))
    facade.setSelectionReferenceJson(_selection_payload(source, text))

    facade.startAgentTurn("重写选区")
    _pump_until(qapp, facade, 5.0)

    diff = _find_item(facade, "text_diff")
    assert "清晨的雾港" in diff.current_text


def test_mock_agent_stop_keeps_partial_timeline(qapp) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)

    facade.startAgentTurn("取消测试")
    facade.stopAgentTurn()
    _pump_until(qapp, facade, 3.0)

    assert facade.property("agentBusy") is False
    kinds = _kinds(facade)
    assert kinds[0] == "user_text"
    assert "warning" in kinds


def test_mock_agent_items_carry_run_identity(qapp) -> None:
    """Spec 10.4: each Mock turn has one run_id and monotonic sequences."""
    facade = MockNovelStudioFacade(demo_mode=True)
    model = facade.property("agentTimeline")

    facade.startAgentTurn("第一轮")
    _pump_until(qapp, facade, 5.0)
    first_turn = model.items()
    first_run_ids = {item.run_id for item in first_turn}
    assert len(first_run_ids) == 1
    first_run_id = first_run_ids.pop()
    assert first_run_id
    sequences = [item.sequence_number for item in first_turn]
    assert sequences == sorted(sequences)
    assert sequences[0] == 0

    first_count = model.rowCount()
    facade.startAgentTurn("第二轮")
    _pump_until(qapp, facade, 5.0)
    second_turn = model.items()[first_count:]
    second_run_ids = {item.run_id for item in second_turn}
    assert len(second_run_ids) == 1
    assert second_run_ids.pop() != first_run_id


def test_agent_item_actions_route_by_item_id_and_update_state() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    model = facade.property("agentTimeline")
    model.append_item(
        AgentTimelineItemDto(
            id="diff-a",
            kind="text_diff",
            label="修改对比",
            current_text="原文",
            draft_text="改稿",
            state="PENDING",
        )
    )
    model.append_item(
        AgentTimelineItemDto(
            id="diff-b",
            kind="text_diff",
            label="修改对比",
            current_text="原文B",
            draft_text="改稿B",
            state="PENDING",
        )
    )

    facade.approveAgentItem("diff-a")
    assert model.items()[0].state == "APPLIED"
    assert model.items()[1].state == "PENDING"

    facade.discardAgentItem("diff-b")
    assert model.items()[1].state == "DISCARDED"
    assert model.items()[0].state == "APPLIED"

    facade.retryAgentItem("diff-b")
    assert model.items()[1].state == "RUNNING"


def test_agent_confirmation_cancel_and_form_actions() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    model = facade.property("agentTimeline")
    model.append_item(
        AgentTimelineItemDto(
            id="confirm-1",
            kind="confirmation",
            label="确认操作",
            text="替换选区 / 再次修改 / 放弃",
            state="PENDING",
        )
    )
    model.append_item(
        AgentTimelineItemDto(
            id="form-1",
            kind="form_card",
            label="补充设定",
            field_labels=("人物名", "关系"),
            field_values=("林默", "旧友"),
            state="PENDING",
        )
    )

    facade.cancelAgentItem("confirm-1")
    assert model.items()[0].state == "CANCELLED"

    facade.submitAgentForm("form-1", '["林默","挚友"]')
    assert model.items()[1].state == "APPLIED"
    assert "林默" in _kinds_text(facade)


def test_agent_reply_choice_appends_assistant_text() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    facade.agentReplyChoice(0)

    model = facade.property("agentTimeline")
    assert model.rowCount() == 1
    assert model.data(model.index(0), ROLE_KIND) == "assistant_text"


def _kinds_text(facade: MockNovelStudioFacade) -> str:
    model = facade.property("agentTimeline")
    return "\n".join(str(model.data(model.index(i), ROLE_TEXT)) for i in range(model.rowCount()))
