from dataclasses import replace

import pytest

from ai_novel_studio.application.memory_workspace_service import (
    LockedMemoryRecordError,
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.domain.memory import Authority, MemoryStatus, ReviewStatus


class FakeWorkspaceGateway:
    def __init__(self, records: tuple[MemoryWorkspaceRecord, ...]) -> None:
        self.records = records
        self.loaded_boundary: str | None = None
        self.updated: list[tuple[str, str, int]] = []
        self.promoted: list[tuple[str, int]] = []
        self.retry_requests: list[tuple[str, int]] = []

    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
        self.loaded_boundary = chapter_id
        return self.records

    def update_content(
        self, record_id: str, content: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        self.updated.append((record_id, content, expected_revision))
        record = next(item for item in self.records if item.id == record_id)
        return replace(record, content=content, revision=record.revision + 1)

    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord:
        self.promoted.append((record_id, expected_revision))
        record = next(item for item in self.records if item.id == record_id)
        return replace(
            record,
            revision=record.revision + 1,
            review_status=ReviewStatus.APPROVED,
            status=MemoryStatus.CURRENT,
            promotable=False,
        )

    def request_model_retry(
        self, record_id: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        self.retry_requests.append((record_id, expected_revision))
        record = next(item for item in self.records if item.id == record_id)
        return replace(
            record,
            source_type="SUMMARY_FALLBACK",
            revision=record.revision + 1,
            review_status=ReviewStatus.REVIEW,
            status=MemoryStatus.REVIEW,
            promotable=False,
        )


class PartiallyFailingGateway(FakeWorkspaceGateway):
    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord:
        if record_id == "summary-fails":
            raise RuntimeError("记录已变化")
        return super().promote(record_id, expected_revision)


def _record(
    record_id: str,
    *,
    review_status: ReviewStatus = ReviewStatus.REVIEW,
    authority: Authority = Authority.MODEL_EXTRACTED,
) -> MemoryWorkspaceRecord:
    return MemoryWorkspaceRecord(
        id=record_id,
        category="压缩前文",
        title="第一章摘要",
        content="候选摘要",
        source_type="SUMMARY",
        source_chapter_id="chapter-1",
        source_revision=2,
        source_hash="hash-1",
        authority=authority,
        review_status=review_status,
        status=MemoryStatus.REVIEW,
        revision=1,
        editable=True,
        promotable=True,
    )


def test_load_edit_and_promote_are_explicit_gateway_operations() -> None:
    gateway = FakeWorkspaceGateway((_record("summary-1"),))
    service = MemoryWorkspaceService(gateway)

    snapshot = service.load("chapter-2")
    edited = service.edit("summary-1", "人工修订摘要", expected_revision=1)
    promoted = service.promote("summary-1", expected_revision=2)

    assert snapshot.before_chapter_id == "chapter-2"
    assert gateway.loaded_boundary == "chapter-2"
    assert gateway.updated == [("summary-1", "人工修订摘要", 1)]
    assert gateway.promoted == [("summary-1", 2)]
    assert edited.revision == 2
    assert promoted.review_status == ReviewStatus.APPROVED


def test_locked_human_record_is_blocked_before_the_gateway_is_called() -> None:
    locked = _record(
        "canon-locked",
        review_status=ReviewStatus.LOCKED,
        authority=Authority.USER_CONFIRMED,
    )
    gateway = FakeWorkspaceGateway((locked,))
    service = MemoryWorkspaceService(gateway)
    service.load("chapter-2")

    with pytest.raises(LockedMemoryRecordError, match="锁定"):
        service.edit("canon-locked", "模型覆盖内容", expected_revision=1)
    with pytest.raises(LockedMemoryRecordError, match="锁定"):
        service.promote("canon-locked", expected_revision=1)

    assert gateway.updated == []
    assert gateway.promoted == []


def test_approved_model_summary_can_be_marked_for_model_retry() -> None:
    approved = replace(
        _record("summary-approved"),
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
        promotable=False,
    )
    gateway = FakeWorkspaceGateway((approved,))
    service = MemoryWorkspaceService(gateway)
    service.load("chapter-2")

    retried = service.request_model_retry("summary-approved", expected_revision=1)

    assert gateway.retry_requests == [("summary-approved", 1)]
    assert retried.source_type == "SUMMARY_FALLBACK"
    assert retried.review_status == ReviewStatus.REVIEW
    assert retried.status == MemoryStatus.REVIEW
    assert retried.revision == 2


def test_structured_memory_cannot_be_marked_for_model_retry() -> None:
    structured = replace(
        _record("character-state"),
        source_type="CHARACTER_STATE",
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
        promotable=False,
    )
    gateway = FakeWorkspaceGateway((structured,))
    service = MemoryWorkspaceService(gateway)
    service.load("chapter-2")

    with pytest.raises(PermissionError, match="章节摘要"):
        service.request_model_retry("character-state", expected_revision=1)

    assert gateway.retry_requests == []


def test_promote_all_only_processes_review_candidates_and_continues_after_failure() -> None:
    approved = replace(
        _record("summary-approved"),
        review_status=ReviewStatus.APPROVED,
        promotable=False,
    )
    gateway = PartiallyFailingGateway(
        (_record("summary-fails"), _record("summary-ok"), approved)
    )
    service = MemoryWorkspaceService(gateway)
    service.load("chapter-2")
    progress: list[tuple[int, int, str]] = []

    assert service.pending_promotion_count() == 2
    result = service.promote_all(progress=lambda *value: progress.append(value))

    assert result.attempted_count == 2
    assert [record.id for record in result.promoted] == ["summary-ok"]
    assert [failure.record_id for failure in result.failures] == ["summary-fails"]
    assert service.pending_promotion_count() == 1
    assert [item[:2] for item in progress] == [(1, 2), (2, 2)]
