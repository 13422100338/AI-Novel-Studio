import sqlite3

import pytest

from ai_novel_studio.core.outline_links import chapter_markdown_link
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.migration_manager import MIGRATIONS, MigrationManager
from ai_novel_studio.infrastructure.storage.outline_link_repository import OutlineLinkRepository
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineConflictError,
    OutlineRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@pytest.fixture
def linked(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "关联测试")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "政变前夜", "1", "正式正文。")
    outlines = OutlineRepository(project)
    token = chapter_markdown_link(chapter.title, chapter.content_path)
    document = outlines.create("全书", "# 全书\n\n25. 政变\n" + token + "\n")
    return project, chapters, chapter, outlines, document.version.document_id, token


def test_scan_and_explicit_confirmation_survive_reopen(linked):
    project, chapters, chapter, outlines, document_id, token = linked
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    assert len(initial.items) == 1
    assert initial.items[0].status == "PENDING"
    link_id = initial.items[0].link.id
    confirmed = links.confirm(document_id, (link_id,), expected_fingerprint=initial.fingerprint)
    assert confirmed.items[0].status == "CONFIRMED"
    reopened = OutlineLinkRepository(ProjectRepository.open(project.layout.root)).scan(document_id)
    assert reopened.items[0].link.id == link_id
    assert [review.action for review in reopened.items[0].link.reviews] == [
        "DISCOVERED",
        "CONFIRMED",
    ]
    assert chapters.read_content_exact(chapter.id) == "正式正文。"


def test_read_only_view_does_not_discover_or_confirm_links(linked):
    project, _, _, _, document_id, _ = linked
    repository = OutlineLinkRepository(project)
    assert repository.read(document_id).items == ()
    registered = repository.scan(document_id)
    assert repository.read(document_id) == registered


def test_corrupt_review_history_fails_closed_without_rewriting_outline(linked):
    project, _, _, outlines, document_id, _ = linked
    repository = OutlineLinkRepository(project)
    registered = repository.scan(document_id)
    original = outlines.read(document_id)
    with project.database.connect() as connection, connection:
        connection.execute("UPDATE outline_chapter_links SET reviews_json='{}'")
    from ai_novel_studio.infrastructure.storage.outline_repository import OutlineIntegrityError

    with pytest.raises(OutlineIntegrityError):
        repository.confirm(
            document_id, (registered.items[0].link.id,), expected_fingerprint=registered.fingerprint
        )
    assert outlines.read(document_id) == original


@pytest.mark.parametrize("change", ["current", "other", "reorder"], ids=str)
def test_any_outline_change_expires_confirmation_without_deleting_links(linked, change):
    project, chapters, chapter, outlines, document_id, token = linked
    other = outlines.create("分卷", "# 第二部\n")
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    link_id = initial.items[0].link.id
    links.confirm(document_id, (link_id,), expected_fingerprint=initial.fingerprint)
    if change == "current":
        outlines.save(
            document_id, "新增前提\n" + outlines.read(document_id).content, expected_revision=1
        )
    elif change == "other":
        outlines.save(other.version.document_id, "另一卷已改\n", expected_revision=1)
    else:
        order = tuple(d.id for d in outlines.list_documents())
        outlines.reorder(tuple(reversed(order)), expected_order=order)
    updated = links.scan(document_id)
    assert updated.fingerprint != initial.fingerprint
    assert updated.items[0].link.id == link_id
    assert updated.items[0].status == "PENDING"
    with pytest.raises(OutlineConflictError):
        links.confirm(document_id, (link_id,), expected_fingerprint=initial.fingerprint)
    confirmed = links.confirm(document_id, (link_id,), expected_fingerprint=updated.fingerprint)
    assert len(confirmed.items[0].link.reviews) == 3


