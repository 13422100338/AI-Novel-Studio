from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.changeset_service import (
    ChangeSetResult,
    ChangeSetService,
    OperationStatus,
)
from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.repair_application_service import (
    RepairApplicationService,
)
from ai_novel_studio.application.subject_merge_service import SubjectMergeService
from ai_novel_studio.domain.changeset import (
    ChangeOperation,
    ChangeOperationKind,
    ChangeSet,
)
from ai_novel_studio.domain.character_identity import CharacterIdentityMerge, CharacterMergeStatus
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_resolver import (
    ApprovalResolution,
    ApprovalResolver,
    StaleSubjectMergeError,
    UnsupportedCommitError,
    changeset_from_payload,
    changeset_to_payload,
    subject_merge_from_payload,
    subject_merge_to_payload,
)
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunStage
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _resolver(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Approval resolver")
    store = HarnessEventStore(HarnessEventRepository(project))
    approvals = ApprovalService(store, ApprovalRepository(project))
    chapters = ChapterRepository(project)
    changesets = ChangeSetService(
        chapters,
        ChapterRevisionService(project),
        RepairApplicationService(chapters, AuditRepository(project)),
    )
    merges = SubjectMergeService(project)
    resolver = ApprovalResolver(
        approvals,
        changesets=changesets,
        merges=merges,
        store=store,
        approvals_repository=ApprovalRepository(project),
    )
    run, _ = store.start_run(goal="解决审批")
    return project, store, approvals, resolver, run


def _content_change_set(chapter_id: str, revision: int, content: str = "v1") -> ChangeSet:
    return ChangeSet(
        str(new_id()),
        (
            ChangeOperation(
                str(new_id()),
                ChangeOperationKind.CHAPTER_CONTENT_REPLACE,
                chapter_id,
                revision,
                {"content": content, "source": "agent", "reason": "polish"},
            ),
        ),
    )


def test_changeset_approved_commits_to_backend(tmp_path: Path) -> None:
    project, _store, approvals, resolver, run = _resolver(tmp_path)
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    chapter = revisions.submit_creation(volume.id, "Chapter", content="v0").chapter
    change_set = _content_change_set(chapter.id, chapter.revision)

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="替换开场",
        payload=changeset_to_payload(change_set),
        idempotency_key="cs-1",
    )
    resolution = resolver.resolve_and_commit(
        request.request_id, approved=True, resolution_note="作者认可"
    )

    assert isinstance(resolution, ApprovalResolution)
    assert isinstance(resolution.result, ChangeSetResult)
    assert all(
        outcome.status is OperationStatus.APPLIED for outcome in resolution.result.outcomes
    )
    updated = ChapterRepository(project).get_chapter(chapter.id)
    assert updated.revision == chapter.revision + 1


def test_changeset_rejected_never_commits(tmp_path: Path) -> None:
    project, _store, approvals, resolver, run = _resolver(tmp_path)
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    chapter = revisions.submit_creation(volume.id, "Chapter", content="v0").chapter
    change_set = _content_change_set(chapter.id, chapter.revision)

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="替换开场",
        payload=changeset_to_payload(change_set),
        idempotency_key="cs-1",
    )
    resolution = resolver.resolve_and_commit(request.request_id, approved=False)

    assert resolution.result is None
    assert resolution.approval.status is ApprovalStatus.REJECTED
    assert ChapterRepository(project).get_chapter(chapter.id).revision == chapter.revision


def test_stale_changeset_fails_closed_approval_stays_approved(tmp_path: Path) -> None:
    project, _store, approvals, resolver, run = _resolver(tmp_path)
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    chapter = revisions.submit_creation(volume.id, "Chapter", content="v0").chapter
    change_set = _content_change_set(chapter.id, chapter.revision + 5)

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="过期替换",
        payload=changeset_to_payload(change_set),
        idempotency_key="cs-1",
    )
    resolution = resolver.resolve_and_commit(request.request_id, approved=True)

    assert resolution.approval.status is ApprovalStatus.APPROVED
    assert isinstance(resolution.result, ChangeSetResult)
    assert all(
        outcome.status is OperationStatus.FAILED for outcome in resolution.result.outcomes
    )
    assert ChapterRepository(project).get_chapter(chapter.id).revision == chapter.revision


