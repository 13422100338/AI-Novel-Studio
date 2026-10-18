from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ApprovalKind(StrEnum):
    """Kinds of author approval the harness waits on (design approval module)."""

    CHANGESET = "CHANGESET"
    PROMPT_CHANGE = "PROMPT_CHANGE"
    PROJECT_CONSTITUTION = "PROJECT_CONSTITUTION"
    SUBJECT_MERGE = "SUBJECT_MERGE"
    SKILL_CHANGE = "SKILL_CHANGE"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _validate_payload(value: dict[str, object]) -> dict[str, object]:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be JSON-serializable") from exc
    return value


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Harness-owned author approval record (backend audit 2026-08-14).

    The lifecycle (PENDING -> APPROVED / REJECTED) is owned by the Harness;
    the backend only validates approval credentials and executes the
    deterministic commit when the resolved request is handed over.
    """

    request_id: str
    run_id: str
    kind: ApprovalKind
    summary: str
    payload: dict[str, object]
    expected_revisions: tuple[tuple[str, int], ...]
    idempotency_key: str
    status: ApprovalStatus
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _required(self.request_id, "request_id"))
        object.__setattr__(self, "run_id", _required(self.run_id, "run_id"))
        if not isinstance(self.kind, ApprovalKind):
            raise ValueError("kind must be an ApprovalKind")
        if not isinstance(self.status, ApprovalStatus):
            raise ValueError("status must be an ApprovalStatus")
        object.__setattr__(self, "summary", _required(self.summary, "summary"))
        object.__setattr__(self, "payload", _validate_payload(self.payload))
        normalized_revisions: list[tuple[str, int]] = []
        for key, revision in self.expected_revisions:
            key = _required(key, "revision key")
            if revision < 0:
                raise ValueError("revision cannot be negative")
            normalized_revisions.append((key, revision))
        object.__setattr__(self, "expected_revisions", tuple(normalized_revisions))
        object.__setattr__(
            self, "idempotency_key", _required(self.idempotency_key, "idempotency_key")
        )
        object.__setattr__(
            self, "resolution_note", _optional_text(self.resolution_note)
        )
