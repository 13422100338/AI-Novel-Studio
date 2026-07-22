from pathlib import Path

import pytest

from ai_novel_studio.application.model_audit_service import (
    ModelAuditFindingInput,
    ModelAuditService,
)
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditSeverity,
    AuditTargetKind,
)
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Model Audit")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "body",
    )
    return project, chapter, AuditRepository(project)


def test_model_audit_service_validates_and_persists_model_findings(tmp_path: Path) -> None:
    _, chapter, audits = _workspace(tmp_path)
    service = ModelAuditService(audits)

    result = service.record_findings(
        chapter_id=chapter.id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter.id,
        target_revision=chapter.revision,
        target_hash="hash",
        mode=CreationMode.STANDARD,
        model_provider_id="provider",
        model_id="audit-model",
        prompt_version="model-audit-v1",
        audit_policy=AuditPolicy.DEEP,
        findings=(
            ModelAuditFindingInput(
                category="CHARACTER",
                severity="ERROR",
                quote="old line",
                evidence="character state conflict",
                explanation="character knowledge regressed",
                confidence=0.8,
            ),
        ),
    )

    assert result.run.model_id == "audit-model"
    assert result.run.mode == CreationMode.STANDARD
    assert result.run.audit_policy == AuditPolicy.DEEP
    assert result.findings[0].source == AuditFindingSource.MODEL
    assert result.findings[0].category == AuditFindingCategory.CHARACTER
    assert result.findings[0].severity == AuditSeverity.ERROR
    assert audits.list_findings(result.run.id) == result.findings


def test_model_audit_service_rejects_invalid_category_and_confidence(tmp_path: Path) -> None:
    _, chapter, audits = _workspace(tmp_path)
    service = ModelAuditService(audits)

    with pytest.raises(ValueError, match="category"):
        service.record_findings(
            chapter_id=chapter.id,
            target_kind=AuditTargetKind.FORMAL_CHAPTER,
            target_id=chapter.id,
            target_revision=chapter.revision,
            target_hash="hash",
            mode=CreationMode.STANDARD,
            model_provider_id="provider",
            model_id="audit-model",
            prompt_version="model-audit-v1",
            findings=(
                ModelAuditFindingInput(
                    category="UNKNOWN",
                    severity="ERROR",
                    quote="old line",
                    evidence="evidence",
                    explanation="explanation",
                    confidence=0.8,
                ),
            ),
        )

    with pytest.raises(ValueError, match="confidence"):
        ModelAuditFindingInput(
            category="STYLE",
            severity="WARNING",
            quote="old line",
            evidence="evidence",
            explanation="explanation",
            confidence=2.0,
        )
