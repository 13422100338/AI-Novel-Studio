from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    OmittedManifestItem,
    SelectedManifestItem,
    create_manifest_id,
    utc_now,
)
from ai_novel_studio.core.context.token_budget import (
    ConservativeTokenEstimator,
    TokenBudget,
    TokenEstimator,
)


class RequiredContextOverflowError(ValueError):
    """Raised when mandatory whole blocks exceed the available input budget."""


@dataclass(frozen=True, slots=True)
class ContextBlock:
    id: str
    category: str
    content: str
    priority: int
    required: bool
    source_type: str
    source_id: str
    source_chapter_id: str | None
    source_revision: int | None
    source_hash: str
    rationale: str
    fallback_content: str | None = None


@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    chapter_id: str
    run_id: str | None
    budget: TokenBudget
    blocks: tuple[ContextBlock, ...]


@dataclass(frozen=True, slots=True)
class BuiltContext:
    text: str
    manifest: ContextManifest


class ContextBuilder:
    def __init__(self, estimator: TokenEstimator | None = None) -> None:
        self._estimator = estimator or ConservativeTokenEstimator()

    def build(self, request: ContextBuildRequest) -> BuiltContext:
        ordered = sorted(request.blocks, key=lambda block: (block.priority, block.id))
        required = [block for block in ordered if block.required]
        optional = [block for block in ordered if not block.required]
        required_tokens = sum(self._estimator.estimate(block.content) for block in required)
        if required_tokens > request.budget.input_limit:
            identifiers = ", ".join(block.id for block in required)
            raise RequiredContextOverflowError(
                f"必需上下文块超出输入预算，且不会被截断：{identifiers}；"
                f"需要 {required_tokens}，上限 {request.budget.input_limit}"
            )

        selected: list[SelectedManifestItem] = []
        omitted: list[OmittedManifestItem] = []
        contents: list[str] = []
        used_tokens = 0
        for block in required:
            tokens = self._estimator.estimate(block.content)
            selected.append(self._selected_item(block, tokens, used_fallback=False))
            contents.append(block.content)
            used_tokens += tokens

        for block in optional:
            full_tokens = self._estimator.estimate(block.content)
            if used_tokens + full_tokens <= request.budget.input_limit:
                selected.append(self._selected_item(block, full_tokens, used_fallback=False))
                contents.append(block.content)
                used_tokens += full_tokens
                continue
            fallback = block.fallback_content
            fallback_tokens = self._estimator.estimate(fallback) if fallback is not None else 0
            if fallback is not None and used_tokens + fallback_tokens <= request.budget.input_limit:
                selected.append(self._selected_item(block, fallback_tokens, used_fallback=True))
                contents.append(fallback)
                used_tokens += fallback_tokens
                continue
            omitted.append(
                OmittedManifestItem(
                    block_id=block.id,
                    category=block.category,
                    source_type=block.source_type,
                    source_id=block.source_id,
                    source_chapter_id=block.source_chapter_id,
                    source_revision=block.source_revision,
                    source_hash=block.source_hash,
                    reason="预算不足，未加入完整内容或摘要回退",
                )
            )

        manifest = ContextManifest(
            id=create_manifest_id(),
            chapter_id=request.chapter_id,
            run_id=request.run_id,
            input_token_limit=request.budget.input_limit,
            output_token_limit=request.budget.output_limit,
            estimated_input_tokens=used_tokens,
            selected=tuple(selected),
            omitted=tuple(omitted),
            warnings=(),
            created_at=utc_now(),
        )
        return BuiltContext("".join(contents), manifest)

    @staticmethod
    def _selected_item(
        block: ContextBlock, estimated_tokens: int, *, used_fallback: bool
    ) -> SelectedManifestItem:
        return SelectedManifestItem(
            block_id=block.id,
            category=block.category,
            source_type=block.source_type,
            source_id=block.source_id,
            source_chapter_id=block.source_chapter_id,
            source_revision=block.source_revision,
            source_hash=block.source_hash,
            rationale=block.rationale,
            estimated_tokens=estimated_tokens,
            used_fallback=used_fallback,
        )
