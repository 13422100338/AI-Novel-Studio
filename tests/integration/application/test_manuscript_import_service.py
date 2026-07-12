from pathlib import Path

from ai_novel_studio.application.manuscript_import_service import ManuscriptImportService
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


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
    assert report.imported_chapters == 2
    assert [chapter.declared_number for chapter in chapters] == ["第1章", "第2章"]
    assert [chapter.title for chapter in chapters] == ["雪夜来客", "没有寄出的信"]
    assert ChapterRepository(project).read_content(chapters[0].id) == "雪落下来。"


def test_import_plain_text_without_headings_creates_single_chapter(tmp_path: Path) -> None:
    source = tmp_path / "draft.txt"
    source.write_text("没有章节标题的正文。", encoding="utf-8")
    project = ProjectRepository.create(tmp_path / "project", "Imported Novel")

    report = ManuscriptImportService().import_file(project, source)

    chapters = ChapterRepository(project).list_chapters()
    assert report.imported_chapters == 1
    assert chapters[0].title == "draft"
    assert ChapterRepository(project).read_content(chapters[0].id) == "没有章节标题的正文。"