def test_noop_save_does_not_expire_confirmation(linked):
    project, _, _, outlines, document_id, _ = linked
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    links.confirm(
        document_id, (initial.items[0].link.id,), expected_fingerprint=initial.fingerprint
    )
    outlines.save(document_id, outlines.read(document_id).content, expected_revision=1)
    assert links.scan(document_id).items[0].status == "CONFIRMED"


def test_reorder_roundtrip_cannot_revalidate_old_confirmation(linked, monkeypatch):
    project, _, _, outlines, document_id, _ = linked
    outlines.create("第二部", "# 第二部\n")
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    link_id = initial.items[0].link.id
    links.confirm(document_id, (link_id,), expected_fingerprint=initial.fingerprint)
    order = tuple(d.id for d in outlines.list_documents())
    from ai_novel_studio.infrastructure.storage import outline_repository

    # Even an unchanged system clock must not reuse an earlier review token.
    class FrozenClock(outline_repository.datetime):
        @classmethod
        def now(cls, tz=None):
            return outlines.get(document_id).created_at

    monkeypatch.setattr(outline_repository, "datetime", FrozenClock)
    reversed_order = tuple(reversed(order))
    outlines.reorder(reversed_order, expected_order=order)
    outlines.reorder(order, expected_order=reversed_order)
    current = links.scan(document_id)
    assert current.fingerprint != initial.fingerprint
    assert current.items[0].status == "PENDING"
    assert [r.action for r in current.items[0].link.reviews] == ["DISCOVERED", "CONFIRMED"]
    with pytest.raises(OutlineConflictError):
        links.confirm(document_id, (link_id,), expected_fingerprint=initial.fingerprint)


def test_noop_reorder_preserves_confirmation(linked):
    project, _, _, outlines, document_id, _ = linked
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    links.confirm(
        document_id, (initial.items[0].link.id,), expected_fingerprint=initial.fingerprint
    )
    order = tuple(d.id for d in outlines.list_documents())
    outlines.reorder(order, expected_order=order)
    current = links.scan(document_id)
    assert current.fingerprint == initial.fingerprint
    assert current.items[0].status == "CONFIRMED"


def test_repeated_confirmation_is_idempotent(linked):
    project, _, _, _, document_id, _ = linked
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    ids = (initial.items[0].link.id,)
    links.confirm(document_id, ids, expected_fingerprint=initial.fingerprint)
    repeated = links.confirm(document_id, ids, expected_fingerprint=initial.fingerprint)
    assert len(repeated.items[0].link.reviews) == 2


def test_ambiguous_moved_links_require_explicit_location(linked):
    project, _, _, outlines, document_id, token = linked
    outlines.save(document_id, token + "\n" + token + "\n", expected_revision=1)
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    ids = tuple(item.link.id for item in initial.items)
    outlines.save(
        document_id,
        "# 新阶段\n\n25. 政变\n" + token + "\n铺垫\n" + token + "\n",
        expected_revision=2,
    )
    moved = links.scan(document_id)
    assert all(item.status == "MISSING_SOURCE" for item in moved.items)
    located = links.relocate(document_id, ids[0], 4, expected_fingerprint=moved.fingerprint)
    assert all(item.status == "PENDING" for item in located.items)
    confirmed = links.confirm(document_id, ids, expected_fingerprint=moved.fingerprint)
    assert all(item.status == "CONFIRMED" for item in confirmed.items)
    first = next(item for item in confirmed.items if item.link.id == ids[0])
    assert [review.action for review in first.link.reviews] == [
        "DISCOVERED",
        "RELOCATED",
        "CONFIRMED",
    ]
    assert first.link.reviews[1].source_line == 1


def test_confirmation_cannot_target_another_documents_records(linked):
    project, _, _, outlines, document_id, token = linked
    other = outlines.create("其他卷", token + "\n")
    links = OutlineLinkRepository(project)
    foreign = links.scan(other.version.document_id).items[0].link.id
    current = links.scan(document_id)
    with pytest.raises(OutlineConflictError):
        links.confirm(document_id, (foreign,), expected_fingerprint=current.fingerprint)
    assert links.read(document_id).items[0].status == "PENDING"


