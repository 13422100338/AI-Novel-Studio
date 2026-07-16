from __future__ import annotations

import hashlib
import re
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
    ContractValidationError,
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
    )
)

_SUMMARY_SECTIONS = (
    "剧情概况",
    "关键情节点",
    "人物成长",
    "连续性要点",
    "细节摘录",
)
_SUMMARY_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_DETAIL_PREFIX = re.compile(r"^(?:[-*+]\s*|\d+[.)、]\s*)")

_SYSTEM_PROMPT = """你是长篇小说记忆提取器。只分析用户给出的当前章正文。
只返回一个 JSON 对象，不要输出思考过程、Markdown 代码围栏或解释文字。

顶层必须包含以下字段：
- summary: 字符串。使用以下固定 Markdown 小节组织有效信息：
  ## 剧情概况
  ## 关键情节点
  ## 人物成长
  ## 连续性要点
  ## 细节摘录
- character_states: 数组。每项字段为 character_name、motivation、psychology、
  current_goal、relationships、recent_activity。
- canon: 数组。每项字段为 title、detail。
- clues: 数组。每项字段为 clue_type、title、detail、action。
  clue_type 只能是 FORESHADOW、MISDIRECTION、OPEN_QUESTION、AUTHOR_PROMISE、
  ATMOSPHERIC_HINT；action 只能是 PLANT、REINFORCE、REDIRECT、REVEAL、
  RESOLVE、ABANDON。
- knowledge: 数组。只提取读者在本章新增知道、怀疑或误解的内容，每项字段为
  subject_type、subject_id、title、detail、state。subject_type 必须填 READER，
  subject_id 必须填 READER；state 只能是 SUSPECTED、MISUNDERSTOOD 或 KNOWN。
  人物掌握的信息直接写入对应人物状态，不要生成人物知识项。

摘要不是缩写正文。剧情概况应把本章因果和结果说明白，最多 1000 个字符；其余小节
按本章信息密度决定条目数量，不要为了凑长度重复正文。细节摘录只选择正文中有戏剧性、
辨识度或能维持行文质感的原句，每条使用“- 原文：<逐字摘录>”，不得改写或虚构；没有
合适内容时写“- 无”。伏笔、作者承诺、悬念和未决问题只写入 clues 数组，不得在 summary
中重复。summary 只保留已经发生的事件因果、人物变化、世界规则和连续性事实。
没有内容的数组返回 []。不确定的信息不要猜测。
所有结果只是待人工审查候选，不能覆盖已有正典。"""

_SYSTEM_PROMPT += (
    "\n字段类型示例（内容仅用于说明格式）：\n"
    '{"summary":"## 剧情概况\\n本章概况\\n## 关键情节点\\n- 事件'
    '\\n## 人物成长\\n- 变化\\n## 连续性要点\\n- 事实'
    '\\n## 细节摘录\\n- 原文：正文原句","character_states":['
    '{"character_name":"甲","motivation":"查明真相","psychology":"警惕",'
    '"current_goal":"核对线索","relationships":"暂不信任乙",'
    '"recent_activity":"收到来信"}],"canon":[],"clues":[],'
    '"knowledge":[]}\n'
)


