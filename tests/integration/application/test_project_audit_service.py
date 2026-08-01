import hashlib
from pathlib import Path

from ai_novel_studio.application.project_audit_service import ProjectAuditService
from ai_novel_studio.application.project_runtime import ProjectRuntime
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
from ai_novel_studio.domain.generation import (
    AuditPolicy,
    CreationMode,
    GenerationStatus,
)
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from tests.integration.application.test_project_runtime import FakeModelRuntime


def _completed_deep_run(
    audits: AuditRepository,
    *,
    chapter_id: str,
    generation_run_id: str,
    prompt_version: str,
):
    return audits.create_run(
        chapter_id=chapter_id,
        target_kind=AuditTargetKind.GENERATED_DRAFT,
        target_id=generation_run_id,
        target_revision=0,
        target_hash="draft-hash",
        mode=CreationMode.STANDARD,
        audit_policy=AuditPolicy.DEEP,
        status=AuditRunStatus.COMPLETED,
        prompt_version=prompt_version,
    )


def _formal_model_run(
    audits: AuditRepository,
    *,
    chapter_id: str,
    revision: int,
    content: str,
    status: AuditRunStatus,
):
    return audits.create_run(
        chapter_id=chapter_id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter_id,
        target_revision=revision,
        target_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        mode=CreationMode.STANDARD,
        audit_policy=AuditPolicy.STANDARD,
        status=status,
        prompt_version="model-audit-ui-v1",
    )


def _model_finding(audits: AuditRepository, run_id: str, evidence: str):
    return audits.add_finding(
        run_id=run_id,
        category=AuditFindingCategory.STYLE,
        severity=AuditSeverity.WARNING,
        source=AuditFindingSource.MODEL,
        location_json="{}",
        evidence=evidence,
        explanation="model finding",
        related_source_json="[]",
        confidence=0.7,
    )


def test_latest_generated_draft_deep_results_survive_reopen_and_clear_empty_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "novel"
    project = ProjectRepository.create(root, "Deep Audit Results")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "formal text",
    )
    audits = AuditRepository(project)
    generation_run_id = "generation-run-1"

    stale_model = _completed_deep_run(
        audits,
        chapter_id=chapter.id,
        generation_run_id=generation_run_id,
        prompt_version="model-audit-ui-v1",
    )
    stale_finding = audits.add_finding(
        run_id=stale_model.id,
        category=AuditFindingCategory.STYLE,
        severity=AuditSeverity.WARNING,
        source=AuditFindingSource.MODEL,
        location_json="{}",
        evidence="stale model evidence",
        explanation="stale model finding",
        related_source_json="[]",
        confidence=0.7,
    )
    latest_deterministic = _completed_deep_run(
        audits,
        chapter_id=chapter.id,
        generation_run_id=generation_run_id,
        prompt_version="deterministic-audit-v1",
    )
    deterministic_finding = audits.add_finding(
        run_id=latest_deterministic.id,
        category=AuditFindingCategory.REQUIREMENT,
        severity=AuditSeverity.ERROR,
        source=AuditFindingSource.DETERMINISTIC,
        location_json="{}",
        evidence="latest deterministic evidence",
        explanation="latest deterministic finding",
        related_source_json="[]",
        confidence=1.0,
    )
    _completed_deep_run(
        audits,
        chapter_id=chapter.id,
        generation_run_id=generation_run_id,
        prompt_version="model-audit-ui-v1",
    )

    reopened = ProjectRepository.open(root)
    results = ProjectAuditService(reopened).latest_generated_draft_deep_results(
        generation_run_id
    )

    assert results.deterministic_findings == (deterministic_finding,)
    assert results.model_findings == ()
    assert results.has_deterministic_result is True
    assert results.has_model_result is True
    assert stale_finding not in results.model_findings


