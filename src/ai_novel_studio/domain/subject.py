from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SubjectType(StrEnum):
    CHARACTER = "CHARACTER"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field}不能为空")
    return normalized


@dataclass(frozen=True, slots=True)
class Subject:
    id: str
    type: SubjectType
    canonical_name: str
    active: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "主体 ID"))
        object.__setattr__(
            self, "canonical_name", _required(self.canonical_name, "主体标准名称")
        )


@dataclass(frozen=True, slots=True)
class SubjectAlias:
    id: str
    subject_id: str
    alias: str
    source_id: str
    confirmed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "主体别名 ID"))
        object.__setattr__(self, "subject_id", _required(self.subject_id, "主体 ID"))
        object.__setattr__(self, "alias", _required(self.alias, "主体别名"))
        object.__setattr__(self, "source_id", _required(self.source_id, "别名来源 ID"))
