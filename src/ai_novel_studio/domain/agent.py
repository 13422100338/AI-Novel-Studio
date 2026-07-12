from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AgentPurpose(StrEnum):
    PLOT_DISCUSSION = "PLOT_DISCUSSION"
    REVISION_PLAN = "REVISION_PLAN"
    AUDIT_EXPLANATION = "AUDIT_EXPLANATION"


class AgentRunStatus(StrEnum):
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    WAITING_FOR_MODEL = "WAITING_FOR_MODEL"
    WAITING_FOR_TOOL = "WAITING_FOR_TOOL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentTurnRole(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class AgentToolName(StrEnum):
    READ_CHAPTER_EXCERPT = "READ_CHAPTER_EXCERPT"
    SEARCH_MEMORY = "SEARCH_MEMORY"
    GET_CHARACTER_STATE = "GET_CHARACTER_STATE"
    GET_CHARACTER_KNOWLEDGE = "GET_CHARACTER_KNOWLEDGE"
    GET_ACTIVE_CLUES = "GET_ACTIVE_CLUES"
    GET_CANON_FACTS = "GET_CANON_FACTS"
    GET_STYLE_GUIDE = "GET_STYLE_GUIDE"
    GET_AUDIT_FINDINGS = "GET_AUDIT_FINDINGS"


class AgentToolCallStatus(StrEnum):
    REQUESTED = "REQUESTED"
    VALIDATED = "VALIDATED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    OMITTED = "OMITTED"


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


def _positive(value: int, field: str) -> int:
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class AgentRun:
    id: str
    chapter_id: str | None
    purpose: AgentPurpose
    status: AgentRunStatus
    model_provider_id: str
    model_id: str
    prompt_version: str
    max_iterations: int
    max_tool_calls: int
    max_tool_result_chars: int
    used_iterations: int
    used_tool_calls: int
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    failure_code: str | None
    failure_message: str | None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("model_provider_id", self.model_provider_id),
            ("model_id", self.model_id),
            ("prompt_version", self.prompt_version),
        ):
            object.__setattr__(self, field, _required(value, field))
        object.__setattr__(self, "chapter_id", _optional_text(self.chapter_id))
        object.__setattr__(self, "failure_code", _optional_text(self.failure_code))
        object.__setattr__(self, "failure_message", _optional_text(self.failure_message))
        _positive(self.max_iterations, "max_iterations")
        _positive(self.max_tool_result_chars, "max_tool_result_chars")
        for field in (
            "max_tool_calls",
            "used_iterations",
            "used_tool_calls",
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
        ):
            _non_negative(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class AgentTurn:
    id: str
    run_id: str
    sequence: int
    role: AgentTurnRole
    content: str
    content_hash: str
    omitted: bool
    created_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("run_id", self.run_id),
            ("content", self.content),
            ("content_hash", self.content_hash),
        ):
            object.__setattr__(self, field, _required(value, field))
        _non_negative(self.sequence, "sequence")


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    id: str
    run_id: str
    turn_id: str | None
    sequence: int
    tool_name: AgentToolName | str
    arguments_json: str
    status: AgentToolCallStatus
    result_json: str
    result_chars: int
    source_refs_json: str
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        for field, value in (
            ("id", self.id),
            ("run_id", self.run_id),
            ("arguments_json", self.arguments_json),
            ("result_json", self.result_json),
            ("source_refs_json", self.source_refs_json),
        ):
            object.__setattr__(self, field, _required(value, field))
        object.__setattr__(self, "turn_id", _optional_text(self.turn_id))
        object.__setattr__(self, "failure_code", _optional_text(self.failure_code))
        object.__setattr__(self, "failure_message", _optional_text(self.failure_message))
        _non_negative(self.sequence, "sequence")
        _non_negative(self.result_chars, "result_chars")


@dataclass(frozen=True, slots=True)
class AgentSourceRef:
    source_type: str
    source_id: str
    source_revision: int
    source_hash: str

    def __post_init__(self) -> None:
        for field, value in (
            ("source_type", self.source_type),
            ("source_id", self.source_id),
            ("source_hash", self.source_hash),
        ):
            object.__setattr__(self, field, _required(value, field))
        _non_negative(self.source_revision, "source_revision")


@dataclass(frozen=True, slots=True)
class AgentToolResult:
    tool_name: AgentToolName
    content: str
    source_refs: tuple[AgentSourceRef, ...]
    omitted: tuple[str, ...]
    result_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", _required(self.content, "content"))
        object.__setattr__(self, "result_hash", _required(self.result_hash, "result_hash"))
