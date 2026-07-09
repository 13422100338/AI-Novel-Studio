from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

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
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


class AuditRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create_run(
        self,
        *,
        chapter_id: str,
        target_kind: AuditTargetKind,
        target_id: str,
        target_revision: int,
        target_hash: str,
        mode: CreationMode,
        status: AuditRunStatus,
        prompt_version: str,
        model_provider_id: str | None = None,
        model_id: str | None = None,
    ) -> AuditRun:
        run_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO audit_runs(
                    id, chapter_id, target_kind, target_id, target_revision, target_hash,
                    mode, status, model_provider_id, model_id, prompt_version,
                    started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    chapter_id,
                    target_kind.value,
                    target_id,
                    target_revision,
                    target_hash,
                    mode.value,
                    status.value,
                    model_provider_id,
                    model_id,
                    prompt_version,
                    now,
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> AuditRun:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM audit_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown audit run: {run_id}")
        return self._run_from_row(row)

    def list_runs_for_target(
        self,
        *,
        target_kind: AuditTargetKind,
        target_id: str,
    ) -> tuple[AuditRun, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM audit_runs
                WHERE target_kind = ? AND target_id = ?
                ORDER BY started_at DESC, id DESC
                """,
                (target_kind.value, target_id),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def update_run_status(self, run_id: str, status: AuditRunStatus) -> AuditRun:
        now = _now().isoformat()
        completed_at = now if status in {AuditRunStatus.COMPLETED, AuditRunStatus.FAILED} else None
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE audit_runs SET status = ?, completed_at = ? WHERE id = ?",
                (status.value, completed_at, run_id),
            )
        return self.get_run(run_id)

    def add_finding(
        self,
        *,
        run_id: str,
        category: AuditFindingCategory,
        severity: AuditSeverity,
        source: AuditFindingSource,
        location_json: str,
        evidence: str,
        explanation: str,
        related_source_json: str,
        confidence: float,
        status: AuditFindingStatus = AuditFindingStatus.OPEN,
    ) -> AuditFinding:
        finding_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO audit_findings(
                    id, run_id, category, severity, source, location_json, evidence,
                    explanation, related_source_json, confidence, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    run_id,
                    category.value,
                    severity.value,
                    source.value,
                    location_json,
                    evidence,
                    explanation,
                    related_source_json,
                    confidence,
                    status.value,
                    now,
                    now,
                ),
            )
        return self.get_finding(finding_id)

    def get_finding(self, finding_id: str) -> AuditFinding:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM audit_findings WHERE id = ?", (finding_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown audit finding: {finding_id}")
        return self._finding_from_row(row)

    def list_findings(self, run_id: str) -> tuple[AuditFinding, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_findings WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return tuple(self._finding_from_row(row) for row in rows)

    def update_finding_status(
        self, finding_id: str, status: AuditFindingStatus
    ) -> AuditFinding:
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE audit_findings SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, finding_id),
            )
        return self.get_finding(finding_id)

    def add_repair_proposal(
        self,
        *,
        finding_id: str,
        target_revision: int,
        target_hash: str,
        strategy: RepairStrategy,
        target_text: str,
        replacement_text: str,
        patch_json: str,
        explanation: str,
        risk_note: str,
        status: RepairProposalStatus,
    ) -> RepairProposal:
        proposal_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO repair_proposals(
                    id, finding_id, target_revision, target_hash, strategy,
                    target_text, replacement_text, patch_json, explanation, risk_note,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    finding_id,
                    target_revision,
                    target_hash,
                    strategy.value,
                    target_text,
                    replacement_text,
                    patch_json,
                    explanation,
                    risk_note,
                    status.value,
                    now,
                ),
            )
        return self.get_repair_proposal(proposal_id)

    def get_repair_proposal(self, proposal_id: str) -> RepairProposal:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM repair_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown repair proposal: {proposal_id}")
        return self._proposal_from_row(row)

    def update_repair_status(
        self, proposal_id: str, status: RepairProposalStatus
    ) -> RepairProposal:
        applied_at = _now().isoformat() if status == RepairProposalStatus.APPLIED else None
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE repair_proposals SET status = ?, applied_at = ? WHERE id = ?",
                (status.value, applied_at, proposal_id),
            )
        return self.get_repair_proposal(proposal_id)

    def add_provenance_event(
        self,
        *,
        chapter_id: str,
        chapter_revision_before: int,
        chapter_revision_after: int,
        event_type: ProvenanceEventType,
        source_audit_run_id: str | None,
        source_finding_id: str | None,
        source_repair_id: str | None,
        summary: str,
    ) -> ProvenanceEvent:
        event_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO provenance_events(
                    id, chapter_id, chapter_revision_before, chapter_revision_after,
                    event_type, source_audit_run_id, source_finding_id, source_repair_id,
                    summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    chapter_id,
                    chapter_revision_before,
                    chapter_revision_after,
                    event_type.value,
                    source_audit_run_id,
                    source_finding_id,
                    source_repair_id,
                    summary,
                    now,
                ),
            )
        return self.get_provenance_event(event_id)

    def get_provenance_event(self, event_id: str) -> ProvenanceEvent:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM provenance_events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown provenance event: {event_id}")
        return self._event_from_row(row)

    def list_provenance(self, chapter_id: str) -> tuple[ProvenanceEvent, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM provenance_events WHERE chapter_id = ? ORDER BY created_at, id",
                (chapter_id,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> AuditRun:
        return AuditRun(
            row["id"],
            row["chapter_id"],
            AuditTargetKind(row["target_kind"]),
            row["target_id"],
            row["target_revision"],
            row["target_hash"],
            CreationMode(row["mode"]),
            AuditRunStatus(row["status"]),
            row["model_provider_id"],
            row["model_id"],
            row["prompt_version"],
            row["input_tokens"],
            row["output_tokens"],
            row["cached_input_tokens"],
            row["reasoning_tokens"],
            row["failure_code"],
            row["failure_message"],
            datetime.fromisoformat(row["started_at"]),
            datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    @staticmethod
    def _finding_from_row(row: sqlite3.Row) -> AuditFinding:
        return AuditFinding(
            row["id"],
            row["run_id"],
            AuditFindingCategory(row["category"]),
            AuditSeverity(row["severity"]),
            AuditFindingSource(row["source"]),
            row["location_json"],
            row["evidence"],
            row["explanation"],
            row["related_source_json"],
            row["confidence"],
            AuditFindingStatus(row["status"]),
            datetime.fromisoformat(row["created_at"]),
            datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row) -> RepairProposal:
        return RepairProposal(
            row["id"],
            row["finding_id"],
            row["target_revision"],
            row["target_hash"],
            RepairStrategy(row["strategy"]),
            row["target_text"],
            row["replacement_text"],
            row["patch_json"],
            row["explanation"],
            row["risk_note"],
            RepairProposalStatus(row["status"]),
            datetime.fromisoformat(row["created_at"]),
            datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> ProvenanceEvent:
        return ProvenanceEvent(
            row["id"],
            row["chapter_id"],
            row["chapter_revision_before"],
            row["chapter_revision_after"],
            ProvenanceEventType(row["event_type"]),
            row["source_audit_run_id"],
            row["source_finding_id"],
            row["source_repair_id"],
            row["summary"],
            datetime.fromisoformat(row["created_at"]),
        )
