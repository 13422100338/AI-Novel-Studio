from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import StyleRule, StyleSample, StyleScope
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


@dataclass(frozen=True, slots=True)
class CompiledStyle:
    rules: tuple[StyleRule, ...]
    samples: tuple[StyleSample, ...]


class StyleRetriever:
    def __init__(self, repository: StyleRepository) -> None:
        self.repository = repository

    def for_task(
        self,
        book_id: str,
        scene_scope: str | None,
        character_ids: tuple[str, ...],
        chapter_id: str,
    ) -> CompiledStyle:
        scopes: list[tuple[StyleScope, str]] = [(StyleScope.BOOK, book_id)]
        if scene_scope:
            scopes.append((StyleScope.GENRE_OR_SCENE, scene_scope))
        scopes.extend((StyleScope.CHARACTER, value) for value in character_ids)
        scopes.append((StyleScope.CHAPTER, chapter_id))
        rules: list[StyleRule] = []
        samples: list[StyleSample] = []
        for scope_type, scope_id in scopes:
            rules.extend(self.repository.rules(scope_type, scope_id))
            samples.extend(self.repository.samples(scope_type, scope_id))
        return CompiledStyle(tuple(rules), tuple(samples))
