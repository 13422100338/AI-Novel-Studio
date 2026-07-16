from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from ai_novel_studio.application.model_tasks import (
    ChatSummaryResult,
    NormalizedBrief,
    StyleAuditResult,
)
from ai_novel_studio.infrastructure.llm import LLMMessage, LLMStreamEvent


class ModelTaskPort(Protocol):
    def stream_chat(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript_excerpt: str,
        output_token_limit: int,
    ) -> Iterator[LLMStreamEvent]: ...

    def draft_chapter_requirement(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript_excerpt: str,
        output_token_limit: int,
    ) -> str: ...

    def normalize_brief(self, source: str, output_token_limit: int) -> NormalizedBrief: ...

    def audit_style(
        self,
        manuscript: str,
        rules: tuple[str, ...],
        output_token_limit: int,
    ) -> StyleAuditResult: ...

    def summarize_chat(
        self, existing_summary: str, transcript: str, output_token_limit: int
    ) -> ChatSummaryResult: ...