def test_deleted_source_is_retained_until_author_confirms_removal(linked):
    project, _, _, outlines, document_id, _ = linked
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    link_id = initial.items[0].link.id
    outlines.save(document_id, "# 不再引用该章\n", expected_revision=1)
    missing = links.scan(document_id)
    assert missing.items[0].status == "MISSING_SOURCE"
    with pytest.raises(OutlineConflictError):
        links.confirm(document_id, (link_id,), expected_fingerprint=missing.fingerprint)
    removed = links.retire(document_id, link_id, expected_fingerprint=missing.fingerprint)
    assert removed.items[0].status == "REMOVED"
    assert [r.action for r in removed.items[0].link.reviews] == ["DISCOVERED", "REMOVED"]
    assert outlines.read(document_id).content == "# 不再引用该章\n"


def test_reintroduced_link_is_pending_and_does_not_erase_removed_history(linked):
    project, _, _, outlines, document_id, token = linked
    links = OutlineLinkRepository(project)
    old = links.scan(document_id).items[0].link.id
    outlines.save(document_id, "# 不引用\n", expected_revision=1)
    missing = links.scan(document_id)
    links.retire(document_id, old, expected_fingerprint=missing.fingerprint)
    outlines.save(document_id, "# 再次引用\n" + token + "\n", expected_revision=2)
    current = links.scan(document_id)
    assert len(current.items) == 2
    assert next(item for item in current.items if item.link.id == old).status == "REMOVED"
    assert next(item for item in current.items if item.link.id != old).status == "PENDING"


def test_deleted_chapter_keeps_link_and_history(linked):
    project, chapters, chapter, outlines, document_id, _ = linked
    links = OutlineLinkRepository(project)
    initial = links.scan(document_id)
    chapters.delete_chapter(chapter.id)
    missing = links.scan(document_id)
    assert missing.items[0].link.id == initial.items[0].link.id
    assert missing.items[0].status == "MISSING_CHAPTER"
    with pytest.raises(OutlineConflictError):
        links.confirm(
            document_id, (missing.items[0].link.id,), expected_fingerprint=missing.fingerprint
        )


def test_batch_confirmation_rolls_back_if_one_link_is_invalid(linked):
    project, _, _, outlines, document_id, token = linked
    outlines.save(document_id, token + "\n\n" + token + "\n", expected_revision=1)
    links = OutlineLinkRepository(project)
    links.scan(document_id)
    outlines.save(document_id, token + "\n", expected_revision=2)
    current = links.scan(document_id)
    ids = tuple(item.link.id for item in current.items)
    assert len(ids) == 2
    with pytest.raises(OutlineConflictError):
        links.confirm(document_id, ids, expected_fingerprint=current.fingerprint)
    assert all(item.link.confirmed_fingerprint is None for item in links.scan(document_id).items)


def test_v26_upgrade_keeps_outline_rows() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for version in range(1, 27):
            MIGRATIONS[version](connection)
        connection.execute("PRAGMA user_version=26")
        connection.execute("INSERT INTO projects VALUES ('p', '保留项目', 1, 't', 't')")
        connection.execute(
            "INSERT INTO outline_documents VALUES ('d', 'p', '原纲', 0, 1, ?, 't', 't')",
            ("a" * 64,),
        )
        connection.execute("INSERT INTO outline_versions VALUES ('v', 'd', 1, ?, 't')", ("a" * 64,))
        before = connection.execute("SELECT * FROM outline_documents").fetchall()
        connection.commit()
        MigrationManager(connection).migrate()
        assert connection.execute("SELECT * FROM outline_documents").fetchall() == before
        assert connection.execute("SELECT COUNT(*) FROM outline_versions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM outline_chapter_links").fetchone()[0] == 0
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 27
