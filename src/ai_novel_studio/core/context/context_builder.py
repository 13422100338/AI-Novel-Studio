from __future__ import annotations

from dataclasses import dataclass, field

from ai_novel_studio.core.context.context_deduplication import ContextDeduplicator
from ai_novel_studio.core.context.context_filter import ContextEligibility
from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    OmittedManifestItem,
    SelectedManifestItem,
    create_manifest_id,
    utc_now,
)
from ai_novel_studio.core.context.context_ranking import ContextRanker, ContextTask
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
    eligibility: ContextEligibility = field(default_factory=ContextEligibility)


@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    chapter_id: str
    run_id: str | None
    budget: TokenBudget
    blocks: tuple[ContextBlock, ...]
    task: ContextTask | None = None
    deduplicate: bool = False
    minimum_category_coverage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized: list[str] = []
        for category in self.minimum_category_coverage:
            if not isinstance(category, str):
                raise ValueError("minimum category coverage must contain strings")
            value = category.strip()
            if not value:
                raise ValueError("minimum category coverage cannot be blank")
            normalized.append(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("minimum category coverage cannot contain duplicates")
        object.__setattr__(self, "minimum_category_coverage", tuple(normalized))


@dataclass(frozen=True, slots=True)
class BuiltContext:
    text: str
    manifest: ContextManifest


class ContextBuilder:
    def __init__(
        self,
        estimator: TokenEstimator | None = None,
        ranker: ContextRanker | None = None,
        deduplicator: ContextDeduplicator | None = None,
    ) -> None:
        self._estimator = estimator or ConservativeTokenEstimator()
        self._ranker = ranker or ContextRanker()
        self._deduplicator = deduplicator or ContextDeduplicator()

    def build(self, request: ContextBuildRequest) -> BuiltContext:
        ordered = sorted(request.blocks, key=lambda block: (block.priority, block.id))
        eligible: list[ContextBlock] = []
        omitted: list[OmittedManifestItem] = []
        for block in ordered:
            exclusion = block.eligibility.exclusion_reason()
            if exclusion is None:
                eligible.append(block)
                continue
            omitted.append(self._omitted_item(block, f"HARD_FILTER:{exclusion.value}"))

        required = [block for block in eligible if block.required]
        optional = [block for block in eligible if not block.required]
        ranked_optional = self._ranker.rank(optional, request.task)
        if request.deduplicate:
            deduplicated = self._deduplicator.deduplicate(ranked_optional)
            ranked_optional = deduplicated.kept
            omitted.extend(
                self._omitted_item(
                    duplicate.dropped.block,
                    f"DEDUPLICATED:{duplicate.kept_block_id}",
                )
                for duplicate in deduplicated.duplicates
            )
        required_tokens = sum(self._estimator.estimate(block.content) for block in required)
        if required_tokens > request.budget.input_limit:
            identifiers = ", ".join(block.id for block in required)
            raise RequiredContextOverflowError(
                f"必需上下文块超出输入预算，且不会被截断：{identifiers}；"
                f"需要 {required_tokens}，上限 {request.budget.input_limit}"
            )

        selected: list[SelectedManifestItem] = []
        contents: list[str] = []
        warnings: list[str] = []
        used_tokens = 0
        for block in required:
            tokens = self._estimator.estimate(block.content)
            selected.append(self._selected_item(block, tokens, used_fallback=False))
            contents.append(block.content)
            used_tokens += tokens

        guaranteed_block_ids: set[str] = set()
        for category in dict.fromkeys(request.minimum_category_coverage):
            candidates = tuple(
                ranked
                for ranked in ranked_optional
                if ranked.block.category == category
            )
            if not candidates:
                continue
            for ranked in candidates:
                representation = self._fitting_representation(
                    ranked.block,
                    request.budget.input_limit - used_tokens,
                )
                if representation is None:
                    continue
                content, tokens, used_fallback = representation
                selected.append(
                    self._selected_item(
                        ranked.block,
                        tokens,
                        used_fallback=used_fallback,
                        rationale=(
                            f"{ranked.rationale}；BUDGET_GUARANTEE:{category}"
                        ),
                    )
                )
                contents.append(content)
                used_tokens += tokens
                guaranteed_block_ids.add(ranked.block.id)
                break
            else:
                warnings.append(f"BUDGET_GUARANTEE_UNMET:{category}")

        for ranked in ranked_optional:
            block = ranked.block
            if block.id in guaranteed_block_ids:
                continue
            representation = self._fitting_representation(
                block,
                request.budget.input_limit - used_tokens,
            )
            if representation is not None:
                content, tokens, used_fallback = representation
                selected.append(
                    self._selected_item(
                        block,
                        tokens,
                        used_fallback=used_fallback,
                        rationale=ranked.rationale,
                    )
                )
                contents.append(content)
                used_tokens += tokens
                continue
            omitted.append(
                self._omitted_item(
                    block,
                    self._budget_omission_reason(ranked.ranking_note),
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
            warnings=tuple(warnings),
            created_at=utc_now(),
        )
        return BuiltContext("".join(contents), manifest)

    def _fitting_representation(
        self,
        block: ContextBlock,
        available_tokens: int,
    ) -> tuple[str, int, bool] | None:
        full_tokens = self._estimator.estimate(block.content)
        if full_tokens <= available_tokens:
            return block.content, full_tokens, False
        fallback = block.fallback_content
        if fallback is None:
            return None
        fallback_tokens = self._estimator.estimate(fallback)
        if fallback_tokens <= available_tokens:
            return fallback, fallback_tokens, True
        return None

    @staticmethod
    def _selected_item(
        block: ContextBlock,
        estimated_tokens: int,
        *,
        used_fallback: bool,
        rationale: str | None = None,
    ) -> SelectedManifestItem:
        return SelectedManifestItem(
            block_id=block.id,
            category=block.category,
            source_type=block.source_type,
            source_id=block.source_id,
            source_chapter_id=block.source_chapter_id,
            source_revision=block.source_revision,
            source_hash=block.source_hash,
            rationale=rationale or block.rationale,
            estimated_tokens=estimated_tokens,
            used_fallback=used_fallback,
        )

    @staticmethod
    def _omitted_item(block: ContextBlock, reason: str) -> OmittedManifestItem:
        return OmittedManifestItem(
            block_id=block.id,
            category=block.category,
            source_type=block.source_type,
            source_id=block.source_id,
            source_chapter_id=block.source_chapter_id,
            source_revision=block.source_revision,
            source_hash=block.source_hash,
            reason=reason,
        )

    @staticmethod
    def _budget_omission_reason(ranking_note: str | None) -> str:
        reason = "预算不足，未加入完整内容或摘要回退"
        return reason if ranking_note is None else f"{reason}；{ranking_note}"
