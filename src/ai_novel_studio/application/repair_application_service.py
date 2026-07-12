from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ai_novel_studio.domain.audit import (
    AuditFinding,
    AuditFindingStatus,
    ProvenanceEvent,
    ProvenanceEventType,
    RepairProposal,
    RepairProposalStatus,
    RepairStrategy,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
    StaleChapterRevisionError,
)


class RepairApplicationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AppliedRepair:
    chapter: Chapter
    finding: AuditFinding
    proposal: RepairProposal
    provenance: ProvenanceEvent


class RepairApplicationService:
    def __init__(self, chapters: ChapterRepository, audits: AuditRepository) -> None:
        self.chapters = chapters
        self.audits = audits

    def create_validated_text_repair(
        self,
        *,
        finding_id: str,
        chapter_id: str,
        strategy: RepairStrategy,
        target_text: str,
        replacement_text: str,
        explanation: str,
        risk_note: str,
    ) -> RepairProposal:
        chapter = self.chapters.get_chapter(chapter_id, include_deleted=False)
        text = self.chapters.read_content(chapter_id)
        if strategy in {RepairStrategy.REPLACE_TEXT, RepairStrategy.DELETE_TEXT}:
            if not target_text or target_text not in text:
                raise RepairApplicationError("target text was not found in chapter")
        if strategy in {RepairStrategy.REPLACE_TEXT, RepairStrategy.INSERT_TEXT}:
            if not replacement_text.strip():
                raise RepairApplicationError("replacement text cannot be empty")
        return self.audits.add_repair_proposal(
            finding_id=finding_id,
            target_revision=chapter.revision,
            target_hash=_hash(text),
            strategy=strategy,
            target_text=target_text,
            replacement_text=replacement_text,
            patch_json=json.dumps(
                {
                    "strategy": strategy.value,
                    "target_text": target_text,
                    "replacement_text": replacement_text,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            explanation=explanation,
            risk_note=risk_note,
            status=RepairProposalStatus.VALIDATED,
        )

    def apply(
        self,
        proposal_id: str,
        *,
        chapter_id: str,
        expected_revision: int,
    ) -> AppliedRepair:
        proposal = self.audits.get_repair_proposal(proposal_id)
        if proposal.status != RepairProposalStatus.VALIDATED:
            raise RepairApplicationError(
                f"repair proposal is not validated: {proposal.status.value}"
            )
        chapter = self.chapters.get_chapter(chapter_id, include_deleted=False)
        text = self.chapters.read_content(chapter_id)
        if chapter.revision != expected_revision or proposal.target_revision != chapter.revision:
            self.audits.update_repair_status(proposal.id, RepairProposalStatus.STALE)
            raise RepairApplicationError("stale repair proposal revision")
        if proposal.target_hash != _hash(text):
            self.audits.update_repair_status(proposal.id, RepairProposalStatus.STALE)
            raise RepairApplicationError("stale repair proposal hash")
        repaired = self._apply_text_strategy(text, proposal)
        try:
            updated_chapter = self.chapters.save_content(
                chapter_id,
                repaired,
                source="audit_repair",
                reason=f"accepted repair proposal {proposal.id}",
                expected_revision=expected_revision,
            )
        except StaleChapterRevisionError as error:
            self.audits.update_repair_status(proposal.id, RepairProposalStatus.STALE)
            raise RepairApplicationError("stale repair proposal revision") from error
        updated_proposal = self.audits.update_repair_status(
            proposal.id, RepairProposalStatus.APPLIED
        )
        finding = self.audits.update_finding_status(
            proposal.finding_id, AuditFindingStatus.ACCEPTED_REPAIR
        )
        provenance = self.audits.add_provenance_event(
            chapter_id=chapter_id,
            chapter_revision_before=chapter.revision,
            chapter_revision_after=updated_chapter.revision,
            event_type=ProvenanceEventType.REPAIR_APPLIED,
            source_audit_run_id=finding.run_id,
            source_finding_id=finding.id,
            source_repair_id=proposal.id,
            summary=proposal.explanation,
        )
        return AppliedRepair(updated_chapter, finding, updated_proposal, provenance)

    @staticmethod
    def _apply_text_strategy(text: str, proposal: RepairProposal) -> str:
        if proposal.strategy == RepairStrategy.REPLACE_TEXT:
            if proposal.target_text not in text:
                raise RepairApplicationError("target text was not found in chapter")
            return text.replace(proposal.target_text, proposal.replacement_text, 1)
        if proposal.strategy == RepairStrategy.DELETE_TEXT:
            if proposal.target_text not in text:
                raise RepairApplicationError("target text was not found in chapter")
            return text.replace(proposal.target_text, "", 1)
        if proposal.strategy == RepairStrategy.INSERT_TEXT:
            if proposal.target_text and proposal.target_text in text:
                return text.replace(
                    proposal.target_text,
                    proposal.target_text + proposal.replacement_text,
                    1,
                )
            return text + proposal.replacement_text
        if proposal.strategy == RepairStrategy.NOTE_ONLY:
            return text
        raise RepairApplicationError(f"unsupported repair strategy: {proposal.strategy.value}")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

