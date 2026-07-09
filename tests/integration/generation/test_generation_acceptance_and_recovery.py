from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.generation_acceptance_service import (
    GenerationAcceptanceError,
    GenerationAcceptanceService,
)
from ai_novel_studio.application.generation_recovery_service import (
    GenerationRecoveryService,
)
from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
    create_manifest_id,
    utc_now,
)
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
)
from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.domain.memory import MemoryStatus, SummaryLevel
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
    StaleChapterRevisionError,
)
from ai_novel_studio.infrastructure.storage.checkpoint_repository import (
    CheckpointIntegrityError,
    CheckpointRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import (
    GenerationRepository,
    GenerationStateError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "acceptance test")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(volume.id, "chapter 1", "1", "old prose")
    runs = GenerationRepository(project)
    checkpoints = CheckpointRepository(project, runs)
    service = GenerationAcceptanceService(project, runs, checkpoints, chapters)
    return project, chapters, chapter, runs, checkpoints, service


def _preparing(runs: GenerationRepository, chapter_id: str):
    return runs.create_preparing(
        chapter_id=chapter_id,
        mode=CreationMode.BASIC,
        brief_id=None,
        brief_revision=None,
        model_provider_id="provider",
        model_id="writer",
        output_token_limit=3000,
        prompt_version="prose-v1",
    )


def _preparing_with_mode(runs: GenerationRepository, chapter_id: str, mode: CreationMode):
    return runs.create_preparing(
        chapter_id=chapter_id,
        mode=mode,
        brief_id=None,
        brief_revision=None,
        model_provider_id="provider",
        model_id="writer",
        output_token_limit=3000,
        prompt_version="prose-v1",
    )


def _ready(project: ProjectRepository, runs: GenerationRepository, run):
    manifest = ContextManifest(
        create_manifest_id(),
        run.chapter_id,
        run.id,
        100_000,
        run.output_token_limit,
        0,
        (),
        (),
        (),
        utc_now(),
    )
    ContextManifestRepository(project).save(manifest)
    return runs.transition(
        run.id,
        GenerationStatus.PREPARING,
        GenerationStatus.READY,
        context_manifest_id=manifest.id,
    )


def _streaming(project: ProjectRepository, runs: GenerationRepository, chapter_id: str):
    ready = _ready(project, runs, _preparing(runs, chapter_id))
    return runs.transition(ready.id, GenerationStatus.READY, GenerationStatus.STREAMING)


def _streaming_with_mode(
    project: ProjectRepository,
    runs: GenerationRepository,
    chapter_id: str,
    mode: CreationMode,
):
    ready = _ready(project, runs, _preparing_with_mode(runs, chapter_id, mode))
    return runs.transition(ready.id, GenerationStatus.READY, GenerationStatus.STREAMING)


def _completed_run(
    project: ProjectRepository,
    runs: GenerationRepository,
    checkpoints: CheckpointRepository,
    chapter_id: str,
    draft: str = "generated prose",
):
    streaming = _streaming(project, runs, chapter_id)
    checkpoints.append(streaming.id, draft, finish_reason="stop")
    return runs.transition(
        streaming.id,
        GenerationStatus.STREAMING,
        GenerationStatus.COMPLETED,
        output_tokens=200,
    )


def _completed_strict_run(
    project: ProjectRepository,
    runs: GenerationRepository,
    checkpoints: CheckpointRepository,
    chapter_id: str,
    draft: str = "generated prose",
):
    streaming = _streaming_with_mode(project, runs, chapter_id, CreationMode.STRICT)
    checkpoints.append(streaming.id, draft, finish_reason="stop")
    return runs.transition(
        streaming.id,
        GenerationStatus.STREAMING,
        GenerationStatus.COMPLETED,
        output_tokens=200,
    )


def _partial_run(
    project: ProjectRepository,
    runs: GenerationRepository,
    checkpoints: CheckpointRepository,
    chapter_id: str,
    draft: str = "partial generated prose",
):
    streaming = _streaming(project, runs, chapter_id)
    checkpoints.append(streaming.id, draft, finish_reason="length")
    return runs.transition(streaming.id, GenerationStatus.STREAMING, GenerationStatus.PARTIAL)


def test_completed_draft_does_not_change_formal_prose_until_accept(
    tmp_path: Path,
) -> None:
    _, chapters, chapter, runs, checkpoints, service = _workspace(tmp_path)
    old_hash = _sha256("old prose")
    run = _completed_run(_, runs, checkpoints, chapter.id, "generated prose")

    assert chapters.read_content(chapter.id) == "old prose"

    accepted = service.accept(run.id, expected_chapter_revision=0)

    assert chapters.read_content(chapter.id) == "generated prose"
    assert accepted.run.status == GenerationStatus.ACCEPTED
    assert accepted.run.accepted_chapter_revision == 1
    assert accepted.chapter.revision == 1
    versions = chapters.list_versions(chapter.id)
    assert len(versions) == 1
    assert versions[0].content_hash == old_hash
    assert (chapters.project.layout.root / versions[0].content_snapshot_path).read_text(
        encoding="utf-8"
    ) == "old prose"


def test_partial_draft_requires_explicit_allow_partial(tmp_path: Path) -> None:
    project, chapters, chapter, runs, checkpoints, service = _workspace(tmp_path)
    run = _partial_run(project, runs, checkpoints, chapter.id)

    with pytest.raises(GenerationAcceptanceError, match="partial"):
        service.accept(run.id, expected_chapter_revision=0)
    assert chapters.read_content(chapter.id) == "old prose"

    accepted = service.accept(run.id, expected_chapter_revision=0, allow_partial=True)

    assert accepted.run.status == GenerationStatus.ACCEPTED
    assert chapters.read_content(chapter.id) == "partial generated prose"


def test_concurrent_chapter_revision_rejects_accept_without_losing_checkpoint(
    tmp_path: Path,
) -> None:
    project, chapters, chapter, runs, checkpoints, service = _workspace(tmp_path)
    run = _completed_run(project, runs, checkpoints, chapter.id, "generated prose")
    latest = checkpoints.latest(run.id)
    assert latest is not None
    chapters.save_content(chapter.id, "human rewrite", source="manual", reason="edit")

    with pytest.raises(StaleChapterRevisionError):
        service.accept(run.id, expected_chapter_revision=0)

    assert chapters.read_content(chapter.id) == "human rewrite"
    assert runs.get(run.id).status == GenerationStatus.COMPLETED
    assert checkpoints.read(latest.id) == "generated prose"


def test_duplicate_acceptance_and_corrupt_checkpoint_are_rejected(
    tmp_path: Path,
) -> None:
    project, chapters, chapter, runs, checkpoints, service = _workspace(tmp_path)
    run = _completed_run(project, runs, checkpoints, chapter.id, "generated prose")
    service.accept(run.id, expected_chapter_revision=0)

    with pytest.raises(GenerationAcceptanceError, match="already accepted"):
        service.accept(run.id, expected_chapter_revision=1)

    second = chapters.create_chapter(project.list_volumes()[0].id, "chapter 2", "2", "old")
    corrupt_run = _completed_run(project, runs, checkpoints, second.id, "draft")
    latest = checkpoints.latest(corrupt_run.id)
    assert latest is not None
    (project.layout.root / latest.text_path).write_text("tampered", encoding="utf-8")

    with pytest.raises(CheckpointIntegrityError):
        service.accept(corrupt_run.id, expected_chapter_revision=0)
    assert chapters.read_content(second.id) == "old"
    assert runs.get(corrupt_run.id).status == GenerationStatus.COMPLETED


def test_acceptance_invalidates_dependent_memory(tmp_path: Path) -> None:
    project, chapters, chapter, runs, checkpoints, service = _workspace(tmp_path)
    summaries = SummaryRepository(project)
    summary = summaries.promote(
        summaries.add_candidate(
            SummaryLevel.CHAPTER,
            chapter.id,
            "old summary",
            (chapter.id,),
            model_profile_id="provider/writer",
        ).id,
        expected_revision=0,
    )
    run = _completed_run(project, runs, checkpoints, chapter.id, "generated prose")

    service.accept(run.id, expected_chapter_revision=0)

    assert summaries.get(summary.id).status == MemoryStatus.STALE


def test_discard_preserves_checkpoint_and_does_not_change_formal_prose(
    tmp_path: Path,
) -> None:
    project, chapters, chapter, runs, checkpoints, service = _workspace(tmp_path)
    run = _completed_run(project, runs, checkpoints, chapter.id, "discarded draft")
    latest = checkpoints.latest(run.id)
    assert latest is not None

    discarded = service.discard(run.id)

    assert discarded.status == GenerationStatus.DISCARDED
    assert chapters.read_content(chapter.id) == "old prose"
    assert checkpoints.latest(run.id) == latest
    assert checkpoints.read(latest.id) == "discarded draft"
    with pytest.raises(GenerationAcceptanceError, match="discarded"):
        service.accept(run.id, expected_chapter_revision=0)


def test_strict_generation_requires_completed_audit_before_acceptance(tmp_path: Path) -> None:
    project, chapters, chapter, runs, checkpoints, _ = _workspace(tmp_path)
    audits = AuditRepository(project)
    service = GenerationAcceptanceService(project, runs, checkpoints, chapters, audits)
    run = _completed_strict_run(project, runs, checkpoints, chapter.id, "strict draft")

    with pytest.raises(GenerationAcceptanceError, match="strict"):
        service.accept(run.id, expected_chapter_revision=0)

    audit_run = audits.create_run(
        chapter_id=chapter.id,
        target_kind=AuditTargetKind.GENERATED_DRAFT,
        target_id=run.id,
        target_revision=0,
        target_hash=_sha256("strict draft"),
        mode=CreationMode.STRICT,
        status=AuditRunStatus.COMPLETED,
        prompt_version="deterministic-v1",
    )
    audits.add_finding(
        run_id=audit_run.id,
        category=AuditFindingCategory.FORMAT,
        severity=AuditSeverity.ERROR,
        source=AuditFindingSource.DETERMINISTIC,
        location_json="{}",
        evidence="problem",
        explanation="blocking issue",
        related_source_json="[]",
        confidence=1.0,
    )

    with pytest.raises(GenerationAcceptanceError, match="blocking"):
        service.accept(run.id, expected_chapter_revision=0)


def test_strict_generation_accepts_after_clean_completed_audit(tmp_path: Path) -> None:
    project, chapters, chapter, runs, checkpoints, _ = _workspace(tmp_path)
    audits = AuditRepository(project)
    service = GenerationAcceptanceService(project, runs, checkpoints, chapters, audits)
    run = _completed_strict_run(project, runs, checkpoints, chapter.id, "strict draft")
    audits.create_run(
        chapter_id=chapter.id,
        target_kind=AuditTargetKind.GENERATED_DRAFT,
        target_id=run.id,
        target_revision=0,
        target_hash=_sha256("strict draft"),
        mode=CreationMode.STRICT,
        status=AuditRunStatus.COMPLETED,
        prompt_version="deterministic-v1",
    )

    accepted = service.accept(run.id, expected_chapter_revision=0)

    assert accepted.run.status == GenerationStatus.ACCEPTED
    assert chapters.read_content(chapter.id) == "strict draft"


def test_recovery_scan_returns_only_recoverable_runs_and_never_calls_model(
    tmp_path: Path,
) -> None:
    project, chapters, chapter, runs, checkpoints, _ = _workspace(tmp_path)
    ready = _ready(project, runs, _preparing(runs, chapter.id))
    second = chapters.create_chapter(project.list_volumes()[0].id, "chapter 2", "2", "")
    streaming = _streaming(project, runs, second.id)
    checkpoints.append(streaming.id, "streaming draft")
    third = chapters.create_chapter(project.list_volumes()[0].id, "chapter 3", "3", "")
    partial = _partial_run(project, runs, checkpoints, third.id, "partial draft")
    fourth = chapters.create_chapter(project.list_volumes()[0].id, "chapter 4", "4", "")
    _completed_run(project, runs, checkpoints, fourth.id, "completed draft")

    recovered = GenerationRecoveryService(runs, checkpoints).scan()

    assert [(item.run.id, item.run.status) for item in recovered] == [
        (ready.id, GenerationStatus.READY),
        (streaming.id, GenerationStatus.STREAMING),
        (partial.id, GenerationStatus.PARTIAL),
    ]
    assert [item.draft_text for item in recovered] == [
        None,
        "streaming draft",
        "partial draft",
    ]


def test_discard_can_clear_a_ready_active_writer_after_restart(tmp_path: Path) -> None:
    project, _, chapter, runs, checkpoints, service = _workspace(tmp_path)
    ready = _ready(project, runs, _preparing(runs, chapter.id))

    discarded = service.discard(ready.id)

    assert discarded.status == GenerationStatus.DISCARDED
    assert checkpoints.latest(ready.id) is None
    assert _preparing(runs, chapter.id).status == GenerationStatus.PREPARING
    with pytest.raises(GenerationStateError):
        service.discard(discarded.id)