class MemoryAnalysisService:
    def __init__(
        self,
        runner: LLMContractRunner,
        *,
        output_token_limit: int | None = None,
    ) -> None:
        if output_token_limit is not None and not 1 <= output_token_limit <= 200_000:
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
            self._output_limit_for(text),
            _CONTRACT,
            lambda candidate: _validate_candidate_payload(candidate, text),
        )
        knowledge = tuple(
            _knowledge(value, index)
            for index, value in enumerate(_required_list(payload, "knowledge"))
        )
        return MemoryCandidateBundle(
            source_chapter_id=chapter_id,
            source_revision=revision,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            summary=SummaryCandidate(_validated_summary(payload, text)),
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
                candidate
                for candidate in knowledge
                if candidate.subject_type == KnowledgeSubject.READER
            ),
            # 文风自动候选已退役；人工样章仍由独立的文风工作区维护。
            style=(),
        )

    def _output_limit_for(self, text: str) -> int:
        if self._output_token_limit is not None:
            return self._output_token_limit
        # 这是防止异常长输出的安全上限，不是摘要目标长度。模型仍按当前章的
        # 信息密度决定实际输出量，但记忆提取不会继承正文创作的超大额度。
        # 结构化记忆同时包含摘要、人物、正典、线索、知识与文风数组；过低
        # 会在 JSON 字符串中途截断。上限随章节长度增长，模型仍可提前结束。
        return min(6_000, max(2_400, 2_200 + len(text) // 5))


def _required_list(payload: dict[str, object], field: str) -> list[object]:
    value = payload[field]
    if not isinstance(value, list):
        raise MemoryCandidateValidationError(f"字段 {field} 必须是数组")
    return cast(list[object], value)


def _validate_candidate_payload(
    payload: dict[str, object], source_text: str
) -> dict[str, object]:
    """Run every memory-specific safety check inside the correction loop."""
    try:
        _validated_summary(payload, source_text)
        for index, value in enumerate(_required_list(payload, "character_states")):
            _character_state(value, index)
        for index, value in enumerate(_required_list(payload, "canon")):
            _canon(value, index)
        for index, value in enumerate(_required_list(payload, "clues")):
            _clue(value, index)
        for index, value in enumerate(_required_list(payload, "knowledge")):
            _knowledge(value, index)
    except MemoryCandidateValidationError as error:
        raise ContractValidationError(str(error)) from error
    return payload


def _validated_summary(payload: dict[str, object], source_text: str) -> str:
    summary = _required_string(payload, "summary")
    matches = tuple(_SUMMARY_HEADING.finditer(summary))
    headings = tuple(match.group(1).strip() for match in matches)

    if "伏笔与未决问题" in headings:
        raise MemoryCandidateValidationError(
            "字段 summary 不得包含伏笔与未决问题；请改写入 clues 数组"
        )
    if headings != _SUMMARY_SECTIONS:
        missing = [section for section in _SUMMARY_SECTIONS if section not in headings]
        if missing:
            raise MemoryCandidateValidationError(
                f"字段 summary 缺少固定小节：{'、'.join(missing)}"
            )
        raise MemoryCandidateValidationError(
            "字段 summary 的小节必须按固定顺序排列，且不能增加其他小节"
        )

    sections = {
        heading: (
            summary[match.end() : matches[index + 1].start()].strip()
            if index + 1 < len(matches)
            else summary[match.end() :].strip()
        )
        for index, (heading, match) in enumerate(zip(headings, matches, strict=True))
    }
    if len(sections["剧情概况"]) > 1_000:
        raise MemoryCandidateValidationError("字段 summary.剧情概况 不能超过 1000 个字符")

    normalized_source = _compact_text(source_text)
    for line in sections["细节摘录"].splitlines():
        excerpt = _DETAIL_PREFIX.sub("", line.strip()).strip()
        if excerpt.startswith("原文："):
            excerpt = excerpt.removeprefix("原文：").strip()
        excerpt = excerpt.strip("“”‘’\"'")
        if not excerpt or excerpt == "无":
            continue
        if _compact_text(excerpt) not in normalized_source:
            raise MemoryCandidateValidationError(
                "字段 summary.细节摘录 必须逐字来自当前章原文"
            )
    return summary


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _required_string(payload: dict[str, object], field: str, *, path: str = "") -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        location = f"{path}.{field}" if path else field
        raise MemoryCandidateValidationError(f"字段 {location} 必须是非空字符串")
    return value.strip()


def _string(payload: dict[str, object], field: str, *, path: str) -> str:
    value = payload.get(field)
    try:
        return _text_value(value)
    except MemoryCandidateValidationError as error:
        raise MemoryCandidateValidationError(
            f"字段 {path}.{field} 必须是文本、文本数组或文本对象"
        ) from error


def _text_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "；".join(part for item in value if (part := _text_value(item)))
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            detail = _text_value(item)
            if detail:
                parts.append(f"{key}：{detail}")
        return "；".join(parts)
    raise MemoryCandidateValidationError("不支持的文本值类型")


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
        _string(item, "motivation", path=path),
        _string(item, "psychology", path=path),
        _string(item, "current_goal", path=path),
        _string(item, "relationships", path=path),
        _string(item, "recent_activity", path=path),
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
