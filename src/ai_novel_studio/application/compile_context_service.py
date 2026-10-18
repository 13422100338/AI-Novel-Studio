from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryRequest,
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceHit,
    EvidenceOutcome,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.application.generation_memory_context_provider import (
    GenerationMemoryContextProvider,
)
from ai_novel_studio.core.context.context_builder import (
    BuiltContext,
    ContextBlock,
    ContextBuilder,
    ContextBuildRequest,
    RetrievalProvenance,
)
from ai_novel_studio.core.context.context_manifest import ContextManifest
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

_MAX_EVIDENCE_LIMIT = 200
_MAX_EVIDENCE_NEEDS = 8


class EvidenceNeedKind(StrEnum):
    HISTORICAL_DETAIL = "HISTORICAL_DETAIL"
    EXACT_QUOTE = "EXACT_QUOTE"
    EXISTENCE_CHECK = "EXISTENCE_CHECK"


@dataclass(frozen=True, slots=True)
class EvidenceNeed:
    kind: EvidenceNeedKind
    query: str
    participants: tuple[str, ...] = ()
    required_hits: int | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, EvidenceNeedKind)
            or not isinstance(self.query, str)
            or not self.query.strip()
            or not isinstance(self.participants, tuple)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in self.participants
            )
        ):
            raise ValueError("evidence need is invalid")
        if self.required_hits is not None and (
            isinstance(self.required_hits, bool)
            or not isinstance(self.required_hits, int)
            or self.required_hits < 1
        ):
            raise ValueError("evidence need is invalid")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= _MAX_EVIDENCE_LIMIT
        ):
            raise ValueError("evidence need is invalid")


@dataclass(frozen=True, slots=True)
class EvidenceNeedOutcome:
    kind: EvidenceNeedKind
    outcome: EvidenceOutcome
    hit_count: int


@dataclass(frozen=True, slots=True)
class CompiledEvidenceContext:
    built: BuiltContext
    evidence_outcomes: tuple[EvidenceNeedOutcome, ...]
    evidence_blocks: tuple[ContextBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class CompileContextRequest:
    chapter_id: str
    budget: TokenBudget
    run_id: str | None = None
    requirement: str = ""
    recent_chapter_texts: tuple[str, ...] = ()
    participant_ids: tuple[str, ...] = ()
    pov_character_id: str | None = None
    evidence_requests: tuple[EvidenceNeed, ...] = ()

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "chapter_id", validate_id(self.chapter_id))
            if self.run_id is not None:
                object.__setattr__(self, "run_id", validate_id(self.run_id))
            if self.pov_character_id is not None:
                object.__setattr__(
                    self,
                    "pov_character_id",
                    validate_id(self.pov_character_id),
                )
        except (TypeError, ValueError):
            raise ValueError("compile context request is invalid") from None
        if (
            not isinstance(self.budget, TokenBudget)
            or not isinstance(self.requirement, str)
            or not isinstance(self.recent_chapter_texts, tuple)
            or any(not isinstance(item, str) for item in self.recent_chapter_texts)
            or not isinstance(self.participant_ids, tuple)
            or any(not isinstance(item, str) for item in self.participant_ids)
            or not isinstance(self.evidence_requests, tuple)
            or any(
                not isinstance(need, EvidenceNeed)
                for need in self.evidence_requests
            )
            or len(self.evidence_requests) > _MAX_EVIDENCE_NEEDS
        ):
            raise ValueError("compile context request is invalid")


@dataclass(frozen=True, slots=True)
class ContextProjection:
    text: str
    included_categories: tuple[tuple[str, int], ...]
    evidence_hit_count: int
    estimated_input_tokens: int
    manifest_id: str


@dataclass(frozen=True, slots=True)
class CompiledContext:
    projection: ContextProjection
    manifest: ContextManifest


