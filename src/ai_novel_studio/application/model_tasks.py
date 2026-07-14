from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

from ai_novel_studio.infrastructure.llm.contract_runner import (
    ContractValidationError,
    JsonField,
    JsonObjectContract,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.llm.gateway import LLMGateway
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMStreamEvent,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.llm.usage_tracker import UsageSnapshot

_DIRECTOR_SYSTEM = """你是长篇小说的剧情导演。你的职责是与作者讨论人物动机、因果、伏笔和章节结构。
不得假装读取未提供的资料，不得擅自修改正文、正典、记忆库或章节要求。区分建议与已确认事实。"""


@dataclass(frozen=True, slots=True)
class NormalizedBrief:
    dramatic_function: str
    hard_events: tuple[str, ...]
    soft_goals: tuple[str, ...]
    forbidden_changes: tuple[str, ...]
    creative_freedom: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StyleAuditFinding:
    category: str
    issue: str
    evidence: str
    severity: str


@dataclass(frozen=True, slots=True)
class StyleAuditResult:
    summary: str
    findings: tuple[StyleAuditFinding, ...]


@dataclass(frozen=True, slots=True)
class ChatSummaryResult:
    summary: str


class ModelTaskService:
    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway
        self.contracts = LLMContractRunner(gateway)

    def usage_snapshot(self) -> UsageSnapshot:
        return self.gateway.usage_tracker.snapshot()

    def summarize_chat(
        self,
        existing_summary: str,
        transcript: str,
        output_token_limit: int,
    ) -> ChatSummaryResult:
        contract = JsonObjectContract((JsonField("summary", str),))
        messages = (
            LLMMessage(
                "system",
                "你负责维护长篇小说项目的剧情商讨摘要。输出 JSON。保留已经确认的决定、"
                "人物动机、因果关系、伏笔、被否决方案及未解决问题；不得把建议写成既定事实。",
            ),
            LLMMessage(
                "user",
                f"已有摘要：\n{existing_summary or '（无）'}\n\n"
                f"需要合并的较早对话：\n{transcript}\n\n"
                '返回格式：{"summary":"更新后的完整长期摘要"}',
            ),
        )
        data = self.contracts.run_json(
            TaskPurpose.PLOT_DISCUSSION,
            messages,
            output_token_limit,
            contract,
        )
        return ChatSummaryResult(self._text(data, "summary"))

    def stream_chat(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript_excerpt: str,
        output_token_limit: int,
    ) -> Iterator[LLMStreamEvent]:
        if not conversation:
            raise ValueError("剧情商讨至少需要一条消息")
        context = LLMMessage(
            "system",
            "下面是作者当前正在编辑的正文，仅作讨论依据，不得声称它已经成为正典：\n"
            f"{manuscript_excerpt or '（当前正文为空）'}",
        )
        messages = (
            LLMMessage("system", _DIRECTOR_SYSTEM),
            *conversation[:-1],
            context,
            conversation[-1],
        )
        yield from self.gateway.stream(
            TaskPurpose.PLOT_DISCUSSION,
            messages,
            output_token_limit,
            temperature=0.8,
        )

    def draft_chapter_requirement(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript_excerpt: str,
        output_token_limit: int,
    ) -> str:
        transcript = "\n".join(f"{message.role}: {message.content}" for message in conversation)
        messages = (
            LLMMessage("system", _DIRECTOR_SYSTEM),
            LLMMessage(
                "user",
                "根据以下剧情商讨和当前正文，输出一份正式当前章要求。"
                "它是给作者审查的章节级指令，应明确必须发生、禁止改变、人物心理和可自由发挥范围。"
                "不要写正文，不要加寒暄。\n\n"
                f"剧情商讨：\n{transcript or '（无）'}\n\n"
                f"当前正文：\n{manuscript_excerpt or '（空）'}",
            ),
        )
        response = self.gateway.complete(
            TaskPurpose.CHAPTER_REQUIREMENT,
            messages,
            output_token_limit,
            temperature=0.3,
        )
        result = response.text.strip()
        if not result:
            raise ContractValidationError("当前章要求不能为空")
        return result

    def normalize_brief(self, source: str, output_token_limit: int) -> NormalizedBrief:
        contract = JsonObjectContract(
            (
                JsonField("dramatic_function", (str, list)),
                JsonField("hard_events", (list, str)),
                JsonField("soft_goals", (list, str)),
                JsonField("forbidden_changes", (list, str)),
                JsonField("creative_freedom", (list, str)),
            )
        )
        messages = (
            LLMMessage(
                "system",
                "你只负责把作者提供的章节 Brief 整理为 JSON。不得增加来源中没有的事实，"
                "不得修改正文或长期记忆。dramatic_function 必须是文本；"
                "hard_events、soft_goals、forbidden_changes、creative_freedom "
                "必须是文本数组，不得返回嵌套对象。",
            ),
            LLMMessage(
                "user",
                "按合同整理下列 Brief。所有列表项必须是文本：\n" + source,
            ),
        )
        data = self.contracts.run_json(
            TaskPurpose.BRIEF_NORMALIZATION,
            messages,
            output_token_limit,
            contract,
        )
        return NormalizedBrief(
            dramatic_function=self._brief_text(data, "dramatic_function"),
            hard_events=self._brief_text_tuple(data, "hard_events"),
            soft_goals=self._brief_text_tuple(data, "soft_goals"),
            forbidden_changes=self._brief_text_tuple(data, "forbidden_changes"),
            creative_freedom=self._brief_text_tuple(data, "creative_freedom"),
        )

    def audit_style(
        self,
        manuscript: str,
        rules: tuple[str, ...],
        output_token_limit: int,
    ) -> StyleAuditResult:
        contract = JsonObjectContract(
            (JsonField("summary", str), JsonField("findings", list))
        )
        messages = (
            LLMMessage(
                "system",
                "你是独立文风审校员。只报告问题和原文证据，不改写正文，不改变剧情事实。"
                "findings 中每项必须包含 category、issue、evidence、severity 文本字段。",
            ),
            LLMMessage(
                "user",
                "审校规则：\n- "
                + "\n- ".join(rules or ("保持人物声音和叙述视角一致",))
                + "\n\n待审正文：\n"
                + manuscript,
            ),
        )
        data = self.contracts.run_json(
            TaskPurpose.STYLE_AUDIT,
            messages,
            output_token_limit,
            contract,
        )
        findings_value = data["findings"]
        if not isinstance(findings_value, list):
            raise ContractValidationError("字段 findings 必须是 list")
        findings: list[StyleAuditFinding] = []
        for item in findings_value:
            if not isinstance(item, dict):
                raise ContractValidationError("findings 中的项目必须是对象")
            finding = cast(dict[str, object], item)
            findings.append(
                StyleAuditFinding(
                    category=self._text(finding, "category"),
                    issue=self._text(finding, "issue"),
                    evidence=self._text(finding, "evidence"),
                    severity=self._text(finding, "severity"),
                )
            )
        return StyleAuditResult(
            summary=self._text(data, "summary"),
            findings=tuple(findings),
        )

    @staticmethod
    def _text(data: dict[str, object], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"字段 {key} 必须是非空文本")
        return value.strip()

    @staticmethod
    def _text_tuple(data: dict[str, object], key: str) -> tuple[str, ...]:
        value = data.get(key)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ContractValidationError(f"字段 {key} 必须是文本数组")
        return tuple(cast(str, item).strip() for item in value)

    @staticmethod
    def _brief_text(data: dict[str, object], key: str) -> str:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value and all(
            isinstance(item, str) and item.strip() for item in value
        ):
            return "；".join(cast(str, item).strip() for item in value)
        raise ContractValidationError(f"字段 {key} 必须是非空文本或文本数组")

    @staticmethod
    def _brief_text_tuple(data: dict[str, object], key: str) -> tuple[str, ...]:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return (value.strip(),)
        if isinstance(value, list) and all(
            isinstance(item, str) and item.strip() for item in value
        ):
            return tuple(cast(str, item).strip() for item in value)
        raise ContractValidationError(f"字段 {key} 必须是文本或文本数组")
