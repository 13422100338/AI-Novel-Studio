from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import (
    Authority,
    MemoryStatus,
    ReviewStatus,
    SourceType,
    StyleRule,
    StyleSample,
    StyleScope,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    ProtectedMemoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class StyleRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def add_rule(
        self,
        scope_type: StyleScope,
        scope_id: str,
        rule_type: str,
        rule_text: str,
        authority: Authority,
        review_status: ReviewStatus,
        *,
        limit_per_chapter: int | None = None,
        limit_per_volume: int | None = None,
        limit_per_book: int | None = None,
    ) -> StyleRule:
        if not scope_id.strip() or not rule_type.strip() or not rule_text.strip():
            raise ValueError("文风规则范围、类型和正文不能为空")
        limits = (limit_per_chapter, limit_per_volume, limit_per_book)
        if any(limit is not None and limit < 0 for limit in limits):
            raise ValueError("文风规则次数限制不能为负数")
        rule = StyleRule(
            new_id(),
            scope_type,
            scope_id,
            rule_type.strip(),
            rule_text.strip(),
            limit_per_chapter,
            limit_per_volume,
            limit_per_book,
            authority,
            review_status,
            MemoryStatus.CURRENT,
        )
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO style_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.id,
                    rule.scope_type.value,
                    rule.scope_id,
                    rule.rule_type,
                    rule.rule_text,
                    rule.limit_per_chapter,
                    rule.limit_per_volume,
                    rule.limit_per_book,
                    rule.authority.value,
                    rule.review_status.value,
                    rule.status.value,
                    now,
                    now,
                ),
            )
        return rule

    def rules(self, scope_type: StyleScope, scope_id: str) -> tuple[StyleRule, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM style_rules
                WHERE scope_type = ? AND scope_id = ? AND status = 'CURRENT'
                  AND review_status IN ('APPROVED', 'LOCKED')
                ORDER BY id
                """,
                (scope_type.value, scope_id),
            ).fetchall()
        rules = [self._rule(row) for row in rows]
        return tuple(sorted(rules, key=lambda rule: (-rule.authority.rank, rule.id)))

    def add_sample(
        self,
        scope_type: StyleScope,
        scope_id: str,
        title: str,
        content: str,
        source_type: SourceType,
        authority: Authority,
        review_status: ReviewStatus,
        *,
        immutable: bool,
    ) -> StyleSample:
        if not title.strip() or not content.strip():
            raise ValueError("样章标题和内容不能为空")
        sample = StyleSample(
            new_id(),
            scope_type,
            scope_id,
            title.strip(),
            content,
            source_type,
            authority,
            review_status,
            immutable,
            _hash(content),
        )
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO style_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sample.id,
                    sample.scope_type.value,
                    sample.scope_id,
                    sample.title,
                    sample.content,
                    sample.source_type.value,
                    sample.authority.value,
                    sample.review_status.value,
                    int(sample.immutable),
                    sample.content_hash,
                    now,
                    now,
                ),
            )
        return sample

    def samples(self, scope_type: StyleScope, scope_id: str) -> tuple[StyleSample, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM style_samples
                WHERE scope_type = ? AND scope_id = ?
                  AND review_status IN ('APPROVED', 'LOCKED')
                ORDER BY id
                """,
                (scope_type.value, scope_id),
            ).fetchall()
        samples = [self._sample(row) for row in rows]
        return tuple(sorted(samples, key=lambda item: (-item.authority.rank, item.id)))

    def update_sample(
        self,
        sample_id: str,
        content: str,
        source_type: SourceType,
    ) -> StyleSample:
        sample = self._get_sample(sample_id)
        if sample.immutable:
            raise ProtectedMemoryError("人工原始样章不可修改")
        if source_type == SourceType.MODEL and sample.authority == Authority.USER_CONFIRMED:
            raise ProtectedMemoryError("模型不能覆盖用户确认的样章")
        if not content.strip():
            raise ValueError("样章内容不能为空")
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE style_samples SET content = ?, content_hash = ?, "
                "updated_at = ? WHERE id = ?",
                (content, _hash(content), _now().isoformat(), sample_id),
            )
        return self._get_sample(sample_id)

    def _get_sample(self, sample_id: str) -> StyleSample:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM style_samples WHERE id = ?", (sample_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown style sample: {sample_id}")
        return self._sample(row)

    @staticmethod
    def _rule(row: sqlite3.Row) -> StyleRule:
        return StyleRule(
            row["id"],
            StyleScope(row["scope_type"]),
            row["scope_id"],
            row["rule_type"],
            row["rule_text"],
            row["limit_per_chapter"],
            row["limit_per_volume"],
            row["limit_per_book"],
            Authority(row["authority"]),
            ReviewStatus(row["review_status"]),
            MemoryStatus(row["status"]),
        )

    @staticmethod
    def _sample(row: sqlite3.Row) -> StyleSample:
        return StyleSample(
            row["id"],
            StyleScope(row["scope_type"]),
            row["scope_id"],
            row["title"],
            row["content"],
            SourceType(row["source_type"]),
            Authority(row["authority"]),
            ReviewStatus(row["review_status"]),
            bool(row["immutable"]),
            row["content_hash"],
        )
