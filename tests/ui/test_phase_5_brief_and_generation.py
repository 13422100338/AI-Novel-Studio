from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from pytestqt.qtbot import QtBot

from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.panels.manuscript_panel import ManuscriptPanel


class FakeGenerationRuntime(QObject):
    draft_chunk = Signal(str)
    run_changed = Signal(object)
    failed = Signal(str)
    accepted = Signal(str)
    discarded = Signal()
    recovered = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.prepare_calls: list[tuple[CreationMode, int, int]] = []
        self.cancel_calls = 0
        self.accept_calls = 0
        self.discard_calls = 0
        self.recover_calls = 0

    def prepare_and_start(
        self,
        mode: CreationMode,
        output_token_limit: int,
        target_words: int,
    ) -> None:
        self.prepare_calls.append((mode, output_token_limit, target_words))

    def cancel_current(self) -> None:
        self.cancel_calls += 1

    def accept_current(self) -> None:
        self.accept_calls += 1

    def discard_current(self) -> None:
        self.discard_calls += 1

    def recover(self) -> None:
        self.recover_calls += 1


def test_generation_controls_follow_mode_and_brief_state(qtbot: QtBot) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)

    panel.set_phase5_generation_enabled(True, frozen_brief_available=False)

    panel.set_creation_mode(CreationMode.BASIC)
    assert panel.generate_button.isEnabled() is True
    panel.set_creation_mode(CreationMode.STANDARD)
    assert panel.generate_button.isEnabled() is False
    assert "Brief" in panel.generate_button.toolTip()
    panel.set_frozen_brief_available(True)
    assert panel.generate_button.isEnabled() is True
    panel.set_creation_mode(CreationMode.STRICT)
    assert panel.generate_button.isEnabled() is False
    assert "阶段 6" in panel.generate_button.toolTip()


def test_generation_request_emits_mode_token_limit_and_target_words(
    qtbot: QtBot,
) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)
    panel.set_phase5_generation_enabled(True, frozen_brief_available=False)
    panel.set_creation_mode(CreationMode.BASIC)
    panel.output_token_limit.setValue(32000)
    panel.target_words.setValue(4200)

    with qtbot.waitSignal(panel.generation_requested, timeout=1000) as signal:
        panel.generate_button.click()

    assert signal.args == [CreationMode.BASIC, 32000, 4200]


def test_streaming_draft_is_separate_from_formal_editor_and_can_be_discarded(
    qtbot: QtBot,
) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)
    old_formal_text = panel.editor.toPlainText()

    panel.begin_generation_draft()
    panel.append_generation_draft("AI draft part")
    panel.apply_generation_status(GenerationStatus.COMPLETED)

    assert panel.editor.toPlainText() == old_formal_text
    assert panel.generated_draft_editor.toPlainText() == "AI draft part"
    assert panel.adopt_draft_button.isEnabled() is True
    assert panel.discard_draft_button.isEnabled() is True

    panel.discard_generation_draft()

    assert panel.generated_draft_editor.toPlainText() == ""
    assert panel.editor.toPlainText() == old_formal_text


def test_partial_generation_is_labelled_and_requires_explicit_adoption(
    qtbot: QtBot,
) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)

    panel.begin_generation_draft()
    panel.append_generation_draft("partial text")
    panel.apply_generation_status(GenerationStatus.PARTIAL)

    assert "部分" in panel.pipeline_status_label.text()
    assert panel.adopt_draft_button.text() == "采用部分草稿"
    assert panel.editor.toPlainText() != "partial text"


def test_main_window_wires_phase5_runtime_without_direct_storage_access(
    qtbot: QtBot,
) -> None:
    runtime = FakeGenerationRuntime()
    window = MainWindow(generation_runtime=runtime)
    qtbot.addWidget(window)
    window.manuscript_panel.set_creation_mode(CreationMode.BASIC)
    window.manuscript_panel.output_token_limit.setValue(64000)

    window.manuscript_panel.generate_button.click()

    assert runtime.prepare_calls == [(CreationMode.BASIC, 64000, 3500)]
    runtime.draft_chunk.emit("draft")
    runtime.run_changed.emit(GenerationStatus.COMPLETED)
    assert window.manuscript_panel.generated_draft_editor.toPlainText() == "draft"
    assert window.manuscript_panel.editor.toPlainText() != "draft"

    window.manuscript_panel.adopt_draft_button.click()
    assert runtime.accept_calls == 1
    runtime.accepted.emit("accepted prose")
    assert window.manuscript_panel.editor.toPlainText() == "accepted prose"

    window.manuscript_panel.begin_generation_draft()
    window.manuscript_panel.append_generation_draft("throwaway")
    window.manuscript_panel.discard_draft_button.click()
    assert runtime.discard_calls == 1
    runtime.discarded.emit()
    assert window.manuscript_panel.generated_draft_editor.toPlainText() == ""


def test_recovery_button_requests_runtime_scan(qtbot: QtBot) -> None:
    runtime = FakeGenerationRuntime()
    window = MainWindow(generation_runtime=runtime)
    qtbot.addWidget(window)

    window.manuscript_panel.recover_button.click()

    assert runtime.recover_calls == 1
