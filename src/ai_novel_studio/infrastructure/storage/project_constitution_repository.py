from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.project_constitution import (
    ConstitutionRule,
    ProjectConstitution,
    ProjectConstitutionProposal,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class StaleConstitutionRevisionError(RuntimeError):
    """The constitution changed since the expected base revision."""


def _now() -> datetime:
    return datetime.now(UTC)


def _rules_json(rules: tuple[ConstitutionRule, ...]) -> str:
    return json.dumps(
        [{"rule_id": rule.rule_id, "text": rule.text} for rule in rules],
        ensure_ascii=False,
    )


def _rules(value: str) -> tuple[ConstitutionRule, ...]:
    raw = json.loads(value)
    if not isinstance(raw, list):
        raise ValueError("constitution rules payload is invalid")
    return tuple(ConstitutionRule(item["rule_id"], item["text"]) for item in raw)


def _items_json(items: tuple[str, ...]) -> str:
    return json.dumps(list(items), ensure_ascii=False)


def _items(value: str) -> tuple[str, ...]:
    raw = json.loads(value)
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("constitution list payload is invalid")
    return tuple(raw)


class ProjectConstitutionRepository:
    """Versioned constitution storage (schema v23); one row per revision."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    @property
    def project_id(self) -> str:
        return self.project.project.id

    def current(self) -> ProjectConstitution | None:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_constitutions WHERE project_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (self.project_id,),
            ).fetchone()
        return self._constitution(row) if row is not None else None

    def get(self, revision: int) -> ProjectConstitution:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_constitutions WHERE project_id = ? AND revision = ?",
                (self.project_id, revision),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown constitution revision: {revision}")
        return self._constitution(row)

    def history(self) -> tuple[ProjectConstitution, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM project_constitutions WHERE project_id = ? "
                "ORDER BY revision",
                (self.project_id,),
            ).fetchall()
        return tuple(self._constitution(row) for row in rows)

    def save(
        self,
        proposal: ProjectConstitutionProposal,
        *,
        approved_by_author: bool,
        expected_revision: int,
    ) -> ProjectConstitution:
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT MAX(revision) AS max_revision FROM project_constitutions "
                "WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()
            current_revision = int(row["max_revision"] or 0)
            if current_revision != expected_revision:
                raise StaleConstitutionRevisionError(
                    "constitution revision changed: "
                    f"expected {expected_revision}, current {current_revision}"
                )
            revision = expected_revision + 1
            connection.execute(
                """
                INSERT INTO project_constitutions (
                    id, project_id, revision, shared_creative_rules_json,
                    agent_only_rules_json, writer_only_rules_json,
                    overridable_rules_json, non_overridable_rules_json,
                    source_decisions_json, unresolved_exclusions_json,
                    approved_by_author, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    self.project_id,
                    revision,
                    _rules_json(proposal.shared_creative_rules),
                    _rules_json(proposal.agent_only_rules),
                    _rules_json(proposal.writer_only_rules),
                    _rules_json(proposal.overridable_rules),
                    _rules_json(proposal.non_overridable_rules),
                    _items_json(proposal.source_decisions),
                    _items_json(proposal.unresolved),
                    int(approved_by_author),
                    now,
                ),
            )
        return self.get(revision)

    @staticmethod
    def _constitution(row: sqlite3.Row) -> ProjectConstitution:
        return ProjectConstitution(
            row["id"],
            row["project_id"],
            int(row["revision"]),
            _rules(row["shared_creative_rules_json"]),
            _rules(row["agent_only_rules_json"]),
            _rules(row["writer_only_rules_json"]),
            _rules(row["overridable_rules_json"]),
            _rules(row["non_overridable_rules_json"]),
            _items(row["source_decisions_json"]),
            _items(row["unresolved_exclusions_json"]),
            bool(row["approved_by_author"]),
            datetime.fromisoformat(row["created_at"]),
        )
