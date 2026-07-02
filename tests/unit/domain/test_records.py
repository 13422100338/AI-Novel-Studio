from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest

from ai_novel_studio.domain.chapter import Chapter, ChapterVersion
from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.project import Project
from ai_novel_studio.domain.volume import Volume


def test_new_id_returns_canonical_uuid_string() -> None:
    value = new_id()

    assert str(UUID(value)) == value


def test_validate_id_rejects_non_uuid() -> None:
    with pytest.raises(ValueError, match="valid UUID"):
        validate_id("chapter-one")


def test_records_keep_identity_separate_from_editable_metadata() -> None:
    now = datetime.now(UTC)
    project = Project(new_id(), "Novel", 1, now, now)
    volume = Volume(new_id(), "Volume One", "", 0, now, now)
    chapter = Chapter(
        new_id(), volume.id, "1", "Opening", "", "manuscript/chapter.md", 0, 0,
        "pending", False, now, now,
    )
    version = ChapterVersion(new_id(), chapter.id, 0, "history/rev-0.md", "manual", "edit", now, "abc")

    assert project.format_version == 1
    assert volume.title == "Volume One"
    assert chapter.declared_number == "1"
    assert chapter.id != chapter.title
    assert version.chapter_id == chapter.id


def test_domain_records_are_immutable() -> None:
    now = datetime.now(UTC)
    volume = Volume(new_id(), "Volume One", "", 0, now, now)

    with pytest.raises(FrozenInstanceError):
        volume.title = "Renamed"  # type: ignore[misc]
