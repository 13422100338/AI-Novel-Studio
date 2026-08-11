import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceResult,
    SubmittedRevision,
)
from ai_novel_studio.application.legacy_import.importer import LegacyProjectImporter
from ai_novel_studio.application.legacy_import.scanner import LegacyProjectScanner
from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
)
from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

_EMBEDDING_IDENTITY = EmbeddingIndexIdentity("provider-a", "embedding-model", 1)


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>' for text in paragraphs
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


def _legacy_project_with_two_valid_chapters(root: Path) -> Path:
    root.mkdir()
    meta = {
        "title": "Legacy Novel",
        "global_synopsis": "old synopsis",
        "characters": [],
        "volumes": [
            {
                "name": "Imported Volume",
                "synopsis": "volume synopsis",
                "chapters": [
                    {"name": "First", "synopsis": "one"},
                    {"name": "Second", "synopsis": "two"},
                ],
            }
        ],
    }
    (root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _write_docx(root / "Imported Volume" / "First.docx", ["第一章正文"])
    _write_docx(root / "Imported Volume" / "Second.docx", ["第二章正文"])
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
    assert (
        report.chapter_hashes[chapters[0].id]
        == hashlib.sha256("# 第一章\n正文内容".encode()).hexdigest()
    )
    search = SearchRepository(project)
    stored = search.read_formal_manuscript_chunks(
        chapters[0].id,
        expected_revision=0,
        expected_source_hash=report.chapter_hashes[chapters[0].id],
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert stored
    assert all(document.title == chapters[0].title for document in stored)
    assert all(document.volume_id == chapters[0].volume_id for document in stored)
    assert all(
        document.content == "# 第一章\n正文内容"[document.source_start : document.source_end]
        for document in stored
        if document.source_start is not None and document.source_end is not None
    )
    pending = search.pending_embedding_sources(_EMBEDDING_IDENTITY)
    assert {source.document_id for source in pending} == {document.id for document in stored}
    with project.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0
    report_files = list(project.layout.reports.glob("*.json"))
    assert len(report_files) == 1
    serialized = report_files[0].read_text(encoding="utf-8")
    assert str(source.resolve()) not in serialized


def test_import_empty_extracted_content_has_zero_formal_rows(
    tmp_path: Path,
) -> None:
    source = _legacy_project(tmp_path / "legacy")
    _write_docx(source / "Same Volume" / "Same Chapter.docx", [" \t"])
    preview = LegacyProjectScanner().scan(source)

    report = LegacyProjectImporter().import_project(preview, tmp_path / "v3")

    project = ProjectRepository.open(tmp_path / "v3")
    chapters = ChapterRepository(project).list_chapters()
    assert report.imported_chapters == 1
    assert ChapterRepository(project).read_content_exact(chapters[0].id) == ""
    assert report.chapter_hashes[chapters[0].id] == hashlib.sha256(b"").hexdigest()
    assert SearchRepository(project).read_formal_manuscript_chunks(
        chapters[0].id,
        expected_revision=0,
        expected_source_hash=report.chapter_hashes[chapters[0].id],
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    ) == ()


def test_import_maintenance_failure_is_sanitized_and_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _legacy_project(tmp_path / "legacy")
    preview = LegacyProjectScanner().scan(source)
    destination = tmp_path / "v3"
    maintenance_calls = 0

    def fail_maintenance(
        self: ChapterRevisionService,
        _chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        nonlocal maintenance_calls
        maintenance_calls += 1
        raise RuntimeError(f"raw failure: {self.project.layout.root}: private imported body")

    monkeypatch.setattr(
        ChapterRevisionService,
        "maintain_current_revision",
        fail_maintenance,
    )
    report = LegacyProjectImporter().import_project(preview, destination)

    project = ProjectRepository.open(destination)
    chapters = ChapterRepository(project).list_chapters()
    assert report.imported_chapters == 1
    assert maintenance_calls == 1
    assert len(chapters) == 1
    assert SearchRepository(project).read_formal_manuscript_chunks(
        chapters[0].id,
        expected_revision=0,
        expected_source_hash=report.chapter_hashes[chapters[0].id],
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    ) == ()
    serialized = next(project.layout.reports.glob("*.json")).read_text(encoding="utf-8")
    assert "raw failure" not in serialized
    assert "private imported body" not in serialized
    assert str(project.layout.root) not in serialized

    monkeypatch.undo()
    recovery = ChapterRevisionService(project).recover_current_revisions(limit=100)
    assert recovery.repaired_chapters == 1
    assert recovery.failures == ()


def test_import_second_create_failure_preserves_first_and_writes_no_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _legacy_project_with_two_valid_chapters(tmp_path / "legacy")
    preview = LegacyProjectScanner().scan(source)
    destination = tmp_path / "v3"
    real_submit = ChapterRevisionService.submit_creation
    submit_calls = 0

    def fail_second(
        self: ChapterRevisionService,
        *args: object,
        **kwargs: object,
    ) -> SubmittedRevision:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 2:
            raise ValueError("injected second create failure")
        return real_submit(self, *args, **kwargs)

    monkeypatch.setattr(ChapterRevisionService, "submit_creation", fail_second)
    with pytest.raises(ValueError, match="injected second create failure"):
        LegacyProjectImporter().import_project(preview, destination)

    project = ProjectRepository.open(destination)
    chapters = ChapterRepository(project).list_chapters()
    assert submit_calls == 2
    assert len(chapters) == 1
    assert len(project.list_volumes()) == 2
    assert ChapterRepository(project).read_content_exact(chapters[0].id) == "第一章正文"
    assert SearchRepository(project).read_formal_manuscript_chunks(
        chapters[0].id,
        expected_revision=0,
        expected_source_hash=hashlib.sha256("第一章正文".encode()).hexdigest(),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert list(project.layout.reports.glob("*.json")) == []


def test_import_detects_source_change_after_preview(tmp_path: Path) -> None:
    source = _legacy_project(tmp_path / "legacy")
    preview = LegacyProjectScanner().scan(source)
    _write_docx(source / "Same Volume" / "Same Chapter.docx", ["changed"])

    report = LegacyProjectImporter().import_project(preview, tmp_path / "v3")

    assert report.imported_chapters == 0
    assert any(issue.code == "source_changed" for issue in report.issues)