def test_subject_merge_approved_commits_to_backend(tmp_path: Path) -> None:
    project, _store, approvals, resolver, run = _resolver(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克", aliases=("白鸦镇领主",))
    target = memory.create_character("艾瑞克·温德米尔")

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SUBJECT_MERGE,
        summary="合并重复人物卡",
        payload=subject_merge_to_payload(
            source.id, target.id, reason="同一人物"
        ),
        idempotency_key="sm-1",
    )
    resolution = resolver.resolve_and_commit(request.request_id, approved=True)

    assert isinstance(resolution.result, CharacterIdentityMerge)
    assert resolution.result.status is CharacterMergeStatus.APPLIED
    assert resolution.result.source_character_id == source.id
    assert resolution.result.target_character_id == target.id


def test_subject_merge_rejected_never_commits(tmp_path: Path) -> None:
    project, _store, approvals, resolver, run = _resolver(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SUBJECT_MERGE,
        summary="合并重复人物卡",
        payload=subject_merge_to_payload(source.id, target.id, reason="同一人物"),
        idempotency_key="sm-1",
    )
    resolution = resolver.resolve_and_commit(request.request_id, approved=False)

    assert resolution.result is None
    assert resolution.approval.status is ApprovalStatus.REJECTED
    assert memory.get_character(source.id).canonical_name == "艾瑞克"


def test_unsupported_kinds_raise_after_resolution(tmp_path: Path) -> None:
    _project, _store, approvals, resolver, run = _resolver(tmp_path)

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.PROMPT_CHANGE,
        summary="改系统提示词",
        payload={},
        idempotency_key="pc-1",
    )
    with pytest.raises(UnsupportedCommitError):
        resolver.resolve_and_commit(request.request_id, approved=True)


def test_malformed_payloads_fail_before_any_write(tmp_path: Path) -> None:
    project, _store, approvals, resolver, run = _resolver(tmp_path)
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    chapter = revisions.submit_creation(volume.id, "Chapter", content="v0").chapter

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="坏载荷",
        payload={"operations": [{"kind": "CHAPTER_CONTENT_REPLACE"}]},
        idempotency_key="bad-1",
    )
    with pytest.raises(ValueError):
        resolver.resolve_and_commit(request.request_id, approved=True)
    assert ChapterRepository(project).get_chapter(chapter.id).revision == chapter.revision


def test_payload_codecs_round_trip(tmp_path: Path) -> None:
    _project, _store, _approvals, resolver, _run = _resolver(tmp_path)
    assert resolver is not None
    change_set = _content_change_set(str(new_id()), 3)
    assert changeset_from_payload(changeset_to_payload(change_set)) == change_set
    source, target, reason = subject_merge_from_payload(
        subject_merge_to_payload(str(new_id()), str(new_id()), reason=" 同一人物 ")
    )
    assert reason == "同一人物"
    assert source != target


def test_stale_merge_revision_refuses_commit_and_keeps_approval_pending(
    tmp_path: Path,
) -> None:
    project, store, approvals, resolver, run = _resolver(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SUBJECT_MERGE,
        summary="合并重复人物卡",
        payload=subject_merge_to_payload(source.id, target.id, reason="同一人物"),
        expected_revisions=(("subject.state_events:" + source.id, 999),),
        idempotency_key="sm-1",
    )

    with pytest.raises(StaleSubjectMergeError, match="changed since proposal"):
        resolver.resolve_and_commit(request.request_id, approved=True)

    assert (
        ApprovalRepository(project).get(request.request_id).status
        is ApprovalStatus.PENDING
    )
    stale_run = store.get_run(run.id)
    assert stale_run.stage is RunStage.STALE
    assert "SUBJECT_REVISION_CONFLICT" in (stale_run.failure_code or "")
    assert memory.get_character(source.id) is not None


def test_matching_merge_revision_commits(tmp_path: Path) -> None:
    project, _store, approvals, resolver, run = _resolver(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")
    preview = SubjectMergeService(project).preview(source.id, target.id)

    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SUBJECT_MERGE,
        summary="合并重复人物卡",
        payload=subject_merge_to_payload(source.id, target.id, reason="同一人物"),
        expected_revisions=(
            ("subject.state_events:" + source.id, preview.state_event_count),
        ),
        idempotency_key="sm-1",
    )
    resolution = resolver.resolve_and_commit(request.request_id, approved=True)

    assert isinstance(resolution.result, CharacterIdentityMerge)
    assert resolution.result.status is CharacterMergeStatus.APPLIED
