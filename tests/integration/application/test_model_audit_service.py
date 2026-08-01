import json
from pathlib import Path

import pytest

from ai_novel_studio.application.model_audit_service import (
    ModelAuditFindingInput,
    ModelAuditService,
)
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditRunStatus,
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
                quote="  old line  ",
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
    assert json.loads(result.findings[0].location_json) == {"quote": "old line"}
    assert audits.list_findings(result.run.id) == result.findings


@pytest.mark.parametrize(
    ("category", "severity", "expected_error"),
    (
        ("UNKNOWN", "ERROR", "category"),
        ("STYLE", "UNKNOWN", "severity"),
    ),
)
def test_model_audit_service_validates_all_findings_before_writing(
    tmp_path: Path,
    category: str,
    severity: str,
    expected_error: str,
) -> None:
    _, chapter, audits = _workspace(tmp_path)
    service = ModelAuditService(audits)

    with pytest.raises(ValueError, match=expected_error):
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
                    category="STYLE",
                    severity="WARNING",
                    quote="valid line",
                    evidence="valid evidence",
                    explanation="valid explanation",
                    confidence=0.8,
                ),
                ModelAuditFindingInput(
                    category=category,
                    severity=severity,
                    quote="old line",
                    evidence="evidence",
                    explanation="explanation",
                    confidence=0.8,
                ),
            ),
        )

    assert (
        audits.list_runs_for_target(
            target_kind=AuditTargetKind.FORMAL_CHAPTER,
            target_id=chapter.id,
        )
        == ()
    )


def test_model_audit_finding_input_rejects_blank_quote() -> None:
    with pytest.raises(ValueError, match="quote"):
        ModelAuditFindingInput(
            category="STYLE",
            severity="WARNING",
            quote="  ",
            evidence="evidence",
            explanation="explanation",
            confidence=0.8,
        )


def test_model_audit_service_persists_completed_zero_finding_run(tmp_path: Path) -> None:
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
        findings=(),
    )

    assert result.run.status == AuditRunStatus.COMPLETED
    assert result.findings == ()
    assert audits.list_findings(result.run.id) == ()


def test_model_audit_finding_input_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        ModelAuditFindingInput(
            category="STYLE",
            severity="WARNING",
            quote="old line",
            evidence="evidence",
            explanation="explanation",
            confidence=2.0,
        )
