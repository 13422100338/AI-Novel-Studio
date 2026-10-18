from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceOutcome,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.application.occurrence_review_service import (
    OccurrenceReviewService,
)
from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
)
from ai_novel_studio.application.shared_semantic_occurrence_service import (
    OccurrenceBindingStatus,
    SharedSemanticOccurrenceService,
)
from ai_novel_studio.application.subject_history_service import (
    SubjectHistoryDetail,
    SubjectHistoryIndexItem,
    SubjectHistoryService,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.semantic_windowing import (
    SemanticWindow,
    project_semantic_windows,
)
from ai_novel_studio.core.context.shared_semantic_result import (
    OccurrenceCandidate,
    ParticipantLinkCandidate,
    SharedSemanticResult,
    SourceSpan,
    SubjectMentionCandidate,
    candidate_source_id,
)
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

CHAPTER_BODIES = (
    "第一章\r\n\r\n艾琳在旧塔发现了铜钥匙。\r\n守卫没有察觉。\r\n",
    "第二章\r\n\r\n铜钥匙在井底发出微光。\r\n艾琳守卫对视一眼。\r\n",
    "第三章\r\n\r\n他们用铜钥匙打开了地窖。\r\n门后是空房间。\r\n",
)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    history_service: SubjectHistoryService
    review_service: OccurrenceReviewService
    repository: OccurrenceRepository
    chapter_ids: list[str]
    subject_ids: dict[str, str]


def _fixture(tmp_path: Path) -> Fixture:
    project = ProjectRepository.create(tmp_path / "novel", "Gate E1 history")
    revisions = ChapterRevisionService(project)
    chapter_ids: list[str] = []
    for index, body in enumerate(CHAPTER_BODIES, start=1):
        submitted = revisions.submit_creation(
            project.list_volumes()[0].id,
            f"第{index}章",
            str(index),
            body,
        )
        chapter_ids.append(submitted.chapter.id)
    characters = CharacterMemoryRepository(project)
    subject_ids = {
        name: characters.create_character(name).id for name in ("艾琳", "守卫")
    }
    search = SearchRepository(project)
    history_service = SubjectHistoryService(
        project,
        evidence_query=EvidenceQueryService(
            retriever=HistoryRetriever(search),
            evidence=FormalManuscriptEvidenceService(search),
        ),
    )
    return Fixture(
        project=project,
        history_service=history_service,
        review_service=OccurrenceReviewService(project),
        repository=OccurrenceRepository(project),
        chapter_ids=chapter_ids,
        subject_ids=subject_ids,
    )


def _windows(fixture: Fixture, chapter_index: int) -> tuple[SemanticWindow, ...]:
    return project_semantic_windows(
        fixture.chapter_ids[chapter_index],
        0,
        _hash(CHAPTER_BODIES[chapter_index]),
        chapter_index + 1,
        CHAPTER_BODIES[chapter_index],
    )


def _span(window: SemanticWindow, value: str) -> SourceSpan:
    start = window.text.index(value)
    return SourceSpan(
        start,
        start + len(value),
        window.text[start : start + len(value)],
    )


@dataclass(frozen=True, slots=True)
class LinkSpec:
    occurrence_index: int | None
    mention_name: str


def _result(
    window: SemanticWindow,
    *,
    mention_names: tuple[str, ...],
    link_specs: tuple[LinkSpec, ...],
    title: str = "发现铜钥匙",
    summary: str = "艾琳发现了铜钥匙。",
    anchor: str = "铜钥匙",
) -> SharedSemanticResult:
    mentions = tuple(
        SubjectMentionCandidate(
            candidate_source_id(window, "subject-mention", index),
            name,
            (_span(window, name),),
        )
        for index, name in enumerate(mention_names)
    )
    by_name = {
        name: mentions[index].candidate_id
        for index, name in enumerate(mention_names)
    }
    links = tuple(
        ParticipantLinkCandidate(
            candidate_source_id(window, "participant-link", index),
            None,
            f"参与者{index}",
            f"人物投影{index}。",
            (_span(window, spec.mention_name),),
            (
                candidate_source_id(window, "occurrence", spec.occurrence_index)
                if spec.occurrence_index is not None
                else None
            ),
            by_name[spec.mention_name],
        )
        for index, spec in enumerate(link_specs)
    )
    return SharedSemanticResult(
        window=window,
        subject_mentions=mentions,
        aliases=(),
        occurrences=(
            OccurrenceCandidate(
                candidate_source_id(window, "occurrence", 0),
                "DISCOVERY",
                title,
                summary,
                (_span(window, anchor),),
            ),
        ),
        participant_links=links,
        state_changes=(),
        view_differences=(),
        summary=None,
    )


def _bind_pair(
    fixture: Fixture,
    chapter_index: int,
    *,
    approve: bool,
    title: str = "发现铜钥匙",
    summary: str = "艾琳发现了铜钥匙。",
    anchor: str = "铜钥匙",
) -> SharedSemanticChapterResult:
    windows = _windows(fixture, chapter_index)
    result = _result(
        windows[0],
        mention_names=("艾琳", "守卫"),
        link_specs=(LinkSpec(0, "艾琳"), LinkSpec(0, "守卫")),
        title=title,
        summary=summary,
        anchor=anchor,
    )
    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(
        _chapter_result(fixture, chapter_index, (result,))
    )
    assert binding.status is OccurrenceBindingStatus.APPLIED
    if approve:
        _approve_binding(fixture, binding)
    return binding


def _approve_binding(fixture: Fixture, binding) -> None:
    for occurrence_id in binding.accepted_occurrence_ids:
        occurrence = fixture.repository.get_occurrence(occurrence_id)
        fixture.review_service.review_occurrence(
            occurrence_id,
            expected_updated_at=occurrence.updated_at.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    occurrence_id = binding.accepted_occurrence_ids[0]
    stored_links = fixture.repository.list_links_for_occurrence(
        occurrence_id,
        limit=500,
    )
    by_id = {item.id: item for item in stored_links}
    for link_id in binding.accepted_link_ids:
        link = by_id[link_id]
        fixture.review_service.review_link(
            link_id,
            expected_updated_at=link.updated_at.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )


def _chapter_result(
    fixture: Fixture,
    chapter_index: int,
    results: tuple[SharedSemanticResult, ...],
) -> SharedSemanticChapterResult:
    return SharedSemanticChapterResult(
        chapter_id=fixture.chapter_ids[chapter_index],
        source_revision=0,
        source_hash=_hash(CHAPTER_BODIES[chapter_index]),
        narrative_sequence=chapter_index + 1,
        results=results,
    )


def test_seven_person_event_binds_one_occurrence_seven_links_no_states(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "七人事件")
    body = "甲乙丙丁戊己庚七人齐聚古塔。"
    submitted = ChapterRevisionService(project).submit_creation(
        project.list_volumes()[0].id, "第一章", "1", body
    )
    characters = CharacterMemoryRepository(project)
    names = ("甲", "乙", "丙", "丁", "戊", "己", "庚")
    for name in names:
        characters.create_character(name)
    window = project_semantic_windows(submitted.chapter.id, 0, _hash(body), 1, body)[0]
    mentions = tuple(
        SubjectMentionCandidate(
            candidate_source_id(window, "subject-mention", index),
            name,
            (_span(window, name),),
        )
        for index, name in enumerate(names)
    )
    by_name = {
        name: mentions[index].candidate_id
        for index, name in enumerate(names)
    }
    links = tuple(
        ParticipantLinkCandidate(
            candidate_source_id(window, "participant-link", index),
            None,
            "参与者",
            "人物投影。",
            (_span(window, name),),
            candidate_source_id(window, "occurrence", 0),
            by_name[name],
        )
        for index, name in enumerate(names)
    )
    result = SharedSemanticResult(
        window=window,
        subject_mentions=mentions,
        aliases=(),
        occurrences=(
            OccurrenceCandidate(
                candidate_source_id(window, "occurrence", 0),
                "DISCOVERY",
                "齐聚古塔",
                "七人共同到场。",
                (_span(window, "齐聚"),),
            ),
        ),
        participant_links=links,
        state_changes=(),
        view_differences=(),
        summary=None,
    )
    chapter_result = SharedSemanticChapterResult(
        chapter_id=submitted.chapter.id,
        source_revision=0,
        source_hash=_hash(body),
        narrative_sequence=1,
        results=(result,),
    )

    binding = SharedSemanticOccurrenceService(project).persist_chapter(chapter_result)

    assert binding.status is OccurrenceBindingStatus.APPLIED
    assert len(binding.accepted_occurrence_ids) == 1
    assert len(binding.accepted_link_ids) == 7
    with project.database.connect() as connection:
        counts = (
            int(connection.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]),
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM subject_occurrence_links"
                ).fetchone()[0]
            ),
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM character_state_events"
                ).fetchone()[0]
            ),
        )
    assert counts == (1, 7, 0)


