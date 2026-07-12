from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import (
    Authority,
    ReviewStatus,
    SourceType,
    StyleRule,
    StyleSample,
    StyleScope,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


@dataclass(frozen=True, slots=True)
class StyleWorkspaceSnapshot:
    rules: tuple[StyleRule, ...]
    samples: tuple[StyleSample, ...]


class StyleWorkspaceService:
    """Application boundary for user-managed style rules and samples."""

    def __init__(self, project: ProjectRepository) -> None:
        self.repository = StyleRepository(project)

    def load(self) -> StyleWorkspaceSnapshot:
        return StyleWorkspaceSnapshot(
            self.repository.list_all_rules(), self.repository.list_all_samples()
        )

    def add_rule(
        self, scope_type: StyleScope, scope_id: str, rule_type: str, text: str
    ) -> StyleRule:
        return self.repository.add_rule(
            scope_type,
            scope_id,
            rule_type,
            text,
            Authority.USER_CONFIRMED,
            ReviewStatus.APPROVED,
        )

    def update_rule(
        self,
        rule_id: str,
        scope_type: StyleScope,
        scope_id: str,
        rule_type: str,
        text: str,
    ) -> StyleRule:
        return self.repository.update_rule(
            rule_id,
            scope_type=scope_type,
            scope_id=scope_id,
            rule_type=rule_type,
            rule_text=text,
        )

    def delete_rule(self, rule_id: str) -> None:
        self.repository.delete_rule(rule_id)

    def add_sample(
        self, scope_type: StyleScope, scope_id: str, title: str, content: str
    ) -> StyleSample:
        return self.repository.add_sample(
            scope_type,
            scope_id,
            title,
            content,
            SourceType.HUMAN,
            Authority.USER_CONFIRMED,
            ReviewStatus.APPROVED,
            immutable=False,
        )

    def update_sample(
        self,
        sample_id: str,
        scope_type: StyleScope,
        scope_id: str,
        title: str,
        content: str,
    ) -> StyleSample:
        return self.repository.update_human_sample(
            sample_id,
            scope_type=scope_type,
            scope_id=scope_id,
            title=title,
            content=content,
        )

    def lock_sample(self, sample_id: str) -> StyleSample:
        return self.repository.lock_sample(sample_id)

    def delete_sample(self, sample_id: str) -> None:
        self.repository.delete_sample(sample_id)