def test_recovered_current_run_reads_its_persisted_latest_deep_results(
    tmp_path: Path,
) -> None:
    root = tmp_path / "novel"
    project = ProjectRepository.create(root, "Recovered Deep Audit")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "formal text",
    )
    runs = GenerationRepository(project)
    run = runs.create_preparing(
        chapter_id=chapter.id,
        mode=CreationMode.STANDARD,
        audit_policy=AuditPolicy.STANDARD,
        brief_id=None,
        brief_revision=None,
        model_provider_id="relay",
        model_id="agent-model",
        output_token_limit=1000,
        prompt_version="generation-v1",
    )
    manifest = ContextManifest(
        create_manifest_id(),
        chapter.id,
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
    run = runs.mark_ready(run.id, manifest.id)
    run = runs.transition(run.id, GenerationStatus.READY, GenerationStatus.STREAMING)
    CheckpointRepository(project, runs).append(run.id, "recovered draft")
    run = runs.transition(run.id, GenerationStatus.STREAMING, GenerationStatus.PARTIAL)
    audits = AuditRepository(project)
    deterministic = _completed_deep_run(
        audits,
        chapter_id=chapter.id,
        generation_run_id=run.id,
        prompt_version="deterministic-audit-v1",
    )
    finding = audits.add_finding(
        run_id=deterministic.id,
        category=AuditFindingCategory.REQUIREMENT,
        severity=AuditSeverity.ERROR,
        source=AuditFindingSource.DETERMINISTIC,
        location_json="{}",
        evidence="recovered evidence",
        explanation="recovered finding",
        related_source_json="[]",
        confidence=1.0,
    )

    runtime = ProjectRuntime.open(root, FakeModelRuntime(tmp_path))
    runtime.generation_session.select_chapter(chapter.id, chapter.revision)

    recovered = runtime.generation_session.recover_current()
    results = runtime.generation_session.latest_deep_audit_results()

    assert recovered is not None
    assert recovered.run.id == run.id
    assert results.deterministic_findings == (finding,)
    assert results.model_findings == ()
    assert results.has_results is True


def test_latest_formal_model_findings_ignores_stale_and_incomplete_runs(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Fresh Formal Audit")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id, "Opening", "1", "old chapter text"
    )
    audits = AuditRepository(project)
    stale = _formal_model_run(
        audits,
        chapter_id=chapter.id,
        revision=chapter.revision,
        content="old chapter text",
        status=AuditRunStatus.COMPLETED,
    )
    _model_finding(audits, stale.id, "stale evidence")
    chapter = chapters.save_content(
        chapter.id,
        "current chapter text",
        source="manual",
        reason="test revision",
        expected_revision=chapter.revision,
    )
    wrong_hash = _formal_model_run(
        audits,
        chapter_id=chapter.id,
        revision=chapter.revision,
        content="different chapter text",
        status=AuditRunStatus.COMPLETED,
    )
    _model_finding(audits, wrong_hash.id, "wrong hash evidence")
    failed = _formal_model_run(
        audits,
        chapter_id=chapter.id,
        revision=chapter.revision,
        content="current chapter text",
        status=AuditRunStatus.FAILED,
    )
    _model_finding(audits, failed.id, "failed evidence")
    preparing = _formal_model_run(
        audits,
        chapter_id=chapter.id,
        revision=chapter.revision,
        content="current chapter text",
        status=AuditRunStatus.PREPARING,
    )
    _model_finding(audits, preparing.id, "preparing evidence")

    assert ProjectAuditService(project).latest_model_findings(chapter.id) == ()


def test_latest_formal_model_zero_finding_run_clears_older_matching_findings(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Empty Formal Audit")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id, "Opening", "1", "current chapter text"
    )
    audits = AuditRepository(project)
    older = _formal_model_run(
        audits,
        chapter_id=chapter.id,
        revision=chapter.revision,
        content="current chapter text",
        status=AuditRunStatus.COMPLETED,
    )
    _model_finding(audits, older.id, "older evidence")
    _formal_model_run(
        audits,
        chapter_id=chapter.id,
        revision=chapter.revision,
        content="current chapter text",
        status=AuditRunStatus.COMPLETED,
    )

    assert ProjectAuditService(project).latest_model_findings(chapter.id) == ()
