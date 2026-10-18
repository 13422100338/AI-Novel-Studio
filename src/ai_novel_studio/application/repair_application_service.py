from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.domain.audit import (
    AuditFinding,
    AuditFindingStatus,
    AuditTargetKind,
    ProvenanceEvent,
    ProvenanceEventType,
    RepairProposal,
    RepairProposalStatus,
    RepairStrategy,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterFileTransaction,
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


@dataclass(frozen=True, slots=True)
class PreparedRepair:
    chapter_id: str
    expected_revision: int
    source_hash: str
    repaired_content: str
    finding: AuditFinding
    proposal: RepairProposal


class RepairApplicationService:
    def __init__(
        self,
        chapters: ChapterRepository,
        audits: AuditRepository,
        *,
        revision_service: ChapterRevisionService | None = None,
    ) -> None:
        self.chapters = chapters
        self.audits = audits
        self.revision_service = revision_service or ChapterRevisionService(chapters.project)

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

    def prepare_apply(
        self,
        proposal_id: str,
        *,
        chapter_id: str,
        expected_revision: int,
        source_content: str,
        connection: sqlite3.Connection | None = None,
    ) -> PreparedRepair:
        proposal = self.audits.get_repair_proposal(
            proposal_id,
            connection=connection,
        )
        if proposal.status is not RepairProposalStatus.VALIDATED:
            raise RepairApplicationError(
                f"repair proposal is not validated: {proposal.status.value}"
            )
        if proposal.target_revision != expected_revision:
            raise RepairApplicationError("stale repair proposal revision")
        source_hash = _hash(source_content)
        if proposal.target_hash != source_hash:
            raise RepairApplicationError("stale repair proposal hash")
        finding = self.audits.get_finding(
            proposal.finding_id,
            connection=connection,
        )
        run = self.audits.get_run(
            finding.run_id,
            connection=connection,
        )
        if (
            run.chapter_id != chapter_id
            or run.target_kind is not AuditTargetKind.FORMAL_CHAPTER
            or run.target_id != chapter_id
            or run.target_revision != expected_revision
            or run.target_hash != source_hash
        ):
            raise RepairApplicationError("repair proposal target identity is invalid")
        repaired = self._apply_text_strategy(source_content, proposal)
        return PreparedRepair(
            chapter_id,
            expected_revision,
            source_hash,
            repaired,
            finding,
            proposal,
        )

    def commit_prepared(
        self,
        prepared: PreparedRepair,
        *,
        connection: sqlite3.Connection,
        file_transaction: ChapterFileTransaction,
    ) -> AppliedRepair:
        if not isinstance(prepared, PreparedRepair):
            raise TypeError("prepared repair is invalid")
        current = self.prepare_apply(
            prepared.proposal.id,
            chapter_id=prepared.chapter_id,
            expected_revision=prepared.expected_revision,
            source_content=self.chapters.read_content_exact(
                prepared.chapter_id,
                connection=connection,
            ),
            connection=connection,
        )
        if current != prepared:
            raise RepairApplicationError("repair proposal changed before commit")
        committed = self.revision_service.commit_revision(
            prepared.chapter_id,
            prepared.repaired_content,
            source="audit_repair",
            reason=f"accepted repair proposal {prepared.proposal.id}",
            expected_revision=prepared.expected_revision,
            connection=connection,
            file_transaction=file_transaction,
        )
        updated_proposal = self.audits.update_repair_status(
            prepared.proposal.id,
            RepairProposalStatus.APPLIED,
            connection=connection,
        )
        finding = self.audits.update_finding_status(
            prepared.finding.id,
            AuditFindingStatus.ACCEPTED_REPAIR,
            connection=connection,
        )
        provenance = self.audits.add_provenance_event(
            chapter_id=prepared.chapter_id,
            chapter_revision_before=prepared.expected_revision,
            chapter_revision_after=committed.chapter.revision,
            event_type=ProvenanceEventType.REPAIR_APPLIED,
            source_audit_run_id=finding.run_id,
            source_finding_id=finding.id,
            source_repair_id=prepared.proposal.id,
            summary=prepared.proposal.explanation,
            connection=connection,
        )
        return AppliedRepair(
            committed.chapter,
            finding,
            updated_proposal,
            provenance,
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
            submitted = self.revision_service.submit_revision(
                chapter_id,
                repaired,
                source="audit_repair",
                reason=f"accepted repair proposal {proposal.id}",
                expected_revision=expected_revision,
            )
        except StaleChapterRevisionError as error:
            self.audits.update_repair_status(proposal.id, RepairProposalStatus.STALE)
            raise RepairApplicationError("stale repair proposal revision") from error
        updated_chapter = submitted.chapter
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
