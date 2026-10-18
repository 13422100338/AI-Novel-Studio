"""Reserved 33-50ms streaming merge for the Agent timeline (ideal-UI 10.3)."""

import time

from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto
from ai_novel_studio.ui_qml.bridge.models.agent_timeline_model import (
    ROLE_TEXT,
    AgentTimelineModel,
)
from ai_novel_studio.ui_qml.bridge.streaming_timeline import StreamingTimelineBuffer


def _model_with_assistant_item(item_id: str = "assistant-1") -> AgentTimelineModel:
    model = AgentTimelineModel()
    model.append_item(AgentTimelineItemDto(id=item_id, kind="assistant_text"))
    return model


def test_buffer_merges_chunks_on_flush() -> None:
    model = _model_with_assistant_item()
    buffer = StreamingTimelineBuffer(model, "run-1")

    assert buffer.accept_chunk("run-1", "assistant-1", 1, "你") is True
    assert buffer.accept_chunk("run-1", "assistant-1", 2, "好") is True
    assert buffer.accept_chunk("run-1", "assistant-1", 3, "！") is True
    assert buffer.pending_count() == 1

    assert buffer.flush() == 1
    assert model.data(model.index(0), ROLE_TEXT) == "你好！"
    assert buffer.pending_count() == 0

    # Later chunks accumulate on top of the flushed text.
    assert buffer.accept_chunk("run-1", "assistant-1", 4, " 世界") is True
    buffer.flush()
    assert model.data(model.index(0), ROLE_TEXT) == "你好！ 世界"


def test_flush_emits_one_data_changed_per_batch() -> None:
    model = _model_with_assistant_item()
    buffer = StreamingTimelineBuffer(model, "run-1")
    emitted: list[int] = []
    model.dataChanged.connect(lambda *_: emitted.append(1))

    for sequence in range(1, 6):
        buffer.accept_chunk("run-1", "assistant-1", sequence, "字")
    assert buffer.flush() == 1

    assert emitted == [1]
    assert model.data(model.index(0), ROLE_TEXT) == "字字字字字"


def test_buffer_drops_stale_and_wrong_run_chunks() -> None:
    model = _model_with_assistant_item()
    buffer = StreamingTimelineBuffer(model, "run-1")

    assert buffer.accept_chunk("run-1", "assistant-1", 5, "旧") is True
    assert buffer.accept_chunk("run-1", "assistant-1", 3, "陈旧") is False
    assert buffer.accept_chunk("run-2", "assistant-1", 6, "别的run") is False
    assert buffer.accept_chunk("run-1", "assistant-1", 6, "新") is True
    buffer.flush()

    assert model.data(model.index(0), ROLE_TEXT) == "旧新"


def test_empty_chunks_are_ignored() -> None:
    buffer = StreamingTimelineBuffer(_model_with_assistant_item(), "run-1")
    assert buffer.accept_chunk("run-1", "assistant-1", 1, "") is False
    assert buffer.pending_count() == 0


def test_drop_run_discards_pending_chunks() -> None:
    model = _model_with_assistant_item()
    buffer = StreamingTimelineBuffer(model, "run-1")
    buffer.accept_chunk("run-1", "assistant-1", 1, "内容")

    assert buffer.pending_count() == 1
    buffer.drop_run()
    assert buffer.pending_count() == 0
    assert buffer.flush() == 0
    assert model.data(model.index(0), ROLE_TEXT) == ""


def test_flush_drops_chunks_for_removed_item() -> None:
    model = AgentTimelineModel()
    buffer = StreamingTimelineBuffer(model, "run-1")
    assert buffer.accept_chunk("run-1", "ghost", 1, "内容") is True

    assert buffer.flush() == 0
    assert buffer.pending_count() == 0


def test_timer_flushes_after_interval(qapp) -> None:
    model = _model_with_assistant_item()
    buffer = StreamingTimelineBuffer(model, "run-1", flush_interval_ms=40)
    buffer.accept_chunk("run-1", "assistant-1", 1, "自动")

    deadline = time.monotonic() + 1.0
    while (
        time.monotonic() < deadline
        and model.data(model.index(0), ROLE_TEXT) != "自动"
    ):
        qapp.processEvents()
        time.sleep(0.01)

    assert model.data(model.index(0), ROLE_TEXT) == "自动"
