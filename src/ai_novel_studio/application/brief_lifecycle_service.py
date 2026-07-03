from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_novel_studio.core.brief.source_fingerprint import (
    BriefSourceSnapshot,
    compute_source_fingerprint,
    source_key,
)
from ai_novel_studio.domain.generation import BriefStatus, ChapterBrief
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    BriefDraftData,
    ChapterBriefRepository,
    ImmutableBriefError,
    StaleBriefError,
)


class BriefValidationError(ValueError):
    pass


class CurrentBriefSourceProvider(Protocol):
    def current_sources(self, brief_id: str) -> tuple[BriefSourceSnapshot, ...]: ...


@dataclass(frozen=True, slots=True)
class BriefCloneResult:
    brief: ChapterBrief
    added: tuple[tuple[str, str], ...]
    removed: tuple[tuple[str, str], ...]
    changed: tuple[tuple[str, str], ...]


class BriefLifecycleService:
    def __init__(
        self,
        repository: ChapterBriefRepository,
        source_provider: CurrentBriefSourceProvider,
    ) -> None:
        self.repository = repository
        self.source_provider = source_provider

    def freeze(self, brief_id: str, *, expected_revision: int) -> ChapterBrief:
        brief = self.repository.get(brief_id)
        if brief.revision != expected_revision:
            raise StaleBriefError(
                f"Brief 修订已变化，当前为 {brief.revision}，提交为 {expected_revision}"
            )
        if brief.status != BriefStatus.DRAFT:
            raise ImmutableBriefError("只有草稿 Brief 可以冻结")
        current = self.source_provider.current_sources(brief_id)
        self._validate_required_sources(current)
        if compute_source_fingerprint(current) != brief.source_fingerprint:
            raise BriefValidationError("Brief 来源已经变化，请克隆或重新编译后再冻结")
        if not brief.hard_events and not brief.dramatic_purpose.strip():
            raise BriefValidationError("Brief 必须包含戏剧功能或必须事件")
        if any(warning.startswith("MISSING_REQUIRED:") for warning in brief.warnings):
            raise BriefValidationError("Brief 仍有必需来源缺失")
        if any(warning.startswith("CONFLICT:") for warning in brief.warnings):
            raise BriefValidationError("Brief 仍有未解决冲突")
        return self.repository.freeze(brief_id, expected_revision=expected_revision)

    def mark_stale_for_source(
        self,
        source_type: str,
        source_id: str,
        source_revision: int,
        source_hash: str,
    ) -> tuple[str, ...]:
        return self.repository.mark_stale_for_source(
            source_type, source_id, source_revision, source_hash
        )

    def clone_as_draft(self, brief_id: str) -> BriefCloneResult:
        original = self.repository.get(brief_id)
        if original.status not in {BriefStatus.FROZEN, BriefStatus.STALE}:
            raise ImmutableBriefError("只有冻结或过期 Brief 可以克隆")
        old_sources = tuple(
            BriefSourceSnapshot(
                source.source_type,
                source.source_id,
                source.source_revision,
                source.source_hash,
                source.required,
            )
            for source in self.repository.list_sources(brief_id)
        )
        current = self.source_provider.current_sources(brief_id)
        self._validate_required_sources(current)
        old_by_key = {source_key(source): source for source in old_sources}
        current_by_key = {source_key(source): source for source in current}
        added = tuple(sorted(current_by_key.keys() - old_by_key.keys()))
        removed = tuple(sorted(old_by_key.keys() - current_by_key.keys()))
        changed = tuple(
            sorted(
                key
                for key in current_by_key.keys() & old_by_key.keys()
                if current_by_key[key] != old_by_key[key]
            )
        )
        draft = self.repository.create_draft(
            BriefDraftData.from_brief(original),
            current,
            cloned_from_id=original.id,
        )
        return BriefCloneResult(draft, added, removed, changed)

    @staticmethod
    def _validate_required_sources(sources: tuple[BriefSourceSnapshot, ...]) -> None:
        if not any(
            source.source_type == "CHAPTER_REQUIREMENT" and source.required
            for source in sources
        ):
            raise BriefValidationError("Brief 缺少必需的当前章要求来源")