def test_history_levels_expand_from_index_to_detail_to_exact_evidence(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    binding = _bind_pair(fixture, 0, approve=True)
    subject_id = fixture.subject_ids["艾琳"]

    index_items = fixture.history_service.list_index(subject_id)
    assert [item.occurrence_id for item in index_items] == [
        binding.accepted_occurrence_ids[0]
    ]
    assert isinstance(index_items[0], SubjectHistoryIndexItem)
    assert not hasattr(index_items[0], "participants")

    detail = fixture.history_service.get_detail(binding.accepted_occurrence_ids[0])
    assert isinstance(detail, SubjectHistoryDetail)
    assert len(detail.participants) == 2
    assert detail.source_ranges[0].start < detail.source_ranges[0].end

    evidence = fixture.history_service.get_evidence(
        detail.occurrence_id,
        target_chapter_id=fixture.chapter_ids[2],
    )
    assert evidence.outcome is EvidenceOutcome.FOUND
    body_by_chapter = dict(zip(fixture.chapter_ids, CHAPTER_BODIES, strict=True))
    for hit in evidence.hits:
        assert hit.text == body_by_chapter[hit.chapter_id][
            hit.source_start : hit.source_end
        ]
        assert hit.retrieval_routes


def test_rejected_and_review_rows_stay_out_of_trusted_levels(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    approved = _bind_pair(fixture, 0, approve=True)
    rejected = _bind_pair_on_chapter_two(fixture, decision=ReviewStatus.REJECTED)

    with pytest.raises(ValueError, match="unavailable"):
        fixture.history_service.get_detail(rejected.accepted_occurrence_ids[0])
    index_subject_ids = {
        item.occurrence_id for item in fixture.history_service.list_index(
            fixture.subject_ids["守卫"]
        )
    }
    assert index_subject_ids == set(approved.accepted_occurrence_ids)


def test_later_chapter_reveal_does_not_become_earlier_evidence(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    binding = _bind_pair(
        fixture,
        0,
        approve=True,
        title="空房间的秘密",
        summary="门后是空房间。",
        anchor="铜钥匙",
    )

    evidence = fixture.history_service.get_evidence(
        binding.accepted_occurrence_ids[0],
        target_chapter_id=fixture.chapter_ids[0],
    )

    assert evidence.outcome is EvidenceOutcome.NOT_FOUND


def test_insufficient_hits_are_preserved(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    binding = _bind_pair(fixture, 0, approve=True)

    insufficient = fixture.history_service.get_evidence(
        binding.accepted_occurrence_ids[0],
        target_chapter_id=fixture.chapter_ids[2],
        required_hits=8,
    )

    assert insufficient.outcome is EvidenceOutcome.INSUFFICIENT
    assert 0 < len(insufficient.hits) < 8


def test_single_revision_invalidates_only_local_history(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = _bind_pair(fixture, 0, approve=True)
    second = _bind_pair(fixture, 1, approve=True)
    ChapterRepository(fixture.project).save_content(
        fixture.chapter_ids[0],
        "第一章\r\n\r\n艾琳把铜钥匙藏了起来。\r\n守卫仍没有察觉。\r\n",
        source="test",
        reason="local revision",
        expected_revision=0,
    )

    first_after = fixture.repository.get_occurrence(first.accepted_occurrence_ids[0])
    second_after = fixture.repository.get_occurrence(second.accepted_occurrence_ids[0])
    assert first_after.source_changed is True or first_after.stale is True
    assert second_after.stale is False and second_after.source_changed is False

    remaining = {
        item.occurrence_id
        for item in fixture.history_service.list_index(fixture.subject_ids["守卫"])
    }
    assert remaining == set(second.accepted_occurrence_ids)


def test_delete_restore_lifecycle_matches_queue_and_history(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    pending_on_deleted = _bind_pair(fixture, 0, approve=False)
    surviving = _bind_pair(fixture, 1, approve=True)

    chapters = ChapterRepository(fixture.project)
    chapters.delete_chapter(fixture.chapter_ids[0])

    queue_ids = {
        item.id for item in fixture.repository.list_review_candidates()
    }
    assert queue_ids.isdisjoint(set(pending_on_deleted.accepted_occurrence_ids))
    history_ids = {
        item.occurrence_id
        for item in fixture.history_service.list_index(
            fixture.subject_ids["艾琳"]
        )
    }
    assert history_ids == set(surviving.accepted_occurrence_ids)

    chapters.restore_chapter(fixture.chapter_ids[0])

    # fail-closed：restore 不自动恢复失效标记，等待显式 revalidation
    queue_after = {
        item.id for item in fixture.repository.list_review_candidates()
    }
    assert queue_after.isdisjoint(set(pending_on_deleted.accepted_occurrence_ids))
    pending_after = fixture.repository.get_occurrence(
        pending_on_deleted.accepted_occurrence_ids[0]
    )
    assert pending_after.stale is True
    history_after = {
        item.occurrence_id
        for item in fixture.history_service.list_index(
            fixture.subject_ids["艾琳"]
        )
    }
    assert history_after.isdisjoint(set(pending_on_deleted.accepted_occurrence_ids))


def _bind_pair_on_chapter_two(
    fixture: Fixture,
    *,
    decision: ReviewStatus,
):
    binding = _bind_pair(fixture, 1, approve=False)
    occurrence_id = binding.accepted_occurrence_ids[0]
    occurrence = fixture.repository.get_occurrence(occurrence_id)
    fixture.review_service.review_occurrence(
        occurrence_id,
        expected_updated_at=occurrence.updated_at.isoformat(),
        decision=decision,
        confirmed_by_user=True,
    )
    return binding
