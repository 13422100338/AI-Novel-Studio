from __future__ import annotations

from ai_novel_studio.core.context.context_builder import ContextBlock
from ai_novel_studio.domain.generation import ChapterBrief, ChapterRequirement
from ai_novel_studio.infrastructure.llm import LLMMessage

PROSE_PROMPT_VERSION = "prose-v1"

_WRITER_SYSTEM = (
    "你是长篇小说正文写手。严格遵守正典、当前章要求和知识边界；"
    "不得输出分析、解释或规划，不得调用工具。"
)
_FORMAT_SYSTEM = (
    "输出连续的小说正文，不添加标题之外的说明。若内容因上限中断，"
    "直接停在已完成文本处，不要总结或声明未完成。"
)


def build_prose_messages(
    requirement: ChapterRequirement,
    brief: ChapterBrief | None,
    selected_blocks: tuple[ContextBlock, ...],
) -> tuple[LLMMessage, ...]:
    by_category: dict[str, list[str]] = {}
    for block in selected_blocks:
        by_category.setdefault(block.category, []).append(block.content)

    brief_text = _brief_text(brief) if brief is not None else "基础模式：仅遵守当前章要求。"
    target = _joined(by_category, "TARGET")
    project_guidance = tuple(
        LLMMessage("system", "小说最高系统提示（人工维护）：\n" + content)
        for content in by_category.get("PROJECT_GUIDANCE", ())
    )
    return (
        LLMMessage("system", _WRITER_SYSTEM),
        LLMMessage("system", _FORMAT_SYSTEM),
    ) + project_guidance + (
        LLMMessage("user", f"当前章要求：\n{requirement.content}"),
        LLMMessage(
            "user",
            ("冻结 Brief：\n" if brief is not None else "基础模式约束：\n") + brief_text,
        ),
        LLMMessage("user", "近期章节全文：\n" + _joined(by_category, "RECENT_FULL")),
        LLMMessage(
            "user",
            "人物、知识、线索、正典和文风：\n" + _joined(by_category, "MEMORY"),
        ),
        LLMMessage(
            "user", "历史摘要与检索证据：\n" + _joined(by_category, "HISTORY")
        ),
        LLMMessage(
            "user",
            f"请创作约 {target} 字。"
            "严格执行以上约束，只输出本章正文。",
        ),
    )


def system_prompt_blocks() -> tuple[ContextBlock, ...]:
    return (
        ContextBlock(
            "system-writer-v1",
            "SYSTEM",
            _WRITER_SYSTEM,
            0,
            True,
            "SYSTEM_PROMPT",
            "writer-v1",
            None,
            1,
            PROSE_PROMPT_VERSION,
            "稳定的正文写作边界",
        ),
        ContextBlock(
            "system-format-v1",
            "SYSTEM",
            _FORMAT_SYSTEM,
            1,
            True,
            "SYSTEM_PROMPT",
            "format-v1",
            None,
            1,
            PROSE_PROMPT_VERSION,
            "稳定的输出与中断规则",
        ),
    )


def _joined(categories: dict[str, list[str]], name: str) -> str:
    return "\n\n".join(categories.get(name, ())) or "（无）"


def _brief_text(brief: ChapterBrief) -> str:
    lines = [
        f"戏剧功能：{brief.dramatic_purpose}",
        f"目标长度：{brief.target_length}",
        "必须事件：" + "；".join(brief.hard_events),
        "软目标：" + "；".join(brief.soft_goals),
        "禁止改动：" + "；".join(brief.prohibited_changes),
        "创作自由：" + "；".join(brief.creative_freedom),
    ]
    return "\n".join(lines)
