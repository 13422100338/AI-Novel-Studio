from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from ai_novel_studio.domain.audit import (
    AuditFinding,
    AuditFindingCategory,
    AuditFindingSource,
    AuditFindingStatus,
    AuditRun,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
    ProvenanceEvent,
    ProvenanceEventType,
    RepairProposal,
    RepairProposalStatus,
    RepairStrategy,
)
from ai_novel_studio.domain.generation import CreationMode


def _now() -> datetime:
    return datetime.now(UTC)


def test_audit_enums_expose_stable_storage_values() -> None:
    assert AuditTargetKind.GENERATED_DRAFT.value == "GENERATED_DRAFT"
    assert AuditRunStatus.MODEL_CHECKED.value == "MODEL_CHECKED"
    assert AuditFindingCategory.KNOWLEDGE.value == "KNOWLEDGE"
    assert AuditSeverity.BLOCKER.value == "BLOCKER"
    assert AuditFindingSource.DETERMINISTIC.value == "DETERMINISTIC"
    assert AuditFindingStatus.FALSE_POSITIVE.value == "FALSE_POSITIVE"
    assert RepairStrategy.REPLACE_TEXT.value == "REPLACE_TEXT"
    assert RepairProposalStatus.STALE.value == "STALE"
    assert ProvenanceEventType.REPAIR_APPLIED.value == "REPAIR_APPLIED"


def test_audit_records_are_immutable_and_keep_traceability() -> None:
    now = _now()
    run = AuditRun(
        id="audit-run-1",
        chapter_id="chapter-1",
        target_kind=AuditTargetKind.GENERATED_DRAFT,
        target_id="generation-run-1",
        target_revision=3,
        target_hash="target-hash",
        mode=CreationMode.STRICT,
        status=AuditRunStatus.COMPLETED,
        model_provider_id="provider-1",
        model_id="audit-model",
        prompt_version="audit-v1",
        input_tokens=1200,
        output_tokens=200,
        cached_input_tokens=600,
        reasoning_tokens=50,
        failure_code=None,
        failure_message=None,
        started_at=now,
        completed_at=now,
    )
    finding = AuditFinding(
        id="finding-1",
        run_id=run.id,
        category=AuditFindingCategory.CHARACTER,
        severity=AuditSeverity.WARNING,
        source=AuditFindingSource.MODEL,
        location_json='{"quote":"she forgot"}',
        evidence="character knew this in chapter 2",
        explanation="knowledge state regressed without explanation",
        related_source_json='[{"type":"character_state","id":"character-1"}]',
        confidence=0.75,
        status=AuditFindingStatus.OPEN,
        created_at=now,
        updated_at=now,
    )
    proposal = RepairProposal(
        id="repair-1",
        finding_id=finding.id,
        target_revision=run.target_revision,
        target_hash=run.target_hash,
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="she forgot",
        replacement_text="she pretended not to know",
        patch_json='{"op":"replace"}',
        explanation="preserves the character knowledge boundary",
        risk_note="may reveal the deception too early",
        status=RepairProposalStatus.VALIDATED,
        created_at=now,
        applied_at=None,
    )
    event = ProvenanceEvent(
        id="event-1",
        chapter_id=run.chapter_id,
        chapter_revision_before=3,
        chapter_revision_after=4,
        event_type=ProvenanceEventType.REPAIR_APPLIED,
        source_audit_run_id=run.id,
        source_finding_id=finding.id,
        source_repair_id=proposal.id,
        summary="accepted one local replacement",
        created_at=now,
    )

    assert finding.run_id == run.id
    assert proposal.finding_id == finding.id
    assert event.source_repair_id == proposal.id
    with pytest.raises(FrozenInstanceError):
        finding.status = AuditFindingStatus.REJECTED  # type: ignore[misc]


def test_invalid_audit_confidence_revisions_and_tokens_are_rejected() -> None:
    now = _now()
    with pytest.raises(ValueError, match="confidence"):
        AuditFinding(
            "finding-1",
            "run-1",
            AuditFindingCategory.STYLE,
            AuditSeverity.INFO,
            AuditFindingSource.MODEL,
            "{}",
            "evidence",
            "explanation",
            "[]",
            1.5,
            AuditFindingStatus.OPEN,
            now,
            now,
        )
    with pytest.raises(ValueError, match="target_revision"):
        AuditRun(
            "run-1",
            "chapter-1",
            AuditTargetKind.FORMAL_CHAPTER,
            "chapter-1",
            -1,
            "hash",
            CreationMode.BASIC,
            AuditRunStatus.PREPARING,
            None,
            None,
            "audit-v1",
            None,
            None,
            None,
            None,
            None,
            None,
            now,
            None,
        )
    with pytest.raises(ValueError, match="Token"):
        AuditRun(
            "run-1",
            "chapter-1",
            AuditTargetKind.FORMAL_CHAPTER,
            "chapter-1",
            0,
            "hash",
            CreationMode.BASIC,
            AuditRunStatus.PREPARING,
            None,
            None,
            "audit-v1",
            -1,
            None,
            None,
            None,
            None,
            None,
            now,
            None,
        )


def test_repair_proposal_rejects_empty_replacement_for_text_edit() -> None:
    with pytest.raises(ValueError, match="replacement_text"):
        RepairProposal(
            id="repair-1",
            finding_id="finding-1",
            target_revision=1,
            target_hash="hash",
            strategy=RepairStrategy.REPLACE_TEXT,
            target_text="old text",
            replacement_text="",
            patch_json="{}",
            explanation="reason",
            risk_note="risk",
            status=RepairProposalStatus.DRAFT,
            created_at=_now(),
            applied_at=None,
        )

