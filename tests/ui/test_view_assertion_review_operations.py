from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionReviewError,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.view import ViewAssertion, ViewType
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.memory_window import MemoryWindow


class _WorkspaceGateway:
    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
        assert chapter_id == "chapter-2"
        return ()

    def update_content(
        self, record_id: str, content: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        raise AssertionError("Review tests do not edit memory records")

    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord:
        raise AssertionError("Review tests do not promote memory records")

    def request_model_retry(
        self, record_id: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        raise AssertionError("Review tests do not retry memory records")

    def update_fields(
        self,
        record_id: str,
        source_type: str,
        fields: dict[str, str],
        expected_revision: int,
    ) -> MemoryWorkspaceRecord:
        raise AssertionError("Review tests do not edit structured records")


@dataclass
class _ReviewService:
    candidates: tuple[ViewAssertion, ...]
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def list_review_candidates(self, *, limit: int = 100) -> tuple[ViewAssertion, ...]:
        assert limit == 100
        return self.candidates

    def approve_candidate(
        self, assertion_id: str, *, confirmed_by_user: bool
    ) -> ViewAssertion:
        return self._review("approve", assertion_id, confirmed_by_user)

    def reject_candidate(
        self, assertion_id: str, *, confirmed_by_user: bool
    ) -> ViewAssertion:
        return self._review("reject", assertion_id, confirmed_by_user)

    def edit_model_candidate_content(
        self, assertion_id: str, content: str, *, expected_updated_at: datetime,
        confirmed_by_user: bool,
    ) -> ViewAssertion:
        self.calls.append(("edit", assertion_id, confirmed_by_user))
        if self.error is not None:
            raise self.error
        candidate = self.candidates[0]
        self.candidates = (replace(candidate, content=content, updated_at=datetime.now()),)
        return self.candidates[0]

    def _review(
        self, action: str, assertion_id: str, confirmed_by_user: bool
    ) -> ViewAssertion:
        self.calls.append((action, assertion_id, confirmed_by_user))
        if self.error is not None:
            raise self.error
        self.candidates = ()
        return cast(ViewAssertion, object())


def _candidate() -> ViewAssertion:
    now = datetime.now()
    return ViewAssertion(
        id="assertion-1",
        subject_id="character-1",
        view_type=ViewType.CHARACTER_VIEW,
        content="艾瑞克怀疑匿名来信来自王城。",
        viewer_subject_id="character-2",
        epistemic_status=None,
        valid_from_sequence=1,
        valid_to_sequence=None,
        story_time_label="第 1 夜",
        narrative_visible_from_sequence=2,
        narrative_visible_to_sequence=None,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        source_id="chapter-1",
        source_revision=3,
        stale=False,
        source_changed=False,
        created_at=now,
        updated_at=now,
    )


def _bind(window: MemoryWindow, service: _ReviewService) -> None:
    window.bind(
        MemoryWorkspaceService(_WorkspaceGateway()),
        "chapter-2",
        reader_view_subjects=(
            ("character-1", "艾瑞克"),
            ("character-2", "克莉丝汀"),
        ),
        view_assertion_review_service=service,
    )


def test_view_assertion_review_binds_one_candidate_with_safe_subject_names(
    qtbot: QtBot,
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    _bind(window, _ReviewService((_candidate(),)))

    assert window.view_assertion_review_selector.count() == 1
    assert "CHARACTER_VIEW" in window.view_assertion_review_details.toPlainText()
    assert "艾瑞克" in window.view_assertion_review_details.toPlainText()
    assert "克莉丝汀" in window.view_assertion_review_details.toPlainText()
    assert "chapter-1" in window.view_assertion_review_details.toPlainText()
    assert window.view_assertion_review_details.isReadOnly()
    assert "可选" in window.view_assertion_review_status_label.text()
    assert "保存" in window.view_assertion_review_status_label.text()
    assert "批准或拒绝" in window.view_assertion_review_status_label.text()
    assert window.view_assertion_approve_button.isEnabled()
    assert window.view_assertion_reject_button.isEnabled()


def test_view_assertion_review_cancelled_approval_and_rejection_do_not_write(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ReviewService((_candidate(),))
    _bind(window, service)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    qtbot.mouseClick(window.view_assertion_approve_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.view_assertion_reject_button, Qt.MouseButton.LeftButton)

    assert service.calls == []


def test_view_assertion_review_confirms_approval_and_rejection_separately(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    approve_window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(approve_window)
    approve_service = _ReviewService((_candidate(),))
    _bind(approve_window, approve_service)

    qtbot.mouseClick(
        approve_window.view_assertion_approve_button, Qt.MouseButton.LeftButton
    )

    assert approve_service.calls == [("approve", "assertion-1", True)]
    assert approve_window.view_assertion_review_selector.count() == 0

    reject_window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(reject_window)
    reject_service = _ReviewService((_candidate(),))
    _bind(reject_window, reject_service)

    qtbot.mouseClick(
        reject_window.view_assertion_reject_button, Qt.MouseButton.LeftButton
    )

    assert reject_service.calls == [("reject", "assertion-1", True)]
    assert reject_window.view_assertion_review_selector.count() == 0


def test_view_assertion_review_handles_error_and_empty_state(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    _bind(window, _ReviewService(()))

    assert window.view_assertion_approve_button.isEnabled() is False
    assert "没有" in window.view_assertion_review_status_label.text()

    service = _ReviewService(
        (_candidate(),), error=ViewAssertionReviewError("候选已被审查")
    )
    _bind(window, service)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_approve_button, Qt.MouseButton.LeftButton)

    assert "候选已被审查" in window.view_assertion_review_status_label.text()


def test_view_assertion_review_edit_requires_confirmation(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ReviewService((_candidate(),))
    _bind(window, service)
    window.view_assertion_content_editor.setPlainText("修订后的候选内容")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    qtbot.mouseClick(window.view_assertion_save_edit_button, Qt.MouseButton.LeftButton)
    assert service.calls == []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    qtbot.mouseClick(window.view_assertion_save_edit_button, Qt.MouseButton.LeftButton)
    assert service.calls == [("edit", "assertion-1", True)]
