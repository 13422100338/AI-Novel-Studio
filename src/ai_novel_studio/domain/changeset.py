from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.domain.identifiers import validate_id

_MAX_OPERATIONS = 50


class ChangeOperationKind(StrEnum):
    CHAPTER_CONTENT_REPLACE = "CHAPTER_CONTENT_REPLACE"
    CHAPTER_TITLE_CHANGE = "CHAPTER_TITLE_CHANGE"
    REPAIR_APPLY = "REPAIR_APPLY"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"change operation {field} cannot be empty")
    return normalized


def _validate_payload(value: dict[str, object], field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"change operation {field} is invalid")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"change operation {field} must be JSON-serializable") from exc
    return value


@dataclass(frozen=True, slots=True)
class ChangeOperation:
    """One typed write operation inside a ChangeSet (DCP step 5.3, option A)."""

    operation_id: str
    kind: ChangeOperationKind
    chapter_id: str
    expected_revision: int
    payload: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", validate_id(self.operation_id))
        object.__setattr__(self, "chapter_id", validate_id(self.chapter_id))
        if not isinstance(self.kind, ChangeOperationKind):
            raise ValueError("change operation kind is invalid")
        if self.expected_revision < 0:
            raise ValueError("change operation expected_revision is invalid")
        payload = _validate_payload(self.payload, "payload")
        if self.kind is ChangeOperationKind.CHAPTER_CONTENT_REPLACE:
            for field in ("content", "source", "reason"):
                payload[field] = _required(str(payload.get(field, "")), field)
            if not isinstance(payload.get("invalidate_memory", True), bool):
                raise ValueError("change operation invalidate_memory is invalid")
        elif self.kind is ChangeOperationKind.CHAPTER_TITLE_CHANGE:
            payload["title"] = _required(str(payload.get("title", "")), "title")
        else:
            try:
                payload["proposal_id"] = validate_id(
                    str(payload.get("proposal_id", ""))
                )
            except ValueError:
                raise ValueError(
                    "change operation repair proposal id is invalid"
                ) from None
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class ChangeSet:
    change_set_id: str
    operations: tuple[ChangeOperation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_set_id", validate_id(self.change_set_id))
        if not isinstance(self.operations, tuple) or not self.operations:
            raise ValueError("change set operations cannot be empty")
        if len(self.operations) > _MAX_OPERATIONS:
            raise ValueError("change set has too many operations")
        if any(not isinstance(op, ChangeOperation) for op in self.operations):
            raise ValueError("change set operations are invalid")
        identifiers = [op.operation_id for op in self.operations]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("change set operation ids must be unique")
