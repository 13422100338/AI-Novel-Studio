from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    StyleScope,
)
from ai_novel_studio.infrastructure.llm.contract_runner import (
    JsonField,
    JsonObjectContract,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.llm.schemas import LLMMessage, TaskPurpose


class MemoryCandidateValidationError(ValueError):
    """Raised when nested model output cannot be safely represented as candidates."""


@dataclass(frozen=True, slots=True)
class SummaryCandidate:
    content: str


@dataclass(frozen=True, slots=True)
class CharacterStateCandidate:
    character_name: str
    motivation: str
    psychology: str
    current_goal: str
    relationships: str
    recent_activity: str


@dataclass(frozen=True, slots=True)
class CanonCandidate:
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class ClueCandidate:
    clue_type: ClueType
    title: str
    detail: str
    action: ClueAction


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    subject_type: KnowledgeSubject
    subject_id: str
    title: str
    detail: str
    state: KnowledgeState


@dataclass(frozen=True, slots=True)
class StyleCandidate:
    scope_type: StyleScope
    scope_id: str
    rule_type: str
    rule_text: str


@dataclass(frozen=True, slots=True)
class MemoryCandidateBundle:
    source_chapter_id: str
    source_revision: int
    source_hash: str
    summary: SummaryCandidate
    character_states: tuple[CharacterStateCandidate, ...]
    canon: tuple[CanonCandidate, ...]
    clues: tuple[ClueCandidate, ...]
    knowledge: tuple[KnowledgeCandidate, ...]
    style: tuple[StyleCandidate, ...]
    authority: Authority = Authority.MODEL_EXTRACTED
    review_status: ReviewStatus = ReviewStatus.REVIEW


_CONTRACT = JsonObjectContract(
    (
        JsonField("summary", str),
        JsonField("character_states", list),
        JsonField("canon", list),
        JsonField("clues", list),
        JsonField("knowledge", list),
        JsonField("style", list),
    )
)

_SYSTEM_PROMPT = """你是长篇小说记忆提取器。只分析用户给出的当前章正文。
返回一个 JSON 对象，必须包含 summary、character_states、canon、clues、knowledge、style。
所有数组项都必须使用明确字段；不确定的信息不要猜测，也不要标记为已确认。
你的输出只是待人工审查的候选记录，不能覆盖已有正典。"""


class MemoryAnalysisService:
    def __init__(self, runner: LLMContractRunner, *, output_token_limit: int = 4_000) -> None:
        if not 1 <= output_token_limit <= 200_000:
            raise ValueError("记忆提取输出 Token 上限必须在 1 到 200000 之间")
        self._runner = runner
        self._output_token_limit = output_token_limit

    def extract_candidates(
        self, chapter_id: str, revision: int, text: str
    ) -> MemoryCandidateBundle:
        chapter_id = chapter_id.strip()
        if not chapter_id:
            raise ValueError("章节 ID 不能为空")
        if revision < 0:
            raise ValueError("章节修订号不能为负数")
        if not text.strip():
            raise ValueError("章节正文不能为空")
        messages = (
            LLMMessage("system", _SYSTEM_PROMPT),
            LLMMessage(
                "user",
                f"source_chapter_id={chapter_id}\nrevision={revision}\n\n<chapter_text>\n"
                f"{text}\n</chapter_text>",
            ),
        )
        payload = self._runner.run_json(
            TaskPurpose.MEMORY_EXTRACTION,
            messages,
            self._output_token_limit,
            _CONTRACT,
        )
        return MemoryCandidateBundle(
            source_chapter_id=chapter_id,
            source_revision=revision,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            summary=SummaryCandidate(_required_string(payload, "summary")),
            character_states=tuple(
                _character_state(value, index)
                for index, value in enumerate(_required_list(payload, "character_states"))
            ),
            canon=tuple(
                _canon(value, index)
                for index, value in enumerate(_required_list(payload, "canon"))
            ),
            clues=tuple(
                _clue(value, index)
                for index, value in enumerate(_required_list(payload, "clues"))
            ),
            knowledge=tuple(
                _knowledge(value, index)
                for index, value in enumerate(_required_list(payload, "knowledge"))
            ),
            style=tuple(
                _style(value, index)
                for index, value in enumerate(_required_list(payload, "style"))
            ),
        )


def _required_list(payload: dict[str, object], field: str) -> list[object]:
    value = payload[field]
    if not isinstance(value, list):
        raise MemoryCandidateValidationError(f"字段 {field} 必须是数组")
    return cast(list[object], value)


def _required_string(payload: dict[str, object], field: str, *, path: str = "") -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        location = f"{path}.{field}" if path else field
        raise MemoryCandidateValidationError(f"字段 {location} 必须是非空字符串")
    return value.strip()


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MemoryCandidateValidationError(f"字段 {path} 必须是 JSON 对象")
    return cast(dict[str, object], value)


def _enum_value(
    payload: dict[str, object], field: str, enum_type: type[StrEnum], *, path: str
) -> StrEnum:
    value = _required_string(payload, field, path=path)
    try:
        return enum_type(value)
    except ValueError as error:
        raise MemoryCandidateValidationError(
            f"字段 {path}.{field} 的值不受支持：{value}"
        ) from error


def _character_state(value: object, index: int) -> CharacterStateCandidate:
    path = f"character_states[{index}]"
    item = _object(value, path)
    return CharacterStateCandidate(
        _required_string(item, "character_name", path=path),
        _required_string(item, "motivation", path=path),
        _required_string(item, "psychology", path=path),
        _required_string(item, "current_goal", path=path),
        _required_string(item, "relationships", path=path),
        _required_string(item, "recent_activity", path=path),
    )


def _canon(value: object, index: int) -> CanonCandidate:
    path = f"canon[{index}]"
    item = _object(value, path)
    return CanonCandidate(
        _required_string(item, "title", path=path),
        _required_string(item, "detail", path=path),
    )


def _clue(value: object, index: int) -> ClueCandidate:
    path = f"clues[{index}]"
    item = _object(value, path)
    return ClueCandidate(
        cast(ClueType, _enum_value(item, "clue_type", ClueType, path=path)),
        _required_string(item, "title", path=path),
        _required_string(item, "detail", path=path),
        cast(ClueAction, _enum_value(item, "action", ClueAction, path=path)),
    )


def _knowledge(value: object, index: int) -> KnowledgeCandidate:
    path = f"knowledge[{index}]"
    item = _object(value, path)
    return KnowledgeCandidate(
        cast(
            KnowledgeSubject,
            _enum_value(item, "subject_type", KnowledgeSubject, path=path),
        ),
        _required_string(item, "subject_id", path=path),
        _required_string(item, "title", path=path),
        _required_string(item, "detail", path=path),
        cast(KnowledgeState, _enum_value(item, "state", KnowledgeState, path=path)),
    )


def _style(value: object, index: int) -> StyleCandidate:
    path = f"style[{index}]"
    item = _object(value, path)
    return StyleCandidate(
        cast(StyleScope, _enum_value(item, "scope_type", StyleScope, path=path)),
        _required_string(item, "scope_id", path=path),
        _required_string(item, "rule_type", path=path),
        _required_string(item, "rule_text", path=path),
    )
