from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import Authority, MemoryStatus, ReviewStatus, StyleScope
from ai_novel_studio.infrastructure.llm.contract_runner import (
    JsonField,
    JsonObjectContract,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.llm.schemas import LLMMessage, TaskPurpose
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository

_CONTRACT = JsonObjectContract(
    (
        JsonField("summary", str),
        JsonField("characters", list),
        JsonField("canon", list),
        JsonField("clues", list),
        JsonField("style", list),
        JsonField("uncertain", list),
    )
)

_SYSTEM_PROMPT = """你是小说设定资料整理器。输入不是小说正文，可能包含世界观、人物小传、
剧情计划、备选方案和文风要求。
只返回 JSON，不要返回 Markdown 代码围栏或解释。不得补写输入中不存在的事实。
顶层字段固定为：
- summary: 对资料用途和核心内容的简洁概览。
- characters: 数组；每项包含 name、aliases、profile。
- canon: 数组；每项包含 title、detail。只放明确成立的世界规则或背景事实。
- clues: 数组；每项包含 title、detail。放作者计划中的伏笔、承诺和未决线索。
- style: 数组；每项包含 rule_type、rule_text。只放明确的写作或叙事风格要求。
- uncertain: 数组；每项是字符串。放备选方案、互相冲突、已废弃或无法确认的信息。
严格区分“已经确定”“未来计划”“备选或不确定”。不要把人物设定伪造成某一章节已经发生的状态。"""


@dataclass(frozen=True, slots=True)
class SettingAnalysis:
    summary: str
    characters: tuple[tuple[str, str, str], ...]
    canon: tuple[tuple[str, str], ...]
    clues: tuple[tuple[str, str], ...]
    style: tuple[tuple[str, str], ...]
    uncertain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SettingImportReport:
    source_id: str
    created_canon: int
    created_style: int
    uncertain_count: int


class SettingDocumentAnalysisService:
    def __init__(self, runner: LLMContractRunner) -> None:
        self._runner = runner

    def analyze(self, title: str, document_type: str, text: str) -> SettingAnalysis:
        if not title.strip() or not text.strip():
            raise ValueError("设定资料标题和正文不能为空")
        payload = self._runner.run_json(
            TaskPurpose.MEMORY_EXTRACTION,
            (
                LLMMessage("system", _SYSTEM_PROMPT),
                LLMMessage(
                    "user",
                    f"资料标题：{title.strip()}\n资料类型：{document_type.strip()}\n\n"
                    f"<setting_document>\n{text}\n</setting_document>",
                ),
            ),
            min(6_000, max(2_400, 2_200 + len(text) // 5)),
            _CONTRACT,
        )
        return SettingAnalysis(
            summary=_required_text(payload, "summary"),
            characters=tuple(
                (
                    _required_text(item, "name", path=f"characters[{index}]"),
                    _optional_text(item, "aliases", path=f"characters[{index}]"),
                    _required_text(item, "profile", path=f"characters[{index}]"),
                )
                for index, item in enumerate(_objects(payload, "characters"))
            ),
            canon=tuple(
                _pair(item, index, "canon")
                for index, item in enumerate(_objects(payload, "canon"))
            ),
            clues=tuple(
                _pair(item, index, "clues")
                for index, item in enumerate(_objects(payload, "clues"))
            ),
            style=tuple(
                (
                    _required_text(item, "rule_type", path=f"style[{index}]"),
                    _required_text(item, "rule_text", path=f"style[{index}]"),
                )
                for index, item in enumerate(_objects(payload, "style"))
            ),
            uncertain=tuple(_string_items(payload, "uncertain")),
        )


class SettingDocumentMemoryService:
    """Stores user source verbatim and model output only as review candidates."""

    def __init__(self, analyzer: SettingDocumentAnalysisService | None) -> None:
        self._analyzer = analyzer

    def save_source(
        self,
        project: ProjectRepository,
        title: str,
        document_type: str,
        text: str,
        *,
        source_id: str | None = None,
    ) -> str:
        title, text = title.strip(), text.strip()
        if not title or not text:
            raise ValueError("设定资料标题和正文不能为空")
        source_id = source_id or new_id()
        SearchRepository(project).index_document(
            document_type="SETTING_SOURCE",
            source_id=source_id,
            chapter_id=None,
            title=f"[{document_type.strip() or '混合设定'}] {title}",
            content=text,
            participants=(),
            pinned_weight=1.0,
            review_status=ReviewStatus.APPROVED,
            status=MemoryStatus.CURRENT,
            source_revision=0,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        return source_id

    def analyze_and_store(
        self,
        project: ProjectRepository,
        title: str,
        document_type: str,
        text: str,
        *,
        source_id: str | None = None,
    ) -> SettingImportReport:
        if self._analyzer is None:
            raise RuntimeError("尚未配置可用的记忆整理模型")
        source_id = self.save_source(project, title, document_type, text, source_id=source_id)
        analysis = self._analyzer.analyze(title, document_type, text)
        narrative = NarrativeMemoryRepository(project)
        styles = StyleRepository(project)
        marker = f"SETTING:{source_id}"
        canon_items: list[tuple[str, str]] = [(f"设定概览：{title}", analysis.summary)]
        canon_items.extend(
            (
                f"人物基础设定：{name}",
                "\n".join(
                    part
                    for part in (f"别名：{aliases}" if aliases else "", profile)
                    if part
                ),
            )
            for name, aliases, profile in analysis.characters
        )
        canon_items.extend(analysis.canon)
        canon_items.extend(
            (f"伏笔计划：{item_title}", detail)
            for item_title, detail in analysis.clues
        )
        if analysis.uncertain:
            canon_items.append(
                ("待确认设定", "\n".join(f"- {item}" for item in analysis.uncertain))
            )
        with project.database.connect() as connection:
            existing_canon = {
                (row["title"], row["detail"])
                for row in connection.execute(
                    "SELECT title, detail FROM canon_entries "
                    "WHERE source_paragraph_id = ? AND authority = 'MODEL_EXTRACTED' "
                    "AND review_status = 'REVIEW' AND status = 'CURRENT'",
                    (marker,),
                ).fetchall()
            }
            existing_style = {
                (row["rule_type"], row["rule_text"])
                for row in connection.execute(
                    "SELECT rule_type, rule_text FROM style_rules "
                    "WHERE scope_type = 'BOOK' AND scope_id = 'BOOK' "
                    "AND authority = 'MODEL_EXTRACTED' AND review_status = 'REVIEW' "
                    "AND status = 'CURRENT'"
                ).fetchall()
            }
        created_canon = 0
        for item_title, detail in canon_items:
            if (item_title, detail) in existing_canon:
                continue
            narrative.add_canon(
                item_title,
                detail,
                None,
                source_paragraph_id=marker,
                confidence=0.75,
                authority=Authority.MODEL_EXTRACTED,
                review_status=ReviewStatus.REVIEW,
            )
            created_canon += 1
        created_style = 0
        for rule_type, rule_text in analysis.style:
            if (rule_type, rule_text) in existing_style:
                continue
            styles.add_rule(
                StyleScope.BOOK,
                "BOOK",
                rule_type,
                rule_text,
                Authority.MODEL_EXTRACTED,
                ReviewStatus.REVIEW,
            )
            created_style += 1
        return SettingImportReport(
            source_id, created_canon, created_style, len(analysis.uncertain)
        )


def _objects(payload: dict[str, object], field: str) -> tuple[dict[str, object], ...]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ValueError(f"字段 {field} 必须是数组")
    result: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"字段 {field}[{index}] 必须是对象")
        result.append(cast(dict[str, object], item))
    return tuple(result)


def _required_text(payload: dict[str, object], field: str, *, path: str = "") -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段 {path + '.' if path else ''}{field} 必须是非空文本")
    return value.strip()


def _optional_text(payload: dict[str, object], field: str, *, path: str) -> str:
    value = payload.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"字段 {path}.{field} 必须是文本")
    return value.strip()


def _pair(payload: dict[str, object], index: int, field: str) -> tuple[str, str]:
    path = f"{field}[{index}]"
    return _required_text(payload, "title", path=path), _required_text(payload, "detail", path=path)


def _string_items(payload: dict[str, object], field: str) -> tuple[str, ...]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"字段 {field} 必须是文本数组")
    return tuple(item.strip() for item in cast(list[str], value) if item.strip())
