from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ai_novel_studio.core.context.style_retriever import (
    CompiledStyle,
    StyleRetriever,
)
from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.memory import (
    StyleRule,
    StyleSample,
    StyleSampleReviewCandidate,
)


@dataclass(frozen=True, slots=True)
class StyleProjectionRequest:
    """Bounded request for the style projection facade (H0 step 4)."""

    book_id: str
    chapter_id: str
    scene_scope: str | None = None
    character_ids: tuple[str, ...] = ()
    include_ineligible_rules: bool = False
    include_ineligible_samples: bool = False
    writer_sample_selection: bool = False

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "book_id", validate_id(self.book_id))
            object.__setattr__(self, "chapter_id", validate_id(self.chapter_id))
        except ValueError:
            raise ValueError("style projection identifiers are invalid") from None
        if not isinstance(self.character_ids, tuple) or any(
            not isinstance(value, str) for value in self.character_ids
        ):
            raise ValueError("style projection character ids are invalid")
        if self.scene_scope is not None:
            object.__setattr__(self, "scene_scope", self.scene_scope.strip())
            if not self.scene_scope:
                object.__setattr__(self, "scene_scope", None)


@dataclass(frozen=True, slots=True)
class StyleProjection:
    """Bounded style projection DTO owned by this capability (H0 step 4)."""

    projection_id: str
    rules: tuple[StyleRule, ...]
    samples: tuple[StyleSample, ...]
    ineligible_rules: tuple[StyleRule, ...]
    ineligible_samples: tuple[StyleSampleReviewCandidate, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.projection_id.strip():
            raise ValueError("style projection id cannot be empty")
        for field in ("rules", "samples", "ineligible_rules", "ineligible_samples"):
            if not isinstance(getattr(self, field), tuple):
                raise ValueError(f"style projection {field} is invalid")


class StyleProjectionService:
    """build_style_projection facade over the existing StyleRetriever."""

    def __init__(self, retriever: StyleRetriever) -> None:
        if not isinstance(retriever, StyleRetriever):
            raise TypeError("style retriever is invalid")
        self._retriever = retriever

    def build(self, request: StyleProjectionRequest) -> StyleProjection:
        if not isinstance(request, StyleProjectionRequest):
            raise TypeError("style projection request is invalid")
        compiled: CompiledStyle = self._retriever.for_task(
            request.book_id,
            request.scene_scope,
            request.character_ids,
            request.chapter_id,
            include_ineligible_rules=request.include_ineligible_rules,
            include_ineligible_samples=request.include_ineligible_samples,
            writer_sample_selection=request.writer_sample_selection,
        )
        return StyleProjection(
            projection_id=new_id(),
            rules=compiled.rules,
            samples=compiled.samples,
            ineligible_rules=compiled.ineligible_rules,
            ineligible_samples=compiled.ineligible_samples,
            created_at=datetime.now(UTC),
        )
