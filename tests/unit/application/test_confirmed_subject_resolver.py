from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_novel_studio.application.confirmed_subject_resolver import (
    ConfirmedSubjectResolutionError,
    ConfirmedSubjectResolver,
)
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


def _project(tmp_path: Path) -> ProjectRepository:
    return ProjectRepository.create(tmp_path / "project", "Confirmed subjects")


def _resolver(project: ProjectRepository) -> ConfirmedSubjectResolver:
    return ConfirmedSubjectResolver(SubjectRepository(project))


def _add_unconfirmed_alias(
    project: ProjectRepository,
    subject_id: str,
    alias: str,
) -> None:
    with project.database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO subject_aliases VALUES (?, ?, ?, ?, 0)",
            (new_id(), subject_id, alias, subject_id),
        )


def test_resolves_active_canonical_name_exactly(tmp_path: Path) -> None:
    project = _project(tmp_path)
    subject_id = CharacterMemoryRepository(project).create_character("艾琳").id

    resolved = _resolver(project).resolve_name("艾琳")

    assert resolved == (subject_id,)


def test_resolves_confirmed_alias_and_rejects_unconfirmed_or_wrong_case(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    characters = CharacterMemoryRepository(project)
    confirmed_id = characters.create_character("本名", ("小艾",)).id
    alice_id = characters.create_character("Alice").id
    _add_unconfirmed_alias(project, confirmed_id, "未确认名")

    resolver = _resolver(project)

    assert resolver.resolve_name("小艾") == (confirmed_id,)
    assert resolver.resolve_name("未确认名") == ()
    assert resolver.resolve_name("alice") == ()
    assert resolver.resolve_name("Alice") == (alice_id,)


def test_zero_and_multiple_matches_return_distinct_results(tmp_path: Path) -> None:
    project = _project(tmp_path)
    characters = CharacterMemoryRepository(project)
    characters.create_character("同名")
    second_id = characters.create_character("同名").id
    characters.create_character("陌生")

    resolved = _resolver(project).resolve_name("同名")
    nothing = _resolver(project).resolve_name("不存在")

    assert len(resolved) == 2
    assert second_id in resolved
    assert resolved == tuple(sorted(resolved))
    assert nothing == ()


def test_name_normalization_strips_but_stays_case_sensitive(tmp_path: Path) -> None:
    project = _project(tmp_path)
    characters = CharacterMemoryRepository(project)
    subject_id = characters.create_character("艾琳").id

    stripped = _resolver(project).resolve_name("  艾琳  ")

    assert stripped == (subject_id,)


def test_inactive_characters_are_never_resolved(tmp_path: Path) -> None:
    project = _project(tmp_path)
    characters = CharacterMemoryRepository(project)
    subject_id = characters.create_character("艾琳").id
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE subjects SET active = 0 WHERE id = ?", (subject_id,)
        )

    assert _resolver(project).resolve_name("艾琳") == ()
    assert (
        _resolver(project).resolve_active_character(subject_id) is None
    )


def test_resolve_active_character_requires_existing_active_character(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    character_id = CharacterMemoryRepository(project).create_character("艾琳").id

    resolved = _resolver(project).resolve_active_character(character_id)

    assert resolved == character_id
    assert _resolver(project).resolve_active_character(new_id()) is None


def test_storage_failures_raise_fixed_resolution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    CharacterMemoryRepository(project).create_character("艾琳")
    resolver = _resolver(project)

    def raw_failure(*args, **kwargs):
        raise sqlite3.OperationalError("RAW SQL SECRET")

    monkeypatch.setattr(SubjectRepository, "resolve_character_name", raw_failure)
    with pytest.raises(ConfirmedSubjectResolutionError):
        resolver.resolve_name("艾琳")

    monkeypatch.undo()
    monkeypatch.setattr(SubjectRepository, "get", raw_failure)
    with pytest.raises(ConfirmedSubjectResolutionError):
        resolver.resolve_active_character(new_id())


def test_constructor_rejects_non_repository(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="repository"):
        ConfirmedSubjectResolver(object())  # type: ignore[arg-type]
