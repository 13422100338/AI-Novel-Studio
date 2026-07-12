from __future__ import annotations

import json
from dataclasses import dataclass

from ai_novel_studio.domain.audit import (
    AuditFinding,
    AuditFindingCategory,
    AuditFindingSource,
    AuditRun,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
)
from ai_novel_studio.domain.generation import CreationMode
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository


@dataclass(frozen=True, slots=True)
class ModelAuditFindingInput:
    category: str
    severity: str
    quote: str
    evidence: str
    explanation: str
    confidence: float

    def __post_init__(self) -> None:
        for field in ("category", "severity", "evidence", "explanation"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} cannot be empty")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ModelAuditRecordResult:
    run: AuditRun
    findings: tuple[AuditFinding, ...]


class ModelAuditService:
    def __init__(self, audits: AuditRepository) -> None:
        self.audits = audits

    def record_findings(
        self,
        *,
        chapter_id: str,
        target_kind: AuditTargetKind,
        target_id: str,
        target_revision: int,
        target_hash: str,
        mode: CreationMode,
        model_provider_id: str,
        model_id: str,
        prompt_version: str,
        findings: tuple[ModelAuditFindingInput, ...],
    ) -> ModelAuditRecordResult:
        run = self.audits.create_run(
            chapter_id=chapter_id,
            target_kind=target_kind,
            target_id=target_id,
            target_revision=target_revision,
            target_hash=target_hash,
            mode=mode,
            status=AuditRunStatus.MODEL_CHECKED,
            prompt_version=prompt_version,
            model_provider_id=model_provider_id,
            model_id=model_id,
        )
        saved = tuple(
            self.audits.add_finding(
                run_id=run.id,
                category=_category(item.category),
                severity=_severity(item.severity),
                source=AuditFindingSource.MODEL,
                location_json=json.dumps(
                    {"quote": item.quote},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                evidence=item.evidence,
                explanation=item.explanation,
                related_source_json="[]",
                confidence=item.confidence,
            )
            for item in findings
        )
        completed = self.audits.update_run_status(run.id, AuditRunStatus.COMPLETED)
        return ModelAuditRecordResult(completed, saved)


def _category(value: str) -> AuditFindingCategory:
    try:
        return AuditFindingCategory(value.strip().upper())
    except ValueError as error:
        raise ValueError(f"unknown audit finding category: {value}") from error


def _severity(value: str) -> AuditSeverity:
    try:
        return AuditSeverity(value.strip().upper())
    except ValueError as error:
        raise ValueError(f"unknown audit severity: {value}") from error

