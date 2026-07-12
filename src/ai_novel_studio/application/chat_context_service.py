from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.core.context.token_budget import (
    ConservativeTokenEstimator,
    TokenEstimator,
)
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.infrastructure.storage.chat_history_repository import (
    ChatMessage,
    ChatSession,
)


@dataclass(frozen=True, slots=True)
class ChatContextSelection:
    messages: tuple[LLMMessage, ...]
    included_sequences: tuple[int, ...]
    omitted_messages: int
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ChatCompressionCandidate:
    transcript: str
    through_sequence: int


class ChatContextService:
    def __init__(self, estimator: TokenEstimator | None = None) -> None:
        self.estimator = estimator or ConservativeTokenEstimator()

    def select(
        self,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        *,
        token_budget: int,
    ) -> ChatContextSelection:
        if token_budget <= 0:
            raise ValueError("聊天历史 Token 预算必须大于 0")
        selected: list[ChatMessage] = []
        used = 0
        summary_message: LLMMessage | None = None
        if session.summary.strip():
            candidate = LLMMessage(
                "system", "以下是更早剧情商讨的项目级摘要：\n" + session.summary.strip()
            )
            summary_tokens = self.estimator.estimate(candidate.content)
            if summary_tokens <= token_budget:
                summary_message = candidate
                used += summary_tokens
        unsummarized = tuple(
            item
            for item in messages
            if item.sequence > session.summarized_through_sequence
        )
        for item in reversed(unsummarized):
            tokens = self.estimator.estimate(item.content)
            if used + tokens > token_budget and selected:
                continue
            selected.append(item)
            used += tokens
        selected.reverse()
        output = tuple(
            LLMMessage(item.role, item.content) for item in selected
        )
        if summary_message is not None:
            output = (summary_message, *output)
        return ChatContextSelection(
            output,
            tuple(item.sequence for item in selected),
            len(messages) - len(selected),
            used,
        )

    def compression_candidate(
        self,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        *,
        retain_recent_tokens: int,
        minimum_source_tokens: int = 1_000,
    ) -> ChatCompressionCandidate | None:
        unsummarized = [
            item for item in messages if item.sequence > session.summarized_through_sequence
        ]
        if len(unsummarized) < 4:
            return None
        recent_tokens = 0
        kept_recent = 0
        split = len(unsummarized)
        for index in range(len(unsummarized) - 1, -1, -1):
            tokens = self.estimator.estimate(unsummarized[index].content)
            if kept_recent >= 2 and recent_tokens + tokens > retain_recent_tokens:
                split = index + 1
                break
            recent_tokens += tokens
            kept_recent += 1
            split = index
        older = unsummarized[:split]
        source_tokens = sum(self.estimator.estimate(item.content) for item in older)
        if not older or source_tokens < minimum_source_tokens:
            return None
        transcript = "\n\n".join(
            f"{item.role}: {item.content}" for item in older
        )
        return ChatCompressionCandidate(transcript, older[-1].sequence)
