"""Frontend Wave F5: background draft coordinator with cooperative cancel."""

from __future__ import annotations

from pytestqt.qtbot import QtBot

from ai_novel_studio.ui_qml.bridge.draft_coordinator import (
    DRAFT_CANCELLED,
    DRAFT_COMPLETED,
    DRAFT_FAILED,
    DRAFT_GENERATING,
    DRAFT_IDLE,
    DRAFT_QUEUED,
    DraftCoordinator,
)

from .test_mock_facade import FakeDraftPort


def test_generate_completes_on_background_thread(qtbot: QtBot) -> None:
    port = FakeDraftPort(draft_text="草稿正文")
    coordinator = DraftCoordinator(port)

    with qtbot.waitSignal(coordinator.draft_ready, timeout=5000) as blocker:
        coordinator.start_generate("run-1")

    assert blocker.args == ["草稿正文"]
    assert coordinator.status == DRAFT_COMPLETED
    assert coordinator.is_running is False
    assert coordinator.run_id is None


def test_status_transitions_include_queued_and_generating(qtbot: QtBot) -> None:
    port = FakeDraftPort(draft_text="草稿正文")
    coordinator = DraftCoordinator(port)
    seen: list[str] = []
    coordinator.status_changed.connect(seen.append)

    with qtbot.waitSignal(coordinator.draft_ready, timeout=5000):
        coordinator.start_generate("run-1")
    qtbot.waitUntil(lambda: coordinator.status == DRAFT_COMPLETED, timeout=5000)

    assert seen[0] == DRAFT_QUEUED
    assert DRAFT_GENERATING in seen
    assert seen[-1] == DRAFT_COMPLETED


def test_cancel_cooperatively_stops_generation(qtbot: QtBot) -> None:
    port = FakeDraftPort(block_on_generate=True)
    coordinator = DraftCoordinator(port)

    with qtbot.waitSignal(coordinator.cancelled, timeout=5000):
        coordinator.start_generate("run-1")
        qtbot.waitUntil(lambda: coordinator.status == DRAFT_GENERATING, timeout=5000)
        coordinator.cancel()

    assert coordinator.status == DRAFT_CANCELLED
    assert coordinator.is_running is False
    assert port.cancel_called is True


def test_generate_failure_emits_error_and_failed_status(qtbot: QtBot) -> None:
    port = FakeDraftPort(generate_error="模型超时")
    coordinator = DraftCoordinator(port)

    with qtbot.waitSignal(coordinator.draft_failed, timeout=5000) as blocker:
        coordinator.start_generate("run-1")

    assert "模型超时" in blocker.args[0]
    qtbot.waitUntil(lambda: coordinator.status == DRAFT_FAILED, timeout=5000)
    assert coordinator.status == DRAFT_FAILED


def test_start_without_port_fails_immediately(qtbot: QtBot) -> None:
    coordinator = DraftCoordinator(None)

    with qtbot.waitSignal(coordinator.draft_failed, timeout=5000) as blocker:
        coordinator.start_generate("run-1")

    assert "端口未配置" in blocker.args[0]
    assert coordinator.status == DRAFT_FAILED


def test_double_start_is_rejected(qtbot: QtBot) -> None:
    port = FakeDraftPort(block_on_generate=True)
    coordinator = DraftCoordinator(port)
    coordinator.start_generate("run-1")
    qtbot.waitUntil(lambda: coordinator.status == DRAFT_GENERATING, timeout=5000)

    with qtbot.waitSignal(coordinator.draft_failed, timeout=5000) as blocker:
        coordinator.start_generate("run-2")

    assert "已有生成任务" in blocker.args[0]
    coordinator.cancel()
    qtbot.waitUntil(lambda: coordinator.status == DRAFT_CANCELLED, timeout=5000)


def test_initial_status_is_idle() -> None:
    coordinator = DraftCoordinator(None)
    assert coordinator.status == DRAFT_IDLE
    assert coordinator.is_running is False