class CompileContextService:
    """Compiles explicit evidence needs through the one evidence facade and
    the existing context pipeline.

    Every need issues exactly one EvidenceQueryService.query call; each
    hydrated hit becomes one exact-evidence block whose content is only the
    hit text. NOT_FOUND and INSUFFICIENT are recorded as outcomes and are
    never backfilled from summaries. No second retriever, SQL path, model
    call, or Harness dependency exists here.
    """

    def __init__(
        self,
        *,
        evidence_query: EvidenceQueryService,
        builder: ContextBuilder | None = None,
        memory_context: GenerationMemoryContextProvider | None = None,
    ) -> None:
        if not isinstance(evidence_query, EvidenceQueryService):
            raise TypeError("compile context evidence service is invalid")
        if builder is not None and not isinstance(builder, ContextBuilder):
            raise TypeError("compile context builder is invalid")
        if memory_context is not None and not isinstance(
            memory_context,
            GenerationMemoryContextProvider,
        ):
            raise TypeError("compile context memory provider is invalid")
        self._evidence_query = evidence_query
        self._builder = builder or ContextBuilder()
        self._memory_context = memory_context

    @classmethod
    def for_project(
        cls,
        project: ProjectRepository,
        *,
        history: HistoryRetriever | None = None,
    ) -> CompileContextService:
        if not isinstance(project, ProjectRepository):
            raise TypeError("compile context project is invalid")
        search = SearchRepository(project)
        shared_history = history or HistoryRetriever(search)
        return cls(
            evidence_query=EvidenceQueryService(
                retriever=shared_history,
                evidence=FormalManuscriptEvidenceService(search),
            ),
            memory_context=GenerationMemoryContextProvider(
                project,
                shared_history,
            ),
        )

    def compile(
        self,
        base_request: ContextBuildRequest,
        *,
        evidence_needs: tuple[EvidenceNeed, ...] = (),
    ) -> CompiledEvidenceContext:
        if not isinstance(base_request, ContextBuildRequest):
            raise TypeError("compile context base request is invalid")
        if not isinstance(evidence_needs, tuple) or any(
            not isinstance(need, EvidenceNeed) for need in evidence_needs
        ):
            raise TypeError("compile context evidence needs are invalid")
        blocks: list[ContextBlock] = list(base_request.blocks)
        evidence_blocks: list[ContextBlock] = []
        outcomes: list[EvidenceNeedOutcome] = []
        for ordinal, need in enumerate(evidence_needs):
            result = self._evidence_query.query(
                EvidenceQueryRequest(
                    query=need.query,
                    target_chapter_id=base_request.chapter_id,
                    participants=tuple(
                        dict.fromkeys(
                            item.strip()
                            for item in need.participants
                            if item.strip()
                        )
                    ),
                    required_hits=need.required_hits,
                    limit=need.limit,
                )
            )
            outcomes.append(
                EvidenceNeedOutcome(need.kind, result.outcome, len(result.hits))
            )
            for index, hit in enumerate(result.hits):
                evidence_block = self._evidence_block(need, ordinal, index, hit)
                blocks.append(evidence_block)
                evidence_blocks.append(evidence_block)
        built = self._builder.build(replace(base_request, blocks=tuple(blocks)))
        return CompiledEvidenceContext(
            built, tuple(outcomes), tuple(evidence_blocks)
        )

    def build(self, request: CompileContextRequest) -> CompiledContext:
        if not isinstance(request, CompileContextRequest):
            raise TypeError("compile context request is invalid")
        if self._memory_context is None:
            raise ValueError("compile context project provider is unavailable")
        base_blocks = self._memory_context.blocks(
            request.chapter_id,
            request.requirement,
            request.recent_chapter_texts,
            request.participant_ids,
            pov_character_id=request.pov_character_id,
        )
        compiled = self.compile(
            ContextBuildRequest(
                chapter_id=request.chapter_id,
                run_id=request.run_id,
                budget=request.budget,
                blocks=base_blocks,
                deduplicate=True,
            ),
            evidence_needs=request.evidence_requests,
        )
        manifest = compiled.built.manifest
        category_counts: dict[str, int] = {}
        for item in manifest.selected:
            category_counts[item.category] = (
                category_counts.get(item.category, 0) + 1
            )
        selected_ids = {item.block_id for item in manifest.selected}
        projection = ContextProjection(
            text=compiled.built.text,
            included_categories=tuple(sorted(category_counts.items())),
            evidence_hit_count=sum(
                block.id in selected_ids for block in compiled.evidence_blocks
            ),
            estimated_input_tokens=manifest.estimated_input_tokens,
            manifest_id=manifest.id,
        )
        return CompiledContext(projection, manifest)

    @staticmethod
    def _evidence_block(
        need: EvidenceNeed,
        ordinal: int,
        index: int,
        hit: EvidenceHit,
    ) -> ContextBlock:
        return ContextBlock(
            id=f"EVIDENCE:{ordinal}:{index}",
            category="exact_evidence",
            content=hit.text,
            priority=15,
            required=False,
            source_type="FORMAL_MANUSCRIPT",
            source_id=hit.source_id,
            source_chapter_id=hit.chapter_id,
            source_revision=hit.source_revision,
            source_hash=hit.source_hash,
            rationale=f"EXACT_EVIDENCE:{need.kind.value}",
            retrieval=RetrievalProvenance(
                document_id=hit.document_id,
                expanded_document_ids=hit.expanded_document_ids,
                source_id=hit.source_id,
                source_hash=hit.source_hash,
                chapter_id=hit.chapter_id,
                volume_id=hit.volume_id,
                revision=hit.source_revision,
                start=hit.source_start,
                end=hit.source_end,
                retrieval_routes=hit.retrieval_routes,
                lexical_score=hit.lexical_score,
                semantic_score=hit.semantic_score,
                participant_boost=hit.participant_boost,
                pinned_weight=hit.pinned_weight,
                recency_score=hit.recency_score,
                stale_penalty=hit.stale_penalty,
                total_score=hit.total_score,
            ),
        )


__all__ = [
    "CompileContextRequest",
    "CompiledEvidenceContext",
    "CompiledContext",
    "CompileContextService",
    "ContextProjection",
    "EvidenceNeed",
    "EvidenceNeedKind",
    "EvidenceNeedOutcome",
]
