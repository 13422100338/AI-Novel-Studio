from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ai_novel_studio.domain.generation import (
    AuditPolicy,
    CreationMode,
    GenerationProfile,
    resolve_generation_settings,
)


class AuditTargetKind(StrEnum):
    GENERATED_DRAFT = "GENERATED_DRAFT"
    FORMAL_CHAPTER = "FORMAL_CHAPTER"


class AuditRunStatus(StrEnum):
    PREPARING = "PREPARING"
    RULE_CHECKED = "RULE_CHECKED"
    MODEL_CHECKED = "MODEL_CHECKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AuditFindingCategory(StrEnum):
    STYLE = "STYLE"
    REQUIREMENT = "REQUIREMENT"
    CHARACTER = "CHARACTER"
    KNOWLEDGE = "KNOWLEDGE"
    CLUE = "CLUE"
    CANON = "CANON"
    TIMELINE = "TIMELINE"
    FORMAT = "FORMAT"


class AuditSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKER = "BLOCKER"


class AuditFindingSource(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    MODEL = "MODEL"


class AuditFindingStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED_REPAIR = "ACCEPTED_REPAIR"
    REJECTED = "REJECTED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    CONVERTED_TO_CANON = "CONVERTED_TO_CANON"


class RepairStrategy(StrEnum):
    REPLACE_TEXT = "REPLACE_TEXT"
    INSERT_TEXT = "INSERT_TEXT"
    DELETE_TEXT = "DELETE_TEXT"
    NOTE_ONLY = "NOTE_ONLY"


class RepairProposalStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    INVALID = "INVALID"


class ProvenanceEventType(StrEnum):
    REPAIR_APPLIED = "REPAIR_APPLIED"
    FINDING_REJECTED = "FINDING_REJECTED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    CANON_NOTE_CREATED = "CANON_NOTE_CREATED"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    return value.strip() if value is not None else None


def _non_negative(value: int | None, field: str) -> int | None:
    if value is not None and value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def _confidence(value: float, field: str = "confidence") -> float:
    if value < 0 or value > 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return value


@dataclass(frozen=True, slots=True)
class AuditRun:
    id: str
    chapter_id: str
    target_kind: AuditTargetKind
    target_id: str
    target_revision: int
    target_hash: str
    mode: CreationMode
    status: AuditRunStatus
    model_provider_id: str | None
    model_id: str | None
    prompt_version: str
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    failure_code: str | None
    failure_message: str | None
    started_at: datetime
    completed_at: datetime | None
    audit_policy: AuditPolicy = AuditPolicy.MINIMAL

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("chapter_id", self.chapter_id),
            ("target_id", self.target_id),
            ("target_hash", self.target_hash),
            ("prompt_version", self.prompt_version),
        ):
            object.__setattr__(self, field, _required(value, field))
        for field in (
            "target_revision",
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
        ):
            _non_negative(getattr(self, field), f"{field} Token" if "tokens" in field else field)
        object.__setattr__(self, "model_provider_id", _optional_text(self.model_provider_id))
        object.__setattr__(self, "model_id", _optional_text(self.model_id))
        object.__setattr__(self, "failure_code", _optional_text(self.failure_code))
        object.__setattr__(self, "failure_message", _optional_text(self.failure_message))

    @property
    def generation_profile(self) -> GenerationProfile:
        return resolve_generation_settings(self.mode, self.audit_policy)[0]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    id: str
    run_id: str
    category: AuditFindingCategory
    severity: AuditSeverity
    source: AuditFindingSource
    location_json: str
    evidence: str
    explanation: str
    related_source_json: str
    confidence: float
    status: AuditFindingStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("run_id", self.run_id),
            ("location_json", self.location_json),
            ("evidence", self.evidence),
            ("explanation", self.explanation),
            ("related_source_json", self.related_source_json),
        ):
            object.__setattr__(self, field, _required(value, field))
        _confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class RepairProposal:
    id: str
    finding_id: str
    target_revision: int
    target_hash: str
    strategy: RepairStrategy
    target_text: str
    replacement_text: str
    patch_json: str
    explanation: str
    risk_note: str
    status: RepairProposalStatus
    created_at: datetime
    applied_at: datetime | None

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("finding_id", self.finding_id),
            ("target_hash", self.target_hash),
            ("patch_json", self.patch_json),
            ("explanation", self.explanation),
            ("risk_note", self.risk_note),
        ):
            object.__setattr__(self, field, _required(value, field))
        _non_negative(self.target_revision, "target_revision")
        if self.strategy in {
            RepairStrategy.REPLACE_TEXT,
            RepairStrategy.DELETE_TEXT,
        }:
            object.__setattr__(self, "target_text", _required(self.target_text, "target_text"))
        if self.strategy in {
            RepairStrategy.REPLACE_TEXT,
            RepairStrategy.INSERT_TEXT,
        }:
            object.__setattr__(
                self,
                "replacement_text",
                _required(self.replacement_text, "replacement_text"),
            )


@dataclass(frozen=True, slots=True)
class ProvenanceEvent:
    id: str
    chapter_id: str
    chapter_revision_before: int
    chapter_revision_after: int
    event_type: ProvenanceEventType
    source_audit_run_id: str | None
    source_finding_id: str | None
    source_repair_id: str | None
    summary: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("chapter_id", self.chapter_id),
            ("summary", self.summary),
        ):
            object.__setattr__(self, field, _required(value, field))
        _non_negative(self.chapter_revision_before, "chapter_revision_before")
        _non_negative(self.chapter_revision_after, "chapter_revision_after")
        object.__setattr__(self, "source_audit_run_id", _optional_text(self.source_audit_run_id))
        object.__setattr__(self, "source_finding_id", _optional_text(self.source_finding_id))
        object.__setattr__(self, "source_repair_id", _optional_text(self.source_repair_id))
