from PySide6.QtCore import QUrl

from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_link_repository import OutlineLinkRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bridge.outline_bridge import OutlineBridge


def _create(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "关联界面")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "铺垫章节", "2", "不能改写的正式正文。"
    )
    bridge = OutlineBridge()
    bridge.bind_project(project)
    assert bridge.newDocument("全书")
    bridge.edit("# 全书\n\n25. 政变\n")
    assert bridge.flush()
    return project, chapter, bridge


def test_insert_confirm_and_outline_edit_require_new_confirmation(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    assert bridge.insertChapterLink(chapter.id, 3)
    assert len(bridge.state["links"]) == 1
    link = bridge.state["links"][0]
    assert link["status"] == "PENDING"
    fingerprint = bridge.state["linkFingerprint"]
    assert bridge.confirmLinks([link["id"]], fingerprint)
    assert bridge.state["links"][0]["status"] == "CONFIRMED"
    bridge.edit(bridge.state["text"] + "新增事件前提\n")
    assert not bridge.confirmLinks([link["id"]], fingerprint)
    assert bridge.flush()
    assert bridge.state["links"][0]["id"] == link["id"]
    assert bridge.state["links"][0]["status"] == "PENDING"
    assert not bridge.confirmLinks([link["id"]], fingerprint)
    assert ChapterRepository(project).read_content_exact(chapter.id) == "不能改写的正式正文。"
    bridge.bind_project(None)


def test_manual_link_uses_plain_markdown_and_can_be_opened(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    opened = []
    bridge.chapterRequested.connect(opened.append)
    assert bridge.insertChapterLink(chapter.id, 3)
    raw = OutlineRepository(project).read(bridge.state["currentId"]).content
    assert "[铺垫章节](../manuscript/" in raw
    assert bridge.openLinkedChapter(chapter.id)
    assert opened == [chapter.id]
    bridge.bind_project(None)


def test_removal_is_explicit_and_history_remains_visible(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    assert bridge.insertChapterLink(chapter.id, 3)
    link = bridge.state["links"][0]
    bridge.edit("# 不再引用该章\n")
    assert bridge.flush()
    assert bridge.state["links"][0]["status"] == "MISSING_SOURCE"
    assert bridge.retireLink(link["id"], bridge.state["linkFingerprint"])
    assert bridge.state["links"][0]["status"] == "REMOVED"
    assert len(bridge.state["links"][0]["history"]) == 2
    bridge.bind_project(None)


def test_imported_markdown_links_are_pending_without_auto_confirmation(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    assert bridge.insertChapterLink(chapter.id, 3)
    raw = OutlineRepository(project).read(bridge.state["currentId"]).content
    source = tmp_path / "import.md"
    source.write_bytes(raw.encode())
    assert bridge.importFile(QUrl.fromLocalFile(str(source)))
    assert bridge.state["links"][0]["status"] == "PENDING"
    assert bridge.state["pendingLinkCount"] == 2
    bridge.bind_project(None)


def test_refresh_cannot_confirm_sources_newer_than_the_displayed_outline(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    assert bridge.insertChapterLink(chapter.id, 3)
    document_id = bridge.state["currentId"]
    displayed = bridge.state["text"]
    link_id = bridge.state["links"][0]["id"]
    outlines = OutlineRepository(project)
    outlines.save(
        document_id, "新版本前提\n" + displayed, expected_revision=bridge.state["revision"]
    )
    newer = OutlineLinkRepository(project).scan(document_id)
    assert not bridge.refreshLinks()
    assert not bridge.state["linksReady"]
    assert bridge.state["text"] == displayed
    assert not bridge.confirmLinks([link_id], newer.fingerprint)
    assert OutlineLinkRepository(project).scan(document_id).items[0].status == "PENDING"
    bridge.bind_project(None)


def test_unseen_version_is_rejected_before_confirmation_is_committed(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    assert bridge.insertChapterLink(chapter.id, 3)
    document_id = bridge.state["currentId"]
    displayed = bridge.state["text"]
    link_id = bridge.state["links"][0]["id"]
    OutlineRepository(project).save(
        document_id, "新版本前提\n" + displayed, expected_revision=bridge.state["revision"]
    )
    repository = OutlineLinkRepository(project)
    newer = repository.scan(document_id)
    assert bridge.state["linksReady"]
    assert not bridge.confirmLinks([link_id], newer.fingerprint)
    current = repository.read(document_id)
    assert current.items[0].status == "PENDING"
    assert [r.action for r in current.items[0].link.reviews] == ["DISCOVERED"]
    assert bridge.state["text"] == displayed
    bridge.bind_project(None)


def test_reordering_immediately_refreshes_visible_confirmation(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    OutlineRepository(project).create("分卷", "# 第二部\n")
    assert bridge.insertChapterLink(chapter.id, 3)
    link_id = bridge.state["links"][0]["id"]
    initial = bridge.state["linkFingerprint"]
    assert bridge.confirmLinks([link_id], initial)
    assert bridge.moveDocument(1)
    assert bridge.state["links"][0]["status"] == "PENDING"
    assert bridge.state["linkFingerprint"] != initial
    assert bridge.moveDocument(-1)
    assert bridge.state["links"][0]["status"] == "PENDING"
    assert bridge.state["linkFingerprint"] != initial
    bridge.bind_project(None)


def test_link_index_failure_does_not_lose_saved_markdown(tmp_path, qapp):
    project, chapter, bridge = _create(tmp_path)
    with project.database.connect() as connection:
        connection.execute(
            "CREATE TRIGGER block_link_index BEFORE INSERT ON outline_chapter_links "
            "BEGIN SELECT RAISE(ABORT, 'simulated link index failure'); END"
        )
    assert bridge.insertChapterLink(chapter.id, 3)
    assert not bridge.state["dirty"]
    assert not bridge.state["linksReady"]
    assert bridge.state["linksError"]
    saved = OutlineRepository(project).read(bridge.state["currentId"])
    assert "[铺垫章节](../manuscript/" in saved.content
    with project.database.connect() as connection:
        connection.execute("DROP TRIGGER block_link_index")
    assert bridge.refreshLinks()
    assert bridge.state["links"][0]["status"] == "PENDING"
    bridge.bind_project(None)
