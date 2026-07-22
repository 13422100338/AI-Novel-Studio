from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CreationMode(StrEnum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class GenerationProfile(StrEnum):
    QUICK = "QUICK"
    NORMAL = "NORMAL"


class AuditPolicy(StrEnum):
    MINIMAL = "MINIMAL"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


def resolve_generation_settings(
    mode: CreationMode,
    audit_policy: AuditPolicy | None,
) -> tuple[GenerationProfile, AuditPolicy]:
    profile = (
        GenerationProfile.QUICK
        if mode == CreationMode.BASIC
        else GenerationProfile.NORMAL
    )
    if audit_policy is not None:
        return profile, audit_policy
    return (
        profile,
        AuditPolicy.STANDARD if mode == CreationMode.STRICT else AuditPolicy.MINIMAL,
    )


def requires_forced_pre_accept_audit(
    mode: CreationMode,
    audit_policy: AuditPolicy,
) -> bool:
    return mode == CreationMode.STRICT or audit_policy == AuditPolicy.DEEP


class BriefStatus(StrEnum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    STALE = "STALE"
    ARCHIVED = "ARCHIVED"


class GenerationStatus(StrEnum):
    PREPARING = "PREPARING"
    READY = "READY"
    STREAMING = "STREAMING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ACCEPTED = "ACCEPTED"
    DISCARDED = "DISCARDED"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _non_negative(value: int | None, field: str) -> int | None:
    if value is not None and value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def _text_tuple(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{field} cannot contain empty text")
    return normalized


@dataclass(frozen=True, slots=True)
class ChapterRequirement:
    id: str
    chapter_id: str
    content: str
    is_locked: bool
    revision: int
    content_hash: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "id"))
        object.__setattr__(self, "chapter_id", _required(self.chapter_id, "chapter_id"))
        object.__setattr__(self, "content_hash", _required(self.content_hash, "content_hash"))
        _non_negative(self.revision, "revision")


@dataclass(frozen=True, slots=True)
class BriefSource:
    id: str
    brief_id: str
    source_type: str
    source_id: str
    source_revision: int
    source_hash: str
    required: bool

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("brief_id", self.brief_id),
            ("source_type", self.source_type),
            ("source_id", self.source_id),
            ("source_hash", self.source_hash),
        ):
            object.__setattr__(self, field, _required(value, field))
        _non_negative(self.source_revision, "source_revision")


@dataclass(frozen=True, slots=True)
class ChapterBrief:
    id: str
    chapter_id: str
    mode: CreationMode
    status: BriefStatus
    revision: int
    dramatic_purpose: str
    target_length: int
    story_date: str
    pov_character_id: str | None
    hard_events: tuple[str, ...]
    soft_goals: tuple[str, ...]
    prohibited_changes: tuple[str, ...]
    creative_freedom: tuple[str, ...]
    participants: tuple[str, ...]
    knowledge: tuple[str, ...]
    clue_actions: tuple[str, ...]
    style_rules: tuple[str, ...]
    warnings: tuple[str, ...]
    source_fingerprint: str
    content_hash: str
    cloned_from_id: str | None
    created_at: datetime
    updated_at: datetime
    frozen_at: datetime | None

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("chapter_id", self.chapter_id),
            ("dramatic_purpose", self.dramatic_purpose),
            ("source_fingerprint", self.source_fingerprint),
            ("content_hash", self.content_hash),
        ):
            object.__setattr__(self, field, _required(value, field))
        _non_negative(self.revision, "revision")
        if self.target_length <= 0:
            raise ValueError("target_length must be greater than zero")
        for field in (
            "hard_events",
            "soft_goals",
            "prohibited_changes",
            "creative_freedom",
            "participants",
            "knowledge",
            "clue_actions",
            "style_rules",
            "warnings",
        ):
            object.__setattr__(self, field, _text_tuple(getattr(self, field), field))
        if self.status == BriefStatus.FROZEN and self.frozen_at is None:
            raise ValueError("frozen Brief requires frozen_at")


@dataclass(frozen=True, slots=True)
class GenerationRun:
    id: str
    chapter_id: str
    mode: CreationMode
    status: GenerationStatus
    brief_id: str | None
    brief_revision: int | None
    context_manifest_id: str | None
    model_provider_id: str
    model_id: str
    output_token_limit: int
    prompt_version: str
    accepted_chapter_revision: int | None
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    failure_code: str | None
    failure_message: str | None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    accepted_at: datetime | None
    audit_policy: AuditPolicy = AuditPolicy.MINIMAL

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("chapter_id", self.chapter_id),
            ("model_provider_id", self.model_provider_id),
            ("model_id", self.model_id),
            ("prompt_version", self.prompt_version),
        ):
            object.__setattr__(self, field, _required(value, field))
        if self.output_token_limit <= 0:
            raise ValueError("output Token limit must be greater than zero")
        for field in (
            "brief_revision",
            "accepted_chapter_revision",
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
        ):
            _non_negative(getattr(self, field), f"{field} Token" if "tokens" in field else field)

    @property
    def generation_profile(self) -> GenerationProfile:
        return resolve_generation_settings(self.mode, self.audit_policy)[0]


@dataclass(frozen=True, slots=True)
class GenerationCheckpoint:
    id: str
    run_id: str
    sequence: int
    text_path: str
    content_hash: str
    finish_reason: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("run_id", self.run_id),
            ("text_path", self.text_path),
            ("content_hash", self.content_hash),
        ):
            object.__setattr__(self, field, _required(value, field))
        _non_negative(self.sequence, "sequence")
