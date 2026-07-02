import hashlib
import json
import zipfile
from pathlib import Path

from ai_novel_studio.application.legacy_import.importer import LegacyProjectImporter
from ai_novel_studio.application.legacy_import.scanner import LegacyProjectScanner
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{runs}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def _legacy_project(root: Path) -> Path:
    root.mkdir()
    meta = {
        "title": "Legacy Novel",
        "global_synopsis": "old synopsis",
        "characters": [],
        "volumes": [
            {
                "name": "Same Volume",
                "synopsis": "first",
                "chapters": [
                    {"name": "Same Chapter", "synopsis": "one", "ai_synopsis": "memory"},
                    {"name": "Missing", "synopsis": "two"},
                ],
            },
            {
                "name": "Same Volume",
                "synopsis": "second",
                "chapters": [{"name": "Broken", "synopsis": "three"}],
            },
        ],
    }
    (root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _write_docx(root / "Same Volume" / "Same Chapter.docx", ["# 第一章", "正文内容"])
    (root / "Same Volume" / "Broken.docx").write_bytes(b"not a docx")
    return root


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_scan_previews_duplicate_names_and_reports_bad_documents(tmp_path: Path) -> None:
    source = _legacy_project(tmp_path / "legacy")

    preview = LegacyProjectScanner().scan(source)

    assert preview.title == "Legacy Novel"
    assert preview.volume_count == 2
    assert preview.chapter_count == 3
    assert [volume.title for volume in preview.volumes] == ["Same Volume", "Same Volume"]
    assert {issue.code for issue in preview.issues} == {"document_missing", "document_corrupt"}
    assert all(not Path(issue.source).is_absolute() for issue in preview.issues)


def test_import_is_read_only_and_writes_verified_markdown_report(tmp_path: Path) -> None:
    source = _legacy_project(tmp_path / "legacy")
    before = _snapshot(source)
    preview = LegacyProjectScanner().scan(source)
    destination = tmp_path / "v3"

    report = LegacyProjectImporter().import_project(preview, destination)

    assert _snapshot(source) == before
    assert report.imported_volumes == 2
    assert report.imported_chapters == 1
    assert report.skipped_chapters == 2
    project = ProjectRepository.open(destination)
    assert [volume.title for volume in project.list_volumes()] == ["Same Volume", "Same Volume"]
    chapters = ChapterRepository(project).list_chapters()
    assert len(chapters) == 1
    assert ChapterRepository(project).read_content(chapters[0].id) == "# 第一章\n正文内容"
    assert report.chapter_hashes[chapters[0].id] == hashlib.sha256(
        "# 第一章\n正文内容".encode()
    ).hexdigest()
    report_files = list(project.layout.reports.glob("*.json"))
    assert len(report_files) == 1
    serialized = report_files[0].read_text(encoding="utf-8")
    assert str(source.resolve()) not in serialized


def test_import_detects_source_change_after_preview(tmp_path: Path) -> None:
    source = _legacy_project(tmp_path / "legacy")
    preview = LegacyProjectScanner().scan(source)
    _write_docx(source / "Same Volume" / "Same Chapter.docx", ["changed"])

    report = LegacyProjectImporter().import_project(preview, tmp_path / "v3")

    assert report.imported_chapters == 0
    assert any(issue.code == "source_changed" for issue in report.issues)
