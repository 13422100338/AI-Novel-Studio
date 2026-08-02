from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import (
    StyleRule,
    StyleSample,
    StyleSampleReviewCandidate,
    StyleScope,
)
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository

MAX_INELIGIBLE_STYLE_RULES = 100
MAX_INELIGIBLE_STYLE_SAMPLES = 20
MAX_WRITER_STYLE_SAMPLES = 4


@dataclass(frozen=True, slots=True)
class CompiledStyle:
    rules: tuple[StyleRule, ...]
    samples: tuple[StyleSample, ...]
    ineligible_rules: tuple[StyleRule, ...] = ()
    ineligible_samples: tuple[StyleSampleReviewCandidate, ...] = ()


class StyleRetriever:
    def __init__(self, repository: StyleRepository) -> None:
        self.repository = repository

    def for_task(
        self,
        book_id: str,
        scene_scope: str | None,
        character_ids: tuple[str, ...],
        chapter_id: str,
        *,
        include_ineligible_rules: bool = False,
        include_ineligible_samples: bool = False,
        writer_sample_selection: bool = False,
    ) -> CompiledStyle:
        scopes: list[tuple[StyleScope, str]] = [(StyleScope.BOOK, book_id)]
        if scene_scope:
            scopes.append((StyleScope.GENRE_OR_SCENE, scene_scope))
        scopes.extend((StyleScope.CHARACTER, value) for value in character_ids)
        scopes.append((StyleScope.CHAPTER, chapter_id))
        writer_sample_scopes: list[tuple[StyleScope, str]] = [
            (StyleScope.CHAPTER, chapter_id),
            *((StyleScope.CHARACTER, value) for value in character_ids),
        ]
        if scene_scope:
            writer_sample_scopes.append((StyleScope.GENRE_OR_SCENE, scene_scope))
        writer_sample_scopes.append((StyleScope.BOOK, book_id))
        rules: list[StyleRule] = []
        samples: list[StyleSample] = []
        ineligible_rules: list[StyleRule] = []
        ineligible_samples: list[StyleSampleReviewCandidate] = []
        for scope_type, scope_id in scopes:
            rules.extend(self.repository.rules(scope_type, scope_id))
            if not writer_sample_selection:
                samples.extend(self.repository.samples(scope_type, scope_id))
            remaining = MAX_INELIGIBLE_STYLE_RULES - len(ineligible_rules)
            if include_ineligible_rules and remaining > 0:
                ineligible_rules.extend(
                    self.repository.ineligible_rules(
                        scope_type,
                        scope_id,
                        limit=remaining,
                    )
                )
            remaining_samples = MAX_INELIGIBLE_STYLE_SAMPLES - len(ineligible_samples)
            if include_ineligible_samples and remaining_samples > 0:
                ineligible_samples.extend(
                    self.repository.ineligible_samples(
                        scope_type,
                        scope_id,
                        limit=remaining_samples,
                    )
                )
        if writer_sample_selection:
            for scope_type, scope_id in writer_sample_scopes:
                remaining = MAX_WRITER_STYLE_SAMPLES - len(samples)
                if remaining <= 0:
                    break
                samples.extend(self.repository.samples(scope_type, scope_id)[:remaining])
        return CompiledStyle(
            tuple(rules),
            tuple(samples),
            tuple(ineligible_rules),
            tuple(ineligible_samples),
        )
