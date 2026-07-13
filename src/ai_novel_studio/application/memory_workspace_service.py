from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ai_novel_studio.domain.memory import Authority, MemoryStatus, ReviewStatus


class LockedMemoryRecordError(PermissionError):
    pass


class StaleMemoryRecordError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryWorkspaceField:
    key: str
    label: str
    value: str
    choices: tuple[str, ...] = ()
    multiline: bool = False


@dataclass(frozen=True, slots=True)
class MemoryWorkspaceRecord:
    id: str
    category: str
    title: str
    content: str
    source_type: str
    source_chapter_id: str | None
    source_revision: int | None
    source_hash: str
    authority: Authority
    review_status: ReviewStatus
    status: MemoryStatus
    revision: int
    editable: bool
    promotable: bool
    fields: tuple[MemoryWorkspaceField, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("记录 ID", self.id),
            ("分类", self.category),
            ("标题", self.title),
            ("来源类型", self.source_type),
        ):
            if not value.strip():
                raise ValueError(f"{field_name}不能为空")
        if self.revision < 0:
            raise ValueError("记录修订号不能为负数")
        if self.source_revision is not None and self.source_revision < 0:
            raise ValueError("来源章节修订号不能为负数")


@dataclass(frozen=True, slots=True)
class MemoryWorkspaceSnapshot:
    before_chapter_id: str
    records: tuple[MemoryWorkspaceRecord, ...]


@dataclass(frozen=True, slots=True)
class MemoryPromotionFailure:
    record_id: str
    title: str
    message: str


@dataclass(frozen=True, slots=True)
class MemoryBulkPromotionResult:
    promoted: tuple[MemoryWorkspaceRecord, ...]
    failures: tuple[MemoryPromotionFailure, ...]

    @property
    def attempted_count(self) -> int:
        return len(self.promoted) + len(self.failures)


class MemoryWorkspaceGateway(Protocol):
    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]: ...

    def update_content(
        self, record_id: str, content: str, expected_revision: int
    ) -> MemoryWorkspaceRecord: ...

    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord: ...

    def update_fields(
        self,
        record_id: str,
        source_type: str,
        fields: dict[str, str],
        expected_revision: int,
    ) -> MemoryWorkspaceRecord: ...


class MemoryWorkspaceService:
    """Application boundary for explicit review operations on memory records."""

    def __init__(self, gateway: MemoryWorkspaceGateway) -> None:
        self._gateway = gateway
        self._records: dict[str, MemoryWorkspaceRecord] = {}

    def load(self, before_chapter_id: str) -> MemoryWorkspaceSnapshot:
        boundary = before_chapter_id.strip()
        if not boundary:
            raise ValueError("章节边界不能为空")
        records = self._gateway.load_before(boundary)
        if len({record.id for record in records}) != len(records):
            raise ValueError("记忆工作区返回了重复记录 ID")
        self._records = {record.id: record for record in records}
        return MemoryWorkspaceSnapshot(boundary, records)

    def edit(
        self, record_id: str, content: str, *, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        record = self._record(record_id)
        self._assert_revision(record, expected_revision)
        if record.review_status == ReviewStatus.LOCKED:
            raise LockedMemoryRecordError("锁定的人工记忆记录不能直接修改")
        if not record.editable:
            raise PermissionError("该记忆记录不支持直接编辑")
        normalized = content.strip()
        if not normalized:
            raise ValueError("记忆内容不能为空")
        updated = self._gateway.update_content(record.id, normalized, expected_revision)
        self._records[updated.id] = updated
        return updated

    def promote(self, record_id: str, *, expected_revision: int) -> MemoryWorkspaceRecord:
        record = self._record(record_id)
        self._assert_revision(record, expected_revision)
        if record.review_status == ReviewStatus.LOCKED:
            raise LockedMemoryRecordError("锁定的人工记忆记录不需要晋升")
        if not record.promotable or record.review_status != ReviewStatus.REVIEW:
            raise PermissionError("只有待审查候选记录可以显式晋升")
        promoted = self._gateway.promote(record.id, expected_revision)
        self._records[promoted.id] = promoted
        return promoted

    def pending_promotion_count(self) -> int:
        return len(self._promotion_candidates())

    def promote_all(
        self,
        *,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> MemoryBulkPromotionResult:
        promoted: list[MemoryWorkspaceRecord] = []
        failures: list[MemoryPromotionFailure] = []
        candidates = self._promotion_candidates()
        total = len(candidates)
        for index, record in enumerate(candidates, start=1):
            try:
                promoted.append(
                    self.promote(record.id, expected_revision=record.revision)
                )
            except (KeyError, PermissionError, RuntimeError, ValueError) as error:
                failures.append(
                    MemoryPromotionFailure(record.id, record.title, str(error))
                )
            if progress is not None:
                progress(index, total, record.title)
        return MemoryBulkPromotionResult(tuple(promoted), tuple(failures))

    def edit_fields(
        self,
        record_id: str,
        fields: dict[str, str],
        *,
        expected_revision: int,
    ) -> MemoryWorkspaceRecord:
        record = self._record(record_id)
        self._assert_revision(record, expected_revision)
        if record.review_status == ReviewStatus.LOCKED:
            raise LockedMemoryRecordError("锁定的人工记忆记录不能直接修改")
        if not record.editable or not record.fields:
            raise PermissionError("该记忆记录不支持结构化编辑")
        updated = self._gateway.update_fields(
            record.id, record.source_type, fields, expected_revision
        )
        self._records[updated.id] = updated
        return updated

    def _record(self, record_id: str) -> MemoryWorkspaceRecord:
        try:
            return self._records[record_id]
        except KeyError as error:
            raise KeyError(f"工作区中不存在记忆记录：{record_id}") from error

    def _promotion_candidates(self) -> tuple[MemoryWorkspaceRecord, ...]:
        return tuple(
            record
            for record in self._records.values()
            if record.promotable and record.review_status == ReviewStatus.REVIEW
        )

    @staticmethod
    def _assert_revision(record: MemoryWorkspaceRecord, expected_revision: int) -> None:
        if record.revision != expected_revision:
            raise StaleMemoryRecordError(
                f"记忆记录已变化：当前修订为 {record.revision}，请求修订为 {expected_revision}"
            )
