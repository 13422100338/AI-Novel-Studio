import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceResult,
    SubmittedRevision,
)
from ai_novel_studio.application.manuscript_import_service import ManuscriptImportService
from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_import_markdown_splits_chapters_and_ignores_end_markers(tmp_path: Path) -> None:
    source = tmp_path / "draft.md"
    source.write_text(
        "# 第一卷 潮声\n\n"
        "# 第1章 雪夜来客\n\n"
        "雪落下来。\n\n"
        "# 第1章 完\n\n"
        "# 第2章 没有寄出的信\n\n"
        "信封没有署名。\n",
        encoding="utf-8",
    )
    project = ProjectRepository.create(tmp_path / "project", "Imported Novel")

    report = ManuscriptImportService().import_file(project, source)

    chapters = ChapterRepository(project).list_chapters()
    assert report.source == source.resolve()
    assert report.imported_volumes == 1
    assert report.imported_chapters == 2
    assert report.first_chapter_id == chapters[0].id
    assert [chapter.declared_number for chapter in chapters] == ["第1章", "第2章"]
    assert [chapter.title for chapter in chapters] == ["雪夜来客", "没有寄出的信"]
    assert ChapterRepository(project).read_content(chapters[0].id) == "雪落下来。"
    assert [
        tuple(
            document.content
            for document in SearchRepository(project).read_formal_manuscript_chunks(
                chapter.id,
                expected_revision=0,
                expected_source_hash=_source_hash(
                    ChapterRepository(project).read_content_exact(chapter.id)
                ),
                chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
            )
        )
        for chapter in chapters
    ] == [("雪落下来。",), ("信封没有署名。",)]


def test_import_plain_text_without_headings_creates_single_chapter(tmp_path: Path) -> None:
    source = tmp_path / "draft.txt"
    source.write_text("没有章节标题的正文。", encoding="utf-8")
    project = ProjectRepository.create(tmp_path / "project", "Imported Novel")

    report = ManuscriptImportService().import_file(project, source)

    chapters = ChapterRepository(project).list_chapters()
    assert report.imported_chapters == 1
    assert chapters[0].title == "draft"
    assert ChapterRepository(project).read_content(chapters[0].id) == "没有章节标题的正文。"
    assert tuple(
        document.content
        for document in SearchRepository(project).read_formal_manuscript_chunks(
            chapters[0].id,
            expected_revision=0,
            expected_source_hash=_source_hash(
                ChapterRepository(project).read_content_exact(chapters[0].id)
            ),
            chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
        )
    ) == ("没有章节标题的正文。",)


def test_import_formal_ranges_use_normalized_stored_unicode_and_empty_is_valid(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unicode.md"
    source.write_bytes(
        (
            "# 第1章 有内容\r\n\r\n"
            "第一行😀\r\n第二行\r\n\r\n"
            "# 第2章 空章\r\n"
        ).encode()
    )
    project = ProjectRepository.create(tmp_path / "project", "Imported Novel")

    report = ManuscriptImportService().import_file(project, source)

    chapters = ChapterRepository(project).list_chapters()
    assert report.imported_chapters == 2
    assert ChapterRepository(project).read_content_exact(chapters[0].id) == (
        "第一行😀\n第二行"
    )
    assert ChapterRepository(project).read_content_exact(chapters[1].id) == ""
    first = SearchRepository(project).read_formal_manuscript_chunks(
        chapters[0].id,
        expected_revision=0,
        expected_source_hash=_source_hash("第一行😀\n第二行"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    second = SearchRepository(project).read_formal_manuscript_chunks(
        chapters[1].id,
        expected_revision=0,
        expected_source_hash=_source_hash(""),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert first
    assert all(
        document.content
        == "第一行😀\n第二行"[document.source_start : document.source_end]
        for document in first
        if document.source_start is not None and document.source_end is not None
    )
    assert second == ()


def test_import_maintenance_failure_keeps_created_chapter_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "draft.txt"
    source.write_text("正文仍应提交。", encoding="utf-8")
    project = ProjectRepository.create(tmp_path / "project", "Imported Novel")
    maintenance_calls = 0

    def fail_maintenance(
        self: ChapterRevisionService,
        *_args: object,
        **_kwargs: object,
    ) -> FormalMaintenanceResult:
        nonlocal maintenance_calls
        maintenance_calls += 1
        raise RuntimeError(f"raw failure: {project.layout.root}: 正文仍应提交。")

    monkeypatch.setattr(
        ChapterRevisionService,
        "maintain_current_revision",
        fail_maintenance,
    )

    report = ManuscriptImportService().import_file(project, source)

    chapters = ChapterRepository(project).list_chapters()
    assert report.imported_chapters == 1
    assert maintenance_calls == 1
    assert ChapterRepository(project).read_content_exact(chapters[0].id) == "正文仍应提交。"
    with project.database.connect() as connection:
        formal_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_documents "
                "WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?",
                (chapters[0].id,),
            ).fetchone()[0]
        )
    assert formal_count == 0

    monkeypatch.undo()
    recovery = ChapterRevisionService(project).recover_current_revisions(limit=100)
    assert recovery.repaired_chapters == 1
    assert recovery.failures == ()


def test_import_second_create_failure_preserves_first_and_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "draft.md"
    source.write_text(
        "# 第1章 第一章\n\n开场正文\n\n# 第2章 第二章\n\n后续正文",
        encoding="utf-8",
    )
    project = ProjectRepository.create(tmp_path / "project", "Imported Novel")
    real_submit = ChapterRevisionService.submit_creation
    calls = 0

    def fail_second(
        self: ChapterRevisionService,
        *args: object,
        **kwargs: object,
    ) -> SubmittedRevision:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("injected second create failure")
        return real_submit(self, *args, **kwargs)

    monkeypatch.setattr(ChapterRevisionService, "submit_creation", fail_second)

    with pytest.raises(ValueError, match="injected second create failure"):
        ManuscriptImportService().import_file(project, source)

    chapters = ChapterRepository(project).list_chapters()
    assert len(chapters) == 1
    assert len(project.list_volumes()) == 2
    assert chapters[0].title == "第一章"
    assert ChapterRepository(project).read_content_exact(chapters[0].id) == "开场正文"
    assert SearchRepository(project).read_formal_manuscript_chunks(
        chapters[0].id,
        expected_revision=0,
        expected_source_hash=_source_hash(
            ChapterRepository(project).read_content_exact(chapters[0].id)
        ),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
